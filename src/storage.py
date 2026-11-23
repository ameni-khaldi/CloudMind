from tempfile import NamedTemporaryFile

import pyarrow.parquet as pq


def export_verified_parquet(reviews, destination):
    # A single local dataset fits in memory. Arrow avoids Hadoop winutils on Windows.
    table = reviews.toArrow()
    with NamedTemporaryFile(dir=destination.parent, suffix=".parquet", delete=False) as temporary:
        staging_path = destination.parent / temporary.name

    try:
        pq.write_table(table, staging_path, compression="snappy")
        if not table.equals(pq.read_table(staging_path)):
            raise ValueError("Parquet values or Arrow schema differ from the validated data")

        readback = reviews.sparkSession.read.parquet(staging_path.resolve().as_posix())
        rows = readback.count()
        if readback.dtypes != reviews.dtypes or rows != table.num_rows:
            raise ValueError("Parquet row count or Spark column types differ from the validated data")

        staging_path.replace(destination)
    finally:
        staging_path.unlink(missing_ok=True)
    return {"path": str(destination), "rows": rows, "writer": "PyArrow", "compression": "snappy"}
