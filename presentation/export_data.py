"""Build the presentation's read-only, aggregate evidence snapshot."""
import json
from pathlib import Path

import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROCESSED = ROOT / "data/processed"
PHASE2 = PROCESSED / "phase2/run-fa137ff05cee42c89e5622d5eec78ca2"
PHASE3 = PROCESSED / "phase3/run-d907a7f0f9bd491ca4723205d208fddd"
CLOUD = ROOT / "dashboard/phase4_verified.json"
BENCHMARK = ROOT / "benchmarks/phase5_results.json"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def table(name, columns):
    return pq.read_table(PHASE2 / f"{name}.parquet", columns=columns).to_pylist()


def main():
    phase1 = read(PROCESSED / "data_quality.json")["quality"]
    phase2 = read(PHASE2 / "rapport_execution.json")
    phase3 = read(PHASE3 / "rapport_execution.json")
    comparison = read(PHASE3 / "model_comparison.json")
    common = ["avis", "note_moyenne", "positive", "neutral", "negative", "reclamations",
              "non_resolues", "reponse_moyenne_heures", "resolution_moyenne_jours"]
    cloud = read(CLOUD)
    hotels = sorted(table("hotel_kpis", ["hotel_id", "hotel_name", *common]), key=lambda row: row["hotel_id"])
    data = {
        "quality": {key: phase1[key] for key in ("rows", "hotels", "non_synthetic_rows", "duplicate_review_ids")},
        "analytics": {"runtime": phase2["spark"], "validation": phase2["validation"],
                      "seconds": phase2["secondes_pipeline"]},
        "hotels": hotels,
        "segments": table("customer_segments", ["segment_client", *common]),
        "monthly": sorted(table("monthly_trends", ["mois", "avis", "positive", "neutral", "negative"]),
                          key=lambda row: row["mois"]),
        "ml": {"comparison": comparison, "split": phase3["split_strategy"]["counts"],
               "isolation": phase3["split_strategy"]["isolation"],
               "originalCustomerOverlap": phase3["data_audit"]["customers_crossing_existing_splits"],
               "originalTextOverlap": phase3["data_audit"]["review_text_crossing_existing_splits"]},
        "cloud": {key: cloud[key] for key in ("runtime", "input_uri", "input_rows", "output_uri", "output_rows",
                                               "output_schema", "sentiment_distribution", "verified_phase3_objects")},
        "benchmark": read(BENCHMARK)["summary"],
        "sources": [str(path.relative_to(ROOT).as_posix()) for path in (
            PROCESSED / "data_quality.json", PHASE2 / "rapport_execution.json",
            PHASE3 / "rapport_execution.json", CLOUD, BENCHMARK)],
    }
    assert len(hotels) == phase1["hotels"] == 50
    assert sum(row["avis"] for row in hotels) == phase1["rows"] == cloud["input_rows"]
    assert sum(map(sum, comparison["test_metrics"]["confusion_matrix"]["matrix"])) == comparison["test_metrics"]["row_count"]
    path = HERE / "public" / "mesures-cloudmind.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, default=str, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
