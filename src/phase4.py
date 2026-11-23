"""Publish CloudMind artifacts and verify distributed Spark I/O against MinIO."""
import argparse
import hashlib
import io
import json
import os
import platform
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
SPARK_VERSION = "4.0.4"
HADOOP_VERSION = "3.4.1"
SDK_VERSION = "2.24.6"
S3A_CLASS = "org.apache.hadoop.fs.s3a.S3AFileSystem"
EXPECTED_REVIEWS = 100_000
CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class Storage:
    endpoint: str
    bucket: str
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)

    @classmethod
    def from_env(cls):
        return cls(
            os.environ["CLOUDMIND_MINIO_ENDPOINT"],
            os.environ.get("CLOUDMIND_BUCKET", "cloudmind"),
            os.environ["MINIO_ROOT_USER"],
            os.environ["MINIO_ROOT_PASSWORD"],
        )

    def client(self):
        from minio import Minio

        endpoint = urlsplit(self.endpoint)
        return Minio(
            endpoint.netloc, access_key=self.access_key, secret_key=self.secret_key,
            secure=endpoint.scheme == "https", region="us-east-1",
        )

    def check_health(self):
        with urlopen(self.endpoint.rstrip("/") + "/minio/health/ready", timeout=5) as response:
            return response.status

    def s3a(self, key):
        return f"s3a://{self.bucket}/{key}"


def initialize_bucket(client, bucket):
    from minio.error import S3Error

    if not client.bucket_exists(bucket):
        try:
            client.make_bucket(bucket)
        except S3Error as error:
            if error.code != "BucketAlreadyOwnedByYou" or not client.bucket_exists(bucket):
                raise


def artifact_paths(root):
    processed = root / "data" / "processed"
    yield "raw/hotel_reviews_100k.csv", root / "data" / "raw" / "hotel_reviews_100k.csv"
    parquet = processed / "hotel_reviews.parquet"
    if parquet.is_dir():
        for part in sorted(parquet.rglob("*.parquet")):
            yield "processed/hotel_reviews.parquet/" + part.relative_to(parquet).as_posix(), part
    else:
        yield "processed/hotel_reviews.parquet", parquet
    for name in ("data_quality.json", "phase1-run.txt"):
        yield f"reports/phase1/{name}", processed / name

    for run in sorted((processed / "phase2").glob("run-*")):
        yield f"reports/phase2/{run.name}/rapport_execution.json", run / "rapport_execution.json"
        for part in sorted(run.rglob("*.parquet")):
            yield f"analytics/phase2/{run.name}/{part.relative_to(run).as_posix()}", part

    for run in sorted((processed / "phase3").glob("run-*")):
        for name in ("rapport_execution.json", "model_comparison.json", "evaluation_metrics.json", "confusion_matrix.json"):
            yield f"reports/phase3/{run.name}/{name}", run / name
        model = "pipeline/text_classifier_state.json"
        yield f"models/phase3/{run.name}/{model}", run / model


def publish_snapshot(client, bucket, root=ROOT):
    artifacts = list(artifact_paths(root))
    for prefix in ("raw/", "processed/", "analytics/", "models/", "reports/phase3/"):
        if not any(key.startswith(prefix) for key, _ in artifacts):
            raise FileNotFoundError(f"No CloudMind artifacts under {prefix}")
    for _, path in artifacts:
        if not path.is_file():
            raise FileNotFoundError(path)

    run_id = f"run-{uuid4().hex}"
    manifest = {"run_id": run_id, "objects": []}
    for name, path in artifacts:
        prefix, suffix = name.split("/", 1)
        key = f"{prefix}/{run_id}/{suffix}"
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        client.fput_object(bucket, key, str(path), metadata={"sha256": digest})
        manifest["objects"].append({"key": key, "size": path.stat().st_size, "sha256": digest})
    put_json(client, bucket, f"reports/{run_id}/manifest.json", manifest)
    return manifest


def put_json(client, bucket, key, value):
    data = (json.dumps(value, indent=2) + "\n").encode("utf-8")
    client.put_object(bucket, key, io.BytesIO(data), len(data), content_type="application/json")


def verify_download(client, bucket, entry):
    response = client.get_object(bucket, entry["key"])
    try:
        digest = hashlib.sha256()
        size = 0
        for chunk in response.stream(CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
        if size != entry["size"] or digest.hexdigest() != entry["sha256"]:
            raise ValueError(f"Downloaded data differs from source: {entry['key']}")
    finally:
        response.close()
        response.release_conn()


def verify_phase3(client, bucket, manifest):
    entries = [
        entry for entry in manifest["objects"]
        if entry["key"].startswith(f"models/{manifest['run_id']}/phase3/")
        or entry["key"].startswith(f"reports/{manifest['run_id']}/phase3/")
    ]
    for entry in entries:
        verify_download(client, bucket, entry)
    return len(entries)


def start_s3a_spark(storage):
    from pyspark.sql import SparkSession

    jar_dir = Path(os.environ["CLOUDMIND_S3A_JARS"]).resolve()
    jars = [jar_dir / f"hadoop-aws-{HADOOP_VERSION}.jar", jar_dir / f"bundle-{SDK_VERSION}.jar"]
    for jar in jars:
        if not jar.is_file():
            raise FileNotFoundError(jar)
    os.environ["AWS_ACCESS_KEY_ID"] = storage.access_key
    os.environ["AWS_SECRET_ACCESS_KEY"] = storage.secret_key
    return (
        SparkSession.builder.appName("CloudMind-Phase4")
        .master("local[2]")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "4")
        .config("spark.sql.warehouse.dir", "/tmp/cloudmind-spark-warehouse")
        .config("spark.jars", ",".join(jar.as_uri() for jar in jars))
        .config("spark.hadoop.fs.s3a.impl", S3A_CLASS)
        .config("spark.hadoop.fs.s3a.endpoint", storage.endpoint)
        .config("spark.hadoop.fs.s3a.endpoint.region", "us-east-1")
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", str(storage.endpoint.startswith("https:")).lower())
        .config("spark.hadoop.fs.s3a.aws.credentials.provider", "software.amazon.awssdk.auth.credentials.EnvironmentVariableCredentialsProvider")
        .config("spark.pyspark.python", os.environ.get("PYSPARK_PYTHON", "python"))
        .getOrCreate()
    )


def inspect_spark(spark, input_uri):
    jvm = spark.sparkContext._jvm
    loader = jvm.java.lang.Thread.currentThread().getContextClassLoader()
    runtime = {
        "python": platform.python_version(),
        "spark": spark.version,
        "hadoop": jvm.org.apache.hadoop.util.VersionInfo.getVersion(),
        "java": jvm.java.lang.System.getProperty("java.version"),
    }
    for key, class_name in (
        ("hadoop_aws", S3A_CLASS),
        ("aws_sdk", "software.amazon.awssdk.services.s3.S3Client"),
    ):
        origin = loader.loadClass(class_name).getProtectionDomain().getCodeSource().getLocation()
        runtime[key] = str(origin)
    fs = jvm.org.apache.hadoop.fs.Path(input_uri).getFileSystem(spark.sparkContext._jsc.hadoopConfiguration())
    runtime["filesystem"] = fs.getClass().getName()
    if (
        runtime["spark"] != SPARK_VERSION
        or runtime["hadoop"] != HADOOP_VERSION
        or not runtime["hadoop_aws"].endswith(f"hadoop-aws-{HADOOP_VERSION}.jar")
        or not runtime["aws_sdk"].endswith(f"bundle-{SDK_VERSION}.jar")
        or runtime["filesystem"] != S3A_CLASS
    ):
        raise RuntimeError(f"Unexpected Spark S3A runtime: {runtime}")
    return runtime


def process_cloud_reviews(spark, input_uri, output_uri):
    from pyspark.sql import functions as F, types as T

    from ingestion import SCHEMA_DDL

    if any(urlsplit(uri).scheme != "s3a" or not urlsplit(uri).netloc for uri in (input_uri, output_uri)):
        raise ValueError("Phase 4 requires s3a:// input and output URIs")
    runtime = inspect_spark(spark, input_uri)
    reviews = spark.read.parquet(input_uri)
    input_rows = reviews.count()
    expected_schema = T.StructType.fromDDL(SCHEMA_DDL)
    if input_rows != EXPECTED_REVIEWS or reviews.schema.simpleString() != expected_schema.simpleString():
        raise ValueError(f"Unexpected source row count or schema: {input_rows}, {reviews.schema}")

    distribution = reviews.groupBy("sentiment").agg(F.count("*").alias("review_count"))
    expected = distribution.collect()
    distribution.write.mode("errorifexists").parquet(output_uri)
    reloaded = spark.read.parquet(output_uri)
    actual = reloaded.orderBy("sentiment").collect()
    if (
        reloaded.dtypes != [("sentiment", "string"), ("review_count", "bigint")]
        or len(actual) != len(expected)
        or set(actual) != set(expected)
        or sum(row.review_count for row in actual) != input_rows
    ):
        raise ValueError("S3A Parquet read-back failed schema or row integrity checks")
    return {
        "runtime": runtime,
        "input_uri": input_uri,
        "input_rows": input_rows,
        "input_schema": reviews.schema.jsonValue(),
        "output_uri": output_uri,
        "output_rows": len(actual),
        "output_schema": reloaded.schema.jsonValue(),
        "sentiment_distribution": [row.asDict() for row in actual],
    }


def run_cloud_demo(storage, manifest):
    run_id = manifest["run_id"]
    spark = start_s3a_spark(storage)
    try:
        return process_cloud_reviews(
            spark,
            storage.s3a(f"processed/{run_id}/hotel_reviews.parquet"),
            storage.s3a(f"analytics/{run_id}/phase4/sentiment_distribution"),
        )
    finally:
        spark.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "run"))
    args = parser.parse_args()
    storage = Storage.from_env()
    client = storage.client()
    if args.command == "init":
        initialize_bucket(client, storage.bucket)
        print(f"Bucket ready: {storage.bucket}")
        return

    manifest = publish_snapshot(client, storage.bucket)
    print(f"Published {len(manifest['objects'])} objects in {manifest['run_id']}", flush=True)
    verified = verify_phase3(client, storage.bucket, manifest)
    result = run_cloud_demo(storage, manifest)
    result["verified_phase3_objects"] = verified
    put_json(client, storage.bucket, f"reports/{manifest['run_id']}/phase4_execution.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
