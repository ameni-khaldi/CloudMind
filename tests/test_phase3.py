import pytest

from phase3 import (
    build_safe_splits,
    build_pipeline,
    leakage_audit,
    model_pipeline,
    predict_sentiment,
    run,
    split_isolation,
    SOURCE,
    SavedTextClassifier,
)


def test_preprocessing_is_ml_pipeline(spark):
    stages = build_pipeline(num_features=16)["stages"]
    assert [stage.getInputCol() for stage in stages[:4]] == [
        "review_text",
        "tokens",
        "filtered_tokens",
        "hashed_features",
    ]


def test_safe_split_isolated_and_existing_split_rejected(spark):
    frame = spark.createDataFrame(
        [
            ("c1", "shared text", "train", "positive", 5),
            ("c2", "shared text", "test", "positive", 5),
            ("c3", "unique text", "train", "negative", 1),
            ("c4", "other text", "validation", "neutral", 3),
        ],
        ["customer_id", "review_text", "dataset_split", "sentiment", "rating"],
    )
    audit = leakage_audit(frame)
    safe = build_safe_splits(frame)
    assert audit["existing_splits_accepted"] is False
    assert audit["rating_sentiment_mismatches"] == 0
    assert split_isolation(safe)["isolated"]


def test_training_prediction_save_load(spark, tmp_path):
    frame = spark.createDataFrame(
        [
            ("excellent hotel great staff", "positive"),
            ("wonderful service and clean room", "positive"),
            ("bad hotel poor service", "negative"),
            ("terrible room very dirty", "negative"),
            ("average hotel acceptable room", "neutral"),
            ("ordinary service and breakfast", "neutral"),
        ] * 5,
        ["review_text", "sentiment"],
    )
    pipeline = model_pipeline("logistic_regression")
    fitted = pipeline.fit(frame)
    predictions = fitted.transform(frame)
    assert predictions.where("prediction IS NULL").count() == 0
    saved = tmp_path / "pipeline"
    SavedTextClassifier.from_pipeline(fitted, "logistic_regression").save(saved)
    loaded = SavedTextClassifier.load(saved)
    text = "\u00e9excellent clean hotel"
    expected = predict_sentiment(spark, fitted, text)
    result = predict_sentiment(spark, loaded, text)
    assert result["predicted_sentiment"] == expected["predicted_sentiment"]
    assert result["probabilities"] == pytest.approx(expected["probabilities"])
    assert set(result["probabilities"]) == {"negative", "neutral", "positive"}
    assert abs(sum(result["probabilities"].values()) - 1.0) < 1e-6


def test_phase3_full_pipeline(spark, tmp_path):
    path, report = run(
        spark,
        SOURCE,
        tmp_path,
    )
    assert report["data_audit"]["rows"] == 100_000
    assert report["split_strategy"]["isolation"]["isolated"]
    assert set(report["model_comparison"]["validation_comparison"]) == {
        "logistic_regression",
        "naive_bayes",
    }
    assert report["model_comparison"]["selected_model"] in {
        "logistic_regression",
        "naive_bayes",
    }
    assert report["model_comparison"]["test_metrics"]["row_count"] > 0
    assert (path / "rapport_execution.json").is_file()
    assert (path / "model_comparison.json").is_file()
    assert (path / "evaluation_metrics.json").is_file()
    assert (path / "confusion_matrix.json").is_file()
    assert (path / "pipeline").is_dir()
