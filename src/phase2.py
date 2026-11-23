import argparse
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from pyspark.sql import functions as F, types as T

from analytics import DIMENSIONS, SENTIMENTS, STATUS, assert_sql_equivalence, metrics, sql_table, tables, transform, validate_table
from ingestion import OUTPUT_DIR, SCHEMA_DDL, start_spark
from storage import export_verified_parquet


SOURCE = OUTPUT_DIR / "hotel_reviews.parquet"
DESTINATION = OUTPUT_DIR / "phase2"


def run(spark, source=SOURCE, destination=DESTINATION):
    debut = perf_counter()
    source = source.resolve()
    destination = destination.resolve()
    if destination == source or source in destination.parents:
        raise ValueError("Le dossier de sortie doit être distinct de la source.")
    raw = spark.read.parquet(source.as_posix())
    schema = T.StructType.fromDDL(SCHEMA_DDL)
    if raw.dtypes != [(field.name, field.dataType.simpleString()) for field in schema]:
        raise ValueError("Le schéma Parquet diffère du contrat de la phase 1.")
    input_rows = raw.count()
    enriched = transform(raw)
    # Project the analytical fields before caching to avoid storing unused review text.
    fact = enriched.select(
        "review_id", "hotel_id", "hotel_name", "rating", "mois", "segment_client",
        "sentiment_normalise", "statut_resolution", "est_reclamation",
        "categorie_reclamation", "delai_reponse_heures", "delai_resolution_jours",
        "has_complaint", "response_time_hours", "resolved_in_days",
    ).repartition(spark.sparkContext.defaultParallelism, "hotel_id").cache()
    run_id = uuid4().hex
    view = f"cloudmind_{run_id}"
    try:
        invalid = (
            ~F.col("sentiment_normalise").isin(*SENTIMENTS)
            | ~F.col("segment_client").isin("vip", "standard", "loyalty")
            | ~F.col("has_complaint").isin(0, 1)
            | F.col("mois").isNull()
            | F.col("hotel_id").isNull()
            | F.col("hotel_name").isNull()
            | ~F.col("rating").between(1, 5)
            | (F.col("est_reclamation") & (
                ~F.col("statut_resolution").isin(*STATUS)
                | (F.length("categorie_reclamation") == 0)
                | F.col("categorie_reclamation").isNull()
            ))
            | (~F.col("est_reclamation") & (F.col("statut_resolution") != "not_applicable"))
            | ~F.col("response_time_hours").eqNullSafe(F.col("delai_reponse_heures"))
            | ~F.col("resolved_in_days").eqNullSafe(F.col("delai_resolution_jours"))
            | F.coalesce(F.col("response_time_hours") < 0, F.lit(False))
            | F.coalesce(F.col("resolved_in_days") < 0, F.lit(False))
        )
        base = fact.agg(
            F.count("*").alias("avis"),
            F.countDistinct("review_id").alias("identifiants"),
            F.count_if("est_reclamation").alias("reclamations"),
            F.count_if(F.coalesce(invalid, F.lit(True))).alias("invalides"),
        ).first().asDict()
        if base["avis"] != input_rows or base["identifiants"] != input_rows or base["invalides"]:
            raise ValueError(f"Transformation incohérente: {base}")

        fact.createOrReplaceTempView(view)
        staging = destination / f".{run_id}"
        staging.mkdir(parents=True)
        published = destination / f"run-{run_id}"
        report = {
            "source": str(source),
            "spark": {
                "version": spark.version,
                "master": spark.sparkContext.master,
                "parallelisme": spark.sparkContext.defaultParallelism,
                "partitions_shuffle": spark.conf.get("spark.sql.shuffle.partitions"),
                "execution_adaptative": spark.conf.get("spark.sql.adaptive.enabled"),
                "partitions_source": raw.rdd.getNumPartitions(),
                "partitions_transformation": fact.rdd.getNumPartitions(),
            },
            "validation": base,
            "schema_source": raw.schema.jsonValue(),
            "schema_enrichi": enriched.schema.jsonValue(),
            "secondes_lecture_transformation_validation": perf_counter() - debut,
            "tables": {},
        }
        report["indicateurs_globaux"] = metrics(fact, ()).first().asDict()
        comparison = fact.withColumn(
            "groupe_client", F.when(F.col("segment_client") == "vip", "VIP").otherwise("Régulier")
        )
        report["comparaison_vip_reguliers"] = [
            row.asDict() for row in metrics(comparison, ("groupe_client",)).orderBy("groupe_client").collect()
        ]
        complaints = fact.where("est_reclamation")
        report["categories_reclamations"] = [
            row.asDict() for row in complaints.groupBy("categorie_reclamation").count()
            .orderBy(F.desc("count"), "categorie_reclamation").collect()
        ]
        report["statuts_reclamations"] = [
            row.asDict() for row in metrics(complaints, ("statut_resolution",)).orderBy("statut_resolution").collect()
        ]
        for name, frame in tables(fact).items():
            start = perf_counter()
            frame = frame.cache()
            try:
                expected = (base["reclamations"] if name == "complaint_analytics" else input_rows, base["reclamations"])
                checks = validate_table(frame, name, expected)
                assert_sql_equivalence(frame, sql_table(spark, view, name), DIMENSIONS[name])
                filename = f"{name}.parquet"
                exported = export_verified_parquet(frame, staging / filename)
                report["tables"][name] = {
                    **checks, "comparaison_sql": "identique", "chemin": filename,
                    "lignes_relues": exported["rows"], "schema": frame.schema.jsonValue(),
                    "partitions_agregat": frame.rdd.getNumPartitions(),
                    "secondes_validation_sql_export": perf_counter() - start,
                }
            finally:
                frame.unpersist()
        report["secondes_pipeline"] = perf_counter() - debut
        (staging / "rapport_execution.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
        )
        staging.rename(published)
        return published, report
    finally:
        spark.catalog.dropTempView(view)
        fact.unpersist()


def main():
    parser = argparse.ArgumentParser(description="CloudMind, analyses Spark de la phase 2")
    parser.add_argument("--input", type=Path, default=SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DESTINATION)
    args = parser.parse_args()
    spark = start_spark()
    try:
        output, report = run(spark, args.input, args.output_dir)
        print(f"Résultats : {output}")
        print(f"Avis validés : {report['validation']['avis']}")
        for name, table in report["tables"].items():
            print(f"{name}: {table['lignes_relues']} lignes relues, SQL identique")
        print(f"Durée : {report['secondes_pipeline']:.3f} s")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
