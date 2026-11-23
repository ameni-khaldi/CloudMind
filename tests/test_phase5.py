import base64
import json

import numpy as np
import pytest

pytest.importorskip("pandas", reason="Install requirements-phase5.txt")
pytest.importorskip("streamlit", reason="Install requirements-phase5.txt")
import pandas as pd
from streamlit.testing.v1 import AppTest

from dashboard import data


@pytest.fixture(scope="module")
def local():
    return data.load_analytics("Locale", {})


def test_existing_parquet_and_tables_reconcile(local):
    reviews, tables = local
    assert len(reviews) == 100_000
    assert tables["hotel_kpis"].avis.sum() == len(reviews)
    assert tables["monthly_trends"].avis.sum() == len(reviews)
    assert tables["complaint_analytics"].avis.sum() == reviews.reclamations.sum() == 42_509


def test_shared_filters_and_complaint_denominators(local):
    reviews, _ = local
    start, end = reviews.review_date.min() + pd.Timedelta(days=12), reviews.review_date.max()
    hotel = reviews.hotel_id.iloc[0]
    selected = data.filter_reviews(reviews, [hotel], [start, end], ["standard"])
    expected = reviews.query("hotel_id == @hotel and @start <= review_date <= @end and customer_segment == 'standard'")
    assert selected.index.equals(expected.index)
    assert data.filter_reviews(reviews, ["missing"]).empty
    customer = reviews.customer_id.iloc[0]
    assert data.filter_reviews(reviews, customer=customer.lower()).index.equals(
        reviews[reviews.customer_id.eq(customer)].index
    )
    totals = data.aggregate(selected, ["hotel_id"]).iloc[0]
    assert totals.avis == len(selected)
    assert totals.pct_reclamations == pytest.approx(100 * selected.reclamations.mean())


def test_all_pages_filters_and_saved_model(monkeypatch, local):
    reviews, _ = local
    monkeypatch.setenv("CLOUDMIND_MINIO_ENDPOINT", "http://127.0.0.1:1")
    app = AppTest.from_file(str(data.ROOT / "dashboard" / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert app.metric[0].value == "100 000"
    hotel = reviews.hotel_id.iloc[0]
    app.multiselect[0].set_value([hotel])
    app.multiselect[1].set_value(["standard"])
    dates = (reviews.review_date.min().date(), reviews.review_date.sort_values().iloc[20_000].date())
    app.date_input[0].set_value(dates)
    app.run()
    count = len(data.filter_reviews(reviews, [hotel], dates, ["standard"]))
    assert app.metric[0].value == f"{count:,}".replace(",", " ")
    caption = [item.value for item in app.caption if "dans la sélection" in item.value]

    for title in ("Analyse des hôtels", "Satisfaction client", "Intelligence artificielle", "Spark & cloud", "Performance"):
        app.sidebar.radio[0].set_value(title).run()
        assert not app.exception, title
        if title in ("Analyse des hôtels", "Satisfaction client"):
            assert caption[0] in [item.value for item in app.caption]
        if title == "Intelligence artificielle":
            text = "The room was excellent and the staff were wonderful."
            expected = data.load_classifier()[0].predict(text)
            app.text_area[0].set_value(text)
            app.button[0].click().run()
            assert not app.exception
            assert data.SENTIMENTS[expected["predicted_sentiment"]] in app.success[0].value
            spec = json.loads(app.get("plotly_chart")[0].proto.spec)
            for trace in spec["data"]:
                x = trace["x"]
                if isinstance(x, dict):
                    x = np.frombuffer(base64.b64decode(x["bdata"]), dtype=x["dtype"])
                expected_probability = next(value for key, value in expected["probabilities"].items()
                                            if data.SENTIMENTS[key] == trace["name"])
                assert list(x) == pytest.approx([expected_probability * 100])
        if title == "Spark & cloud":
            assert "ne répond pas" in app.warning[0].value
    app.sidebar.radio[0].set_value("Vue d’ensemble").run()
    assert caption[0] in [item.value for item in app.caption]
    app.sidebar.selectbox[0].set_value("MinIO").run()
    assert not app.exception
    assert "fichiers locaux" in app.warning[0].value
    assert caption[0] in [item.value for item in app.caption]
