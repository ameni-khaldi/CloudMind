# CloudMind Phase 4 — MinIO and Spark S3A

Docker Compose runs a single MinIO server and an idempotent bucket initializer. MinIO stores objects in the `cloudmind-phase4_minio-data` Docker volume. The Linux Spark runner mounts the project read-only, publishes existing Phase 1–3 files with the MinIO SDK, and uses Spark's Hadoop S3A filesystem for the analytical Parquet read, write, and read-back. Spark runs in `local[2]` for this deployment. All data stays on the local Docker installation.

## Start Docker Desktop on Windows

Open Docker Desktop from the Start menu, or start it from a regular PowerShell session:

```powershell
Start-Process -FilePath 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
docker version
docker compose version
wsl --list --verbose
```

Wait until `docker version` lists a Linux server. A missing `dockerDesktopLinuxEngine` named pipe means the client cannot reach the Linux daemon. If Docker Desktop is still starting, check its status and retry. If Windows reports access denied for the Docker configuration or WSL, repeat the diagnostics from your normal signed-in Windows session, where Docker Desktop runs. Use Docker Desktop's Troubleshoot view if startup continues to fail.

## Configure and run

From the repository root, copy `.env.phase4.example` to `.env.phase4` if needed and fill in private values for `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD`. The real file is ignored by Git. Keep the same credentials when restarting your local deployment.

| Variable | Use |
|---|---|
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | Local MinIO credentials. Compose injects them as environment variables. |
| `CLOUDMIND_BUCKET` | Bucket name, default `cloudmind`. |
| `MINIO_API_PORT`, `MINIO_CONSOLE_PORT` | Loopback ports, defaults `9000` and `9001`. |
| `CLOUDMIND_MINIO_ENDPOINT` | Service endpoint inside Docker, `http://minio:9000`. |
| `CLOUDMIND_S3A_JARS` | Location of the pinned connector JARs in the Spark image, `/opt/s3a`. |
| `CLOUDMIND_PHASE4_INTEGRATION` | Compose sets this to `1` for live integration tests. Ordinary local pytest runs skip those tests. |

```powershell
$composeArgs = @('--env-file', '.env.phase4', '-f', 'compose.phase4.yaml', '--profile', 'pipeline')
docker compose @composeArgs config --quiet
docker compose @composeArgs build
docker compose @composeArgs up -d minio bucket-init
docker compose @composeArgs wait bucket-init
docker compose @composeArgs ps -a
docker compose @composeArgs logs bucket-init
docker compose @composeArgs run --rm spark
docker compose @composeArgs run --rm spark python -m pytest -q -p no:cacheprovider tests/test_phase4.py
.\.venv\Scripts\python.exe -m pytest -q
```

Open the MinIO console at `http://127.0.0.1:9001` and sign in with the configured credentials. The API is at `http://127.0.0.1:9000`. To stop the services and keep the persisted objects, run `docker compose @composeArgs stop`.

## Object layout

Each publication uses a new run ID. Spark also uses a fresh output URI and errors if that output exists. Local input files and completed earlier runs are preserved.

| Prefix | Contents |
|---|---|
| `raw/<run>/` | Original hotel-review CSV. |
| `processed/<run>/` | Phase 1 hotel-review Parquet. |
| `analytics/<run>/` | Phase 2 Parquet outputs and the new Spark sentiment distribution under `phase4/`. |
| `models/<run>/` | Saved Phase 3 models under their original run IDs. |
| `reports/<run>/` | Phase 1–3 reports, snapshot manifest, and successful Phase 4 execution report. |

The manifest records source byte counts and SHA-256 digests. Verification streams the Phase 3 models and metadata back from MinIO and compares both fields. Spark checks that the input has 100,000 reviews with the Phase 1 column names and types. It compares the reloaded aggregate values and schema with the computed result and checks that the class totals account for all source rows. The published execution report includes the actual JVM class origins, input and output URIs, schemas, and row counts. A failed run exits with an error and may leave a partial prefix. The manifest is published after the source uploads finish, and the execution report is published after verification succeeds.

## Runtime compatibility

The installed PySpark 4.0.4 distribution has `hadoop-client-api-3.4.1.jar` and `hadoop-client-runtime-3.4.1.jar` and lacks S3A and AWS SDK JARs. The Linux runner supplies `hadoop-aws-3.4.1.jar` and AWS SDK v2 `bundle-2.24.6.jar`, matching the Hadoop 3.4.1 source dependency declarations. It checks the loaded Spark and Hadoop versions, both JAR origins, and the actual filesystem implementation before reading. [Hadoop AWS module POM](https://github.com/apache/hadoop/blob/rel/release-3.4.1/hadoop-tools/hadoop-aws/pom.xml) · [Hadoop dependency POM](https://github.com/apache/hadoop/blob/rel/release-3.4.1/hadoop-project/pom.xml)

The MinIO server image builds locally from the pinned upstream community release and checks the release commit before compilation. This avoids depending on a public MinIO registry tag remaining accessible. The SDK is used for initialization, file publication, and integrity checks. The Linux runner performs the Parquet transformation entirely through `s3a://`, avoiding the native Windows Parquet writer that failed in earlier phases. [MinIO upstream release](https://github.com/minio/minio/releases/tag/RELEASE.2025-09-07T16-13-09Z)

## Verification on 23 November 2026

- Initially the Docker CLI found no engine pipe, the Docker Desktop Windows service was stopped, and the restricted shell received access-denied errors from WSL and the user Docker configuration. Starting the installed Docker Desktop in the normal user context brought up the WSL 2 Linux engine, version 27.2.0. No Windows security settings or existing Docker resources were changed.
- A concurrent Spark-only build collided with the full build while exporting the same image tag. The full Compose build finished successfully and supplied the Spark image used for verification. Run a single Compose build as shown above.
- Compose configuration validation passed. MinIO built and reported `RELEASE.2025-09-07T16-13-09Z` at commit `07c3a429bfed433e49018cb0f78a52145d4bedeb`. The readiness and console endpoints returned HTTP 200. The bucket initializer exited 0, and Docker reported the named volume on the local driver.
- The MinIO SDK smoke test uploaded 32 source artifacts in `run-e42e60e8b91b4a72949fc33c5bcf9844`. The raw CSV, two model archives, and eight Phase 3 metadata files matched their source sizes and SHA-256 checksums on download.
- The end-to-end demo run `run-4ff3862adb014f2ca339df466c17e025` uploaded 32 artifacts and verified all 10 Phase 3 files. On Python 3.11.18 and Java 21.0.13.1, Spark 4.0.4 loaded Hadoop 3.4.1, `hadoop-aws-3.4.1.jar`, and AWS SDK v2 `bundle-2.24.6.jar`. Hadoop resolved the input to `org.apache.hadoop.fs.s3a.S3AFileSystem`.
- Spark read 100,000 reviews and verified the Phase 1 schema from `s3a://cloudmind/processed/run-4ff3862adb014f2ca339df466c17e025/hotel_reviews.parquet`. It wrote and reloaded three rows at `s3a://cloudmind/analytics/run-4ff3862adb014f2ca339df466c17e025/phase4/sentiment_distribution`, with fields `sentiment STRING` and `review_count BIGINT`. The counts were 23,088 negative, 25,996 neutral, and 50,916 positive. The execution report is in the bucket at `reports/run-4ff3862adb014f2ca339df466c17e025/phase4_execution.json`.
- The Linux demo logged warnings about native Hadoop libraries, S3A metrics and logging configuration, and unsupported stream sync on the object store. It exited 0 and verified the committed Parquet output by reading it back.
- The ordinary Windows pytest run reported **9 passed and 6 skipped** in 166.44 seconds. The six Phase 4 tests require the live Compose profile. Spark's Windows cleanup emitted an access-denied message after the test summary. Pytest exited 0.
- The live Compose suite reported **6 passed** in 18.87 seconds. It checked MinIO readiness, bucket initialization, raw object round-trip integrity, Spark Parquet read/write through S3A, row counts and schema, and model and metadata integrity. A separate download verified the saved Phase 4 execution report.
