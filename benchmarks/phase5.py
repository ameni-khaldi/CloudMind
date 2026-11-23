"""Compare equivalent Spark and Pandas transformations on the existing review data."""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
from statistics import median, stdev
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pyspark.sql import functions as F

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ingestion import start_spark

SOURCE = ROOT / "data" / "processed" / "hotel_reviews.parquet"
FIELDS = ("mois", "sentiment", "avis", "note_moyenne", "reclamations")
INPUTS = ("review_date", "sentiment", "rating", "has_complaint")


def read_spark(spark, path):
    frame = spark.read.parquet(path.as_posix()).persist()
    frame.count()
    return frame


def transform_spark(frame):
    return [
        tuple(row) for row in frame.withColumn("mois", F.date_format("review_date", "yyyy-MM"))
        .groupBy("mois", "sentiment")
        .agg(F.count("*").alias("avis"), F.avg("rating").alias("note_moyenne"),
             F.sum("has_complaint").alias("reclamations"))
        .orderBy("mois", "sentiment").collect()
    ]


def transform_pandas(frame):
    grouped = (frame.assign(mois=pd.to_datetime(frame.review_date).dt.strftime("%Y-%m"))
               .groupby(["mois", "sentiment"], sort=True, dropna=False)
               .agg(avis=("rating", "size"), note_moyenne=("rating", "mean"),
                    reclamations=("has_complaint", "sum")).reset_index())
    return list(grouped.itertuples(index=False, name=None))


def export_rows(path, records):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(FIELDS)
        writer.writerows(records)


def measure(engine, spark, source, output):
    start = perf_counter()
    frame = read_spark(spark, source) if engine == "Spark" else pd.read_parquet(source)
    read = perf_counter()
    try:
        records = transform_spark(frame) if engine == "Spark" else transform_pandas(frame)
        processed = perf_counter()
        export_rows(output, records)
        exported = perf_counter()
    finally:
        if engine == "Spark":
            frame.unpersist(blocking=True)
    return records, {"read": read - start, "process": processed - read, "export": exported - processed}


def verify_equivalence(left, right, size):
    if len(left) != len(right) or sum(row[2] for row in left) != size:
        raise ValueError("Le nombre de lignes agrégées ou d’avis diffère.")
    for a, b in zip(left, right):
        if a[:3] != b[:3] or a[4] != b[4] or not math.isclose(a[3], b[3], rel_tol=1e-12):
            raise ValueError(f"Agrégats différents pour {a[:2]}")


def configuration(spark, sizes, warmups, repeats, inputs):
    jvm = spark.sparkContext._jvm
    operating_system = jvm.java.lang.management.ManagementFactory.getOperatingSystemMXBean()
    return {
        "platform": platform.platform(), "processor": platform.processor(),
        "logical_cpus": os.cpu_count(), "memory_bytes": operating_system.getTotalMemorySize(),
        "python": platform.python_version(), "java": jvm.java.lang.System.getProperty("java.version"),
        "spark": spark.version, "spark_master": spark.sparkContext.master,
        "spark_parallelism": spark.sparkContext.defaultParallelism,
        "spark_shuffle_partitions": spark.conf.get("spark.sql.shuffle.partitions"),
        "spark_adaptive": spark.conf.get("spark.sql.adaptive.enabled"),
        "pandas": pd.__version__, "pyarrow": pa.__version__,
        "sizes": sizes, "warmups": warmups, "repeats": repeats, "inputs": inputs,
        "selection": "Premières N lignes physiques, mêmes quatre colonnes, Parquet Snappy",
        "read_definition": "Lecture matérialisée, incluant persist/count pour Spark",
        "process_definition": "Agrégation et matérialisation des résultats en tuples Python",
        "export_definition": "Même écrivain CSV Python, résultat local, fermeture de fichier incluse",
        "excluded": "Démarrage JVM, préparation des Parquet et suppression du cache Spark",
        "disk_cache": "Cache du système d’exploitation conservé, ordre des moteurs alterné",
    }


def run(spark, sizes, warmups, repeats):
    measurements, summary, inputs = [], [], []
    data = pq.read_table(SOURCE, columns=list(INPUTS))
    with TemporaryDirectory(prefix="cloudmind-benchmark-") as directory:
        folder = Path(directory)
        for size in sizes:
            if not 1 <= size <= data.num_rows:
                raise ValueError(f"Taille hors limites: {size}")
            source, output = folder / f"reviews-{size}.parquet", folder / f"output-{size}.csv"
            pq.write_table(data.slice(0, size), source, compression="snappy", row_group_size=10_000)
            with source.open("rb") as stream:
                inputs.append({"rows": size, "bytes": source.stat().st_size,
                               "sha256": hashlib.file_digest(stream, "sha256").hexdigest()})
            for index in range(warmups + repeats):
                pair = {}
                engines = ("Spark", "Pandas") if index % 2 == 0 else ("Pandas", "Spark")
                for engine in engines:
                    records, times = measure(engine, spark, source, output)
                    pair[engine] = records
                    if index >= warmups:
                        for stage, seconds in times.items():
                            measurements.append({"rows": size, "engine": engine, "repeat": index - warmups + 1,
                                                 "stage": stage, "seconds": seconds})
                verify_equivalence(pair["Spark"], pair["Pandas"], size)
            print(f"{size:,} reviews: Spark and Pandas results match", flush=True)
            for engine in ("Spark", "Pandas"):
                for stage in ("read", "process", "export"):
                    values = [item["seconds"] for item in measurements if
                              (item["rows"], item["engine"], item["stage"]) == (size, engine, stage)]
                    summary.append({"rows": size, "engine": engine, "stage": stage, "median_s": median(values),
                                    "stdev_s": stdev(values), "min_s": min(values), "max_s": max(values)})
    return {"configuration": configuration(spark, sizes, warmups, repeats, inputs),
            "measurements": measurements, "summary": summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[10_000, 50_000, 100_000])
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks" / "phase5_results.json")
    args = parser.parse_args()
    if args.warmups < 1 or args.repeats < 2 or len(set(args.sizes)) != len(args.sizes):
        parser.error("Au moins un échauffement, deux répétitions et des tailles distinctes sont requis.")
    spark = start_spark()
    try:
        report = run(spark, args.sizes, args.warmups, args.repeats)
    finally:
        spark.stop()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with args.output.with_suffix(".csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(report["measurements"][0]))
        writer.writeheader()
        writer.writerows(report["measurements"])


if __name__ == "__main__":
    main()
