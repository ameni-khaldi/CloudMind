import csv

import pytest

from ingestion import COLUMNS, DATA_PATH, read_reviews, run
from quality import profile, validation_errors


def test_full_dataset_and_parquet(spark, tmp_path):
    report = run(spark, DATA_PATH, tmp_path)
    with DATA_PATH.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        assert [row["review_id"] for row in report["first_ten"]] == [
            next(reader)["review_id"] for _ in range(10)
        ]
    assert report["validation_errors"] == []
    assert report["quality"]["distinct_review_ids"] == 100_000
    assert report["quality"]["hotels"] == 50
    assert report["parquet"]["rows"] == 100_000
    assert (tmp_path / "hotel_reviews.parquet").is_file()
    assert (tmp_path / "data_quality.json").is_file()


def test_header_drift_fails(spark, tmp_path):
    source = tmp_path / "drift.csv"
    source.write_text("unexpected,rating\n", encoding="utf-8")
    with pytest.raises(ValueError, match="CSV header differs"):
        read_reviews(spark, source)


def test_invalid_rating_and_duplicate_id_fail(spark, tmp_path):
    source = tmp_path / "bad.csv"
    with DATA_PATH.open(encoding="utf-8-sig", newline="") as original:
        row = next(csv.DictReader(original))
    row["rating"] = "6"
    with source.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows([row, row])
    metrics = profile(read_reviews(spark, source))
    assert metrics["invalid_ratings"] == 2
    assert metrics["duplicate_review_ids"] == 1
    assert metrics["exact_duplicate_rows"] == 1
    assert "invalid_ratings: 2" in validation_errors(metrics, expected_rows=2)
