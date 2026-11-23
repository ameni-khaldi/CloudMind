import pytest

from analytics import metrics, transform
from phase2 import SOURCE, run


def test_duration_and_percentage_denominators(spark):
    source = spark.sql("""
        SELECT * FROM VALUES
          (DATE '2025-01-02', ' VIP ', ' Positive ', 'resolved', 1, 'room', 4D, 2, 5),
          (DATE '2025-01-03', 'VIP', 'negative', 'in_progress', 1, 'staff', 8D, NULL, 1),
          (DATE '2025-01-04', 'VIP', 'negative', 'unresolved', 1, 'staff', NULL, NULL, 2),
          (DATE '2025-01-05', 'VIP', 'neutral', 'not_applicable', 0, 'room', NULL, NULL, 3),
          (DATE '2025-01-06', 'Standard', 'positive', 'not_applicable', 0, 'room', NULL, NULL, 5)
        AS t(review_date, customer_segment, sentiment, resolution_status, has_complaint,
             primary_aspect, response_time_hours, resolved_in_days, rating)
    """)
    rows = {row.segment_client: row for row in metrics(transform(source), ("segment_client",)).collect()}
    vip, standard = rows["vip"], rows["standard"]
    assert (vip.avis, vip.positive, vip.neutral, vip.negative) == (4, 1, 1, 2)
    assert vip.pct_reclamations == 75
    assert vip.pct_non_resolues == pytest.approx(100 / 3)
    assert vip.reponse_moyenne_heures == 6
    assert vip.resolution_moyenne_jours == 2
    assert vip.reponses_mesurees == 2
    assert vip.resolutions_mesurees == 1
    assert standard.pct_non_resolues is None
    assert standard.reponse_moyenne_heures is None


def test_phase2_outputs_reconcile_and_are_readable(spark, tmp_path):
    path, report = run(spark, SOURCE, tmp_path)
    assert report["validation"] == {
        "avis": 100_000, "identifiants": 100_000, "reclamations": 42_509, "invalides": 0,
    }
    expected = {
        "hotel_kpis": 50, "monthly_trends": 46, "customer_segments": 3, "sentiment_distribution": 9,
    }
    assert set(report["tables"]) == {*expected, "complaint_analytics"}
    for name, table in report["tables"].items():
        dataset = spark.read.parquet((path / table["chemin"]).resolve().as_posix())
        assert dataset.count() == table["lignes_relues"] == table["lignes"]
        assert table["comparaison_sql"] == "identique"
        assert table["groupes_invalides"] == 0
        assert table["reclamations"] == 42_509
        if name in expected:
            assert table["avis"] == 100_000
            assert table["lignes"] == expected[name]
        else:
            assert table["avis"] == 42_509
    assert (path / "rapport_execution.json").is_file()
