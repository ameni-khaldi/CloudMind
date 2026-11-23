from pyspark.sql import functions as F


def profile(reviews):
    metrics = reviews.agg(
        F.count("*").alias("rows"),
        F.countDistinct("hotel_id").alias("hotels"),
        F.countDistinct("review_id").alias("distinct_review_ids"),
        F.min("review_date").alias("first_review_date"),
        F.max("review_date").alias("last_review_date"),
        F.count_if(~F.coalesce(F.col("rating").between(1, 5), F.lit(False))).alias("invalid_ratings"),
        F.count_if(~F.coalesce(F.col("review_id").rlike(r"^REV[0-9]+$"), F.lit(False))).alias("invalid_review_ids"),
        F.count_if(~F.coalesce(F.col("hotel_id").rlike(r"^HTL[0-9]+$"), F.lit(False))).alias("invalid_hotel_ids"),
        F.count_if(~F.col("is_synthetic").eqNullSafe(1)).alias("non_synthetic_rows"),
        F.count_if(~F.coalesce(F.col("dataset_split").isin("train", "validation", "test"), F.lit(False))).alias("invalid_splits"),
    ).first().asDict()
    metrics["null_counts"] = reviews.agg(
        *(F.count_if(F.col(name).isNull()).alias(name) for name in reviews.columns)
    ).first().asDict()
    metrics["duplicate_review_ids"] = (
        reviews.where(F.col("review_id").isNotNull())
        .groupBy("review_id").count().where(F.col("count") > 1).count()
    )
    # When IDs are unique and complete, exact duplicate rows are impossible.
    if metrics["duplicate_review_ids"] or metrics["null_counts"]["review_id"]:
        metrics["exact_duplicate_rows"] = metrics["rows"] - reviews.distinct().count()
    else:
        metrics["exact_duplicate_rows"] = 0
    return metrics


def explore(reviews):
    return {
        "ratings": [row.asDict() for row in reviews.groupBy("rating").count().orderBy("rating").collect()],
        "splits": [row.asDict() for row in reviews.groupBy("dataset_split").count().orderBy("dataset_split").collect()],
        "resolution": [row.asDict() for row in reviews.groupBy("resolution_status").agg(
            F.count("*").alias("rows"),
            F.count("response_time_hours").alias("has_response_time"),
            F.count("resolved_in_days").alias("has_resolution_days"),
        ).orderBy("resolution_status").collect()],
        "top_hotels": [row.asDict() for row in reviews.groupBy("hotel_id", "hotel_name").agg(
            F.count("*").alias("reviews"), F.round(F.avg("rating"), 2).alias("mean_rating")
        ).orderBy(F.desc("reviews"), "hotel_id", "hotel_name").limit(10).collect()],
    }


def validation_errors(metrics, expected_rows):
    errors = []
    if metrics["rows"] != expected_rows:
        errors.append(f"Expected {expected_rows} rows, found {metrics['rows']}")
    for name in (
        "invalid_ratings", "invalid_review_ids", "invalid_hotel_ids", "non_synthetic_rows",
        "invalid_splits", "duplicate_review_ids", "exact_duplicate_rows",
    ):
        if metrics[name]:
            errors.append(f"{name}: {metrics[name]}")
    for name, count in metrics["null_counts"].items():
        if count and name not in {"response_time_hours", "resolved_in_days"}:
            errors.append(f"Unexpected nulls in {name}: {count}")
    return errors
