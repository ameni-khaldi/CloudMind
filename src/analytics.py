from pyspark.sql import Window, functions as F


SENTIMENTS = ("positive", "neutral", "negative")
STATUS = ("resolved", "unresolved", "in_progress")
DIMENSIONS = {
    "hotel_kpis": ("hotel_id", "hotel_name"),
    "monthly_trends": ("mois",),
    "customer_segments": ("segment_client",),
    "sentiment_distribution": ("segment_client", "sentiment_normalise"),
    "complaint_analytics": ("hotel_id", "hotel_name", "segment_client", "categorie_reclamation", "statut_resolution"),
}
PERCENTAGES = {
    **{f"pct_{label}": (label, "avis") for label in SENTIMENTS},
    "pct_reclamations": ("reclamations", "avis"),
    "pct_non_resolues": ("non_resolues", "reclamations"),
}
METRIC_SQL = {
    "avis": "count(*)",
    "note_moyenne": "avg(rating)",
    **{label: f"count_if(sentiment_normalise = '{label}')" for label in SENTIMENTS},
    "reclamations": "count_if(est_reclamation)",
    "non_resolues": "count_if(est_reclamation AND statut_resolution = 'unresolved')",
    "reponses_mesurees": "count(delai_reponse_heures)",
    "resolutions_mesurees": "count(delai_resolution_jours)",
    "reponse_moyenne_heures": "avg(delai_reponse_heures)",
    "resolution_moyenne_jours": "avg(delai_resolution_jours)",
}


def transform(source):
    complaint = F.col("has_complaint") == 1
    status = F.lower(F.trim("resolution_status"))
    return source.select(
        "*",
        F.trunc("review_date", "month").alias("mois"),
        F.lower(F.trim("customer_segment")).alias("segment_client"),
        F.lower(F.trim("sentiment")).alias("sentiment_normalise"),
        status.alias("statut_resolution"),
        complaint.alias("est_reclamation"),
        F.when(complaint, F.lower(F.trim("primary_aspect"))).alias("categorie_reclamation"),
        F.when(complaint & status.isin("resolved", "in_progress"), F.col("response_time_hours"))
        .alias("delai_reponse_heures"),
        F.when(complaint & (status == "resolved"), F.col("resolved_in_days"))
        .alias("delai_resolution_jours"),
    )


def percentage(numerator, denominator):
    return 100 * F.try_divide(F.col(numerator), F.col(denominator))


def metrics(frame, keys):
    complaint = F.col("est_reclamation")
    grouped = frame.groupBy(*keys).agg(
        F.count("*").alias("avis"),
        F.avg("rating").alias("note_moyenne"),
        *(F.count_if(F.col("sentiment_normalise") == label).alias(label) for label in SENTIMENTS),
        F.count_if(complaint).alias("reclamations"),
        F.count_if(complaint & (F.col("statut_resolution") == "unresolved")).alias("non_resolues"),
        F.count("delai_reponse_heures").alias("reponses_mesurees"),
        F.count("delai_resolution_jours").alias("resolutions_mesurees"),
        F.avg("delai_reponse_heures").alias("reponse_moyenne_heures"),
        F.avg("delai_resolution_jours").alias("resolution_moyenne_jours"),
    )
    return grouped.select(
        "*", *(percentage(*pair).alias(name) for name, pair in PERCENTAGES.items())
    )


def tables(frame):
    result = {
        name: metrics(frame.where("est_reclamation") if name == "complaint_analytics" else frame, keys)
        for name, keys in DIMENSIONS.items()
    }
    sentiment = result["sentiment_distribution"]
    result["sentiment_distribution"] = sentiment.withColumn(
        "pct_segment", 100 * F.try_divide("avis", F.sum("avis").over(Window.partitionBy("segment_client")))
    )
    return result


def sql_table(spark, view, name):
    keys = ", ".join(DIMENSIONS[name])
    measures = ", ".join(f"{expression} AS {alias}" for alias, expression in METRIC_SQL.items())
    percentages = ", ".join(
        f"100 * try_divide({numerator}, {denominator}) AS {alias}"
        for alias, (numerator, denominator) in PERCENTAGES.items()
    )
    where = "WHERE est_reclamation" if name == "complaint_analytics" else ""
    if name == "sentiment_distribution":
        percentages += ", 100 * try_divide(avis, sum(avis) OVER (PARTITION BY segment_client)) AS pct_segment"
    return spark.sql(f"""
        WITH groupe AS (
            SELECT {keys}, {measures}
            FROM {view} {where}
            GROUP BY {keys}
        )
        SELECT *, {percentages} FROM groupe
    """)


def validate_table(frame, name, expected):
    invalid = (
        (F.col("positive") + F.col("neutral") + F.col("negative") != F.col("avis"))
        | (F.col("non_resolues") > F.col("reclamations"))
        | (F.col("reclamations") > F.col("avis"))
    )
    for alias, (numerator, denominator) in PERCENTAGES.items():
        value = F.col(alias)
        invalid |= (~value.eqNullSafe(percentage(numerator, denominator))) | ~value.between(0, 100)
    checks = frame.agg(
        F.count("*").alias("lignes"),
        F.sum("avis").alias("avis"),
        F.sum("reclamations").alias("reclamations"),
        F.count_if(invalid).alias("groupes_invalides"),
    ).first().asDict()
    if checks["groupes_invalides"] or (checks["avis"], checks["reclamations"]) != expected:
        raise ValueError(f"{name}: agrégats incohérents: {checks}")
    if name == "sentiment_distribution":
        by_segment = frame.groupBy("segment_client").agg(F.sum("pct_segment").alias("total"))
        if by_segment.where(F.abs(F.col("total") - 100) > 1e-8).count():
            raise ValueError("La distribution par segment doit totaliser 100 %.")
    return checks


def assert_sql_equivalence(frame, sql, keys):
    joined = frame.alias("df").join(sql.alias("sql"), list(keys), "full")
    mismatch = F.lit(False)
    for name, kind in frame.dtypes:
        if name in keys:
            continue
        left, right = F.col(f"df.{name}"), F.col(f"sql.{name}")
        equal = left.eqNullSafe(right)
        if kind == "double":
            equal |= F.coalesce(F.abs(left - right) <= 1e-8, F.lit(False))
        mismatch |= ~equal
    if joined.where(mismatch).limit(1).count():
        raise ValueError(f"Résultats DataFrame et SQL différents pour {keys}")
