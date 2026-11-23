import os

import pytest

from phase4 import (
    EXPECTED_REVIEWS,
    S3A_CLASS,
    Storage,
    initialize_bucket,
    publish_snapshot,
    run_cloud_demo,
    verify_download,
    verify_phase3,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("CLOUDMIND_PHASE4_INTEGRATION") != "1",
    reason="Run Phase 4 integration tests through Docker Compose",
)


@pytest.fixture(scope="module")
def object_store():
    storage = Storage.from_env()
    return storage, storage.client()


@pytest.fixture(scope="module")
def snapshot(object_store):
    storage, client = object_store
    return publish_snapshot(client, storage.bucket)


@pytest.fixture(scope="module")
def cloud_result(object_store, snapshot):
    storage, _ = object_store
    return run_cloud_demo(storage, snapshot)


def test_minio_readiness(object_store):
    storage, _ = object_store
    assert storage.check_health() == 200


def test_initialized_bucket(object_store):
    storage, client = object_store
    assert client.bucket_exists(storage.bucket)
    initialize_bucket(client, storage.bucket)
    assert client.bucket_exists(storage.bucket)


def test_upload_and_download_dataset(object_store, snapshot):
    storage, client = object_store
    raw = next(entry for entry in snapshot["objects"] if entry["key"].startswith("raw/"))
    verify_download(client, storage.bucket, raw)
    assert client.stat_object(storage.bucket, f"reports/{snapshot['run_id']}/manifest.json").size > 0


def test_cloud_parquet_read_write(object_store, cloud_result):
    storage, client = object_store
    assert cloud_result["runtime"]["filesystem"] == S3A_CLASS
    assert cloud_result["input_uri"].startswith(f"s3a://{storage.bucket}/processed/")
    prefix = cloud_result["output_uri"].removeprefix(f"s3a://{storage.bucket}/")
    assert prefix.startswith("analytics/")
    outputs = client.list_objects(storage.bucket, prefix=prefix + "/", recursive=True)
    assert any(obj.object_name.endswith(".parquet") for obj in outputs)
    assert [(field["name"], field["type"]) for field in cloud_result["output_schema"]["fields"]] == [
        ("sentiment", "string"),
        ("review_count", "long"),
    ]


def test_s3a_row_count_integrity(cloud_result):
    assert cloud_result["input_rows"] == EXPECTED_REVIEWS
    assert cloud_result["output_rows"] == 3
    assert {row["sentiment"]: row["review_count"] for row in cloud_result["sentiment_distribution"]} == {
        "negative": 23_088,
        "neutral": 25_996,
        "positive": 50_916,
    }


def test_model_and_metadata_integrity(object_store, snapshot):
    storage, client = object_store
    models = [entry for entry in snapshot["objects"] if entry["key"].startswith("models/")]
    assert models
    assert verify_phase3(client, storage.bucket, snapshot) == len(models) * 5
