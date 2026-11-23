import argparse
import csv
import json
import os
import platform
import sys
from pathlib import Path

import pyspark
from pyspark.sql import SparkSession, types as T

from quality import explore, profile, validation_errors
from storage import export_verified_parquet


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "raw" / "hotel_reviews_100k.csv"
OUTPUT_DIR = ROOT / "data" / "processed"

# Ordered contract from the existing CSV header and its observed Spark schema.
FIELD_GROUPS = (
    ("string", "review_id hotel_id hotel_name city country"),
    ("int", "hotel_stars"),
    ("string", "customer_id customer_segment trip_type room_type booking_channel"),
    ("int", "stay_nights"),
    ("date", "review_date check_in_date"),
    ("int", "rating"),
    ("string", "sentiment"),
    ("double", "sentiment_score"),
    ("string", "review_title review_text primary_aspect secondary_aspect"),
    ("int", "has_complaint"),
    ("string", "complaint_severity resolution_status"),
    ("double", "response_time_hours"),
    ("int", "resolved_in_days would_recommend helpful_votes"),
    ("string", "language"),
    ("int", "is_synthetic"),
    ("string", "dataset_split"),
)
SCHEMA_DDL = ", ".join(f"{name} {kind}" for kind, names in FIELD_GROUPS for name in names.split())
COLUMNS = [name for _, names in FIELD_GROUPS for name in names.split()]


def read_reviews(spark, path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        header = next(csv.reader(source), [])
    if header != COLUMNS:
        raise ValueError(f"CSV header differs from the CloudMind contract: {header}")
    schema = T.StructType.fromDDL(SCHEMA_DDL)
    return (
        spark.read.schema(schema)
        .option("header", True)
        .option("enforceSchema", False)
        .option("multiLine", True)
        .option("escape", '"')
        .option("mode", "FAILFAST")
        .csv(path.resolve().as_posix())
    )


def start_spark():
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)
    return (
        SparkSession.builder.appName("CloudMind-HotelReviews")
        .master(os.environ.get("CLOUDMIND_SPARK_MASTER", "local[2]"))
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.ui.enabled", "false")
        .config("spark.hadoop.fs.permissions.enabled", "false")
        .config("spark.hadoop.fs.file.impl.disable.cache", "true")
        .getOrCreate()
    )


def run(spark, path, output_dir, expected_rows=100_000):
    reviews = read_reviews(spark, path)
    reviews.printSchema()
    # The multiline reader scans this single CSV in one input partition.
    samples = [row.asDict() for row in reviews.take(10)]
    for row in samples:
        print(json.dumps(row, ensure_ascii=True, default=str))

    reviews = reviews.cache()
    try:
        metrics = profile(reviews)
        print(f"TOTAL REVIEWS: {metrics['rows']}")
        errors = validation_errors(metrics, expected_rows)
        report = {
            "source": str(path),
            "runtime": {
                "python": platform.python_version(),
                "python_executable": sys.executable,
                "pyspark": pyspark.__version__,
                "spark": spark.version,
                "master": spark.sparkContext.master,
                "java": spark.sparkContext._jvm.java.lang.System.getProperty("java.version"),
                "java_home": os.environ.get("JAVA_HOME"),
            },
            "schema": reviews.schema.jsonValue(),
            "first_ten": samples,
            "quality": metrics,
            "exploration": explore(reviews),
            "validation_errors": errors,
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / "data_quality.json"
        if not errors:
            report["parquet"] = export_verified_parquet(reviews, output_dir / "hotel_reviews.parquet")
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        print(json.dumps(metrics, indent=2, default=str))
        print(f"DATA QUALITY REPORT: {report_path}")
        if errors:
            raise ValueError("Data validation failed: " + ", ".join(errors))
        print(f"PARQUET READBACK ROWS: {report['parquet']['rows']}")
        return report
    finally:
        reviews.unpersist()


def main():
    parser = argparse.ArgumentParser(description="Validate and export the CloudMind reviews")
    parser.add_argument("--input", type=Path, default=DATA_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    spark = start_spark()
    try:
        run(spark, args.input, args.output_dir)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
