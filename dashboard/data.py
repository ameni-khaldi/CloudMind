"""Read-only inputs and analytics for CloudMind Phase 5."""
import io
import json
import os
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
PHASE2 = "run-fa137ff05cee42c89e5622d5eec78ca2"
PHASE3 = "run-d907a7f0f9bd491ca4723205d208fddd"
PHASE4 = "run-4ff3862adb014f2ca339df466c17e025"
TABLES = ("hotel_kpis", "monthly_trends", "customer_segments", "sentiment_distribution", "complaint_analytics")
COLUMNS = [
    "hotel_id", "hotel_name", "review_date", "customer_id", "customer_segment", "sentiment", "rating",
    "has_complaint", "resolution_status", "primary_aspect", "response_time_hours", "resolved_in_days",
]
SENTIMENTS = {"positive": "Positif", "neutral": "Neutre", "negative": "Négatif"}
SEGMENTS = {"standard": "Standard", "loyalty": "Fidélité", "vip": "VIP"}
ASPECTS = {"breakfast": "Petit-déjeuner", "value": "Rapport qualité-prix", "room": "Chambre",
           "wifi": "Wi-Fi", "parking": "Parking", "location": "Emplacement", "check_in": "Accueil",
           "noise": "Bruit", "pool": "Piscine", "air_conditioning": "Climatisation",
           "staff": "Personnel", "cleanliness": "Propreté"}


def cloud_settings():
    defaults = {}
    env_file = ROOT / ".env.phase4"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and not name.startswith("#"):
                defaults[name] = value.strip().strip('"').strip("'")
    defaults.update(os.environ)
    return {
        "endpoint": defaults.get("CLOUDMIND_MINIO_ENDPOINT", f"http://127.0.0.1:{defaults.get('MINIO_API_PORT', '9000')}"),
        "bucket": defaults.get("CLOUDMIND_BUCKET", "cloudmind"),
        "access": defaults.get("MINIO_ROOT_USER", ""),
        "secret": defaults.get("MINIO_ROOT_PASSWORD", ""),
        "snapshot": defaults.get("CLOUDMIND_PHASE4_RUN", PHASE4),
    }


def cloud_clients(settings):
    from minio import Minio
    from urllib.parse import urlsplit
    from urllib3 import PoolManager, Timeout

    endpoint = urlsplit(settings["endpoint"])
    http = PoolManager(timeout=Timeout(connect=2, read=8), retries=False)
    client = Minio(
        endpoint.netloc, access_key=settings["access"] or None, secret_key=settings["secret"] or None,
        secure=endpoint.scheme == "https", region="us-east-1", http_client=http,
    )
    return http, client


def object_bytes(client, bucket, key):
    response = client.get_object(bucket, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def cloud_status(settings):
    bucket = settings["bucket"]
    status = {"ready": False, "accessible": False, "report": None}
    try:
        http, client = cloud_clients(settings)
        response = http.request("GET", settings["endpoint"].rstrip("/") + "/minio/health/ready",
                                timeout=2)
        status["ready"] = response.status == 200
        if status["ready"]:
            status["accessible"] = client.bucket_exists(bucket)
    except Exception:
        return status
    if status["accessible"]:
        try:
            content = object_bytes(client, bucket, f"reports/{settings['snapshot']}/phase4_execution.json")
            status["report"] = json.loads(content)
        except Exception:
            pass
    return status


def load_analytics(source, settings):
    if source == "MinIO":
        _, client = cloud_clients(settings)
        prefix = settings["snapshot"]

        def read(key, columns=None):
            data = object_bytes(client, settings["bucket"], key)
            return pd.read_parquet(io.BytesIO(data), columns=columns)

        raw = read(f"processed/{prefix}/hotel_reviews.parquet", COLUMNS)
        tables = {name: read(f"analytics/{prefix}/phase2/{PHASE2}/{name}.parquet") for name in TABLES}
    else:
        raw = pd.read_parquet(PROCESSED / "hotel_reviews.parquet", columns=COLUMNS)
        tables = {name: pd.read_parquet(PROCESSED / "phase2" / PHASE2 / f"{name}.parquet") for name in TABLES}
    if len(raw) != 100_000 or tables["hotel_kpis"]["avis"].sum() != len(raw):
        raise ValueError("Le volume des avis diffère du référentiel Phase 2.")
    return prepare_reviews(raw), tables


def prepare_reviews(raw):
    frame = raw.copy()
    frame["review_date"] = pd.to_datetime(frame["review_date"])
    frame["mois"] = frame["review_date"].dt.to_period("M").dt.to_timestamp()
    for column in ("customer_segment", "sentiment", "resolution_status", "primary_aspect"):
        frame[column] = frame[column].str.strip().str.lower()
    frame["reclamations"] = frame["has_complaint"].eq(1)
    frame["non_resolues"] = frame["reclamations"] & frame["resolution_status"].eq("unresolved")
    frame["resolues"] = frame["reclamations"] & frame["resolution_status"].eq("resolved")
    frame["reponse_moyenne_heures"] = frame["response_time_hours"].where(
        frame["reclamations"] & frame["resolution_status"].isin(["resolved", "in_progress"])
    )
    frame["resolution_moyenne_jours"] = frame["resolved_in_days"].where(frame["resolues"])
    return frame


def filter_reviews(frame, hotels=(), dates=(), segments=(), customer=""):
    mask = pd.Series(True, index=frame.index)
    if hotels:
        mask &= frame["hotel_id"].isin(hotels)
    if dates:
        start, end = dates[0], dates[-1]
        mask &= frame["review_date"].between(pd.Timestamp(start), pd.Timestamp(end))
    if segments:
        mask &= frame["customer_segment"].isin(segments)
    if customer.strip():
        mask &= frame["customer_id"].str.casefold().eq(customer.strip().casefold())
    return frame.loc[mask]


def aggregate(frame, dimensions):
    return frame.groupby(dimensions, observed=True, dropna=False).agg(
        avis=("rating", "size"), note_moyenne=("rating", "mean"),
        reclamations=("reclamations", "sum"), non_resolues=("non_resolues", "sum"),
        resolues=("resolues", "sum"), reponse_moyenne_heures=("reponse_moyenne_heures", "mean"),
        resolution_moyenne_jours=("resolution_moyenne_jours", "mean"),
    ).reset_index().assign(pct_reclamations=lambda rows: 100 * rows.reclamations / rows.avis)


def load_classifier():
    from phase3 import SavedTextClassifier

    directory = PROCESSED / "phase3" / PHASE3
    model = SavedTextClassifier.load(directory / "pipeline")
    report = json.loads((directory / "model_comparison.json").read_text(encoding="utf-8"))
    return model, report
