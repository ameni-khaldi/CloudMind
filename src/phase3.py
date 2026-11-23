import argparse
import json
import math
import platform
import re
import sys
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pyspark
from pyspark.ml import Pipeline
from pyspark.ml.classification import LogisticRegression, NaiveBayes
from pyspark.ml.feature import HashingTF, IDF, RegexTokenizer, StopWordsRemover, StringIndexer
from pyspark.ml.evaluation import MulticlassClassificationEvaluator
from pyspark.sql import SparkSession, functions as F

from ingestion import OUTPUT_DIR, start_spark


SOURCE = OUTPUT_DIR / "hotel_reviews.parquet"
DESTINATION = OUTPUT_DIR / "phase3"
TEXT_COLUMN = "review_text"
TARGET_COLUMN = "sentiment"
FEATURE_COLUMNS = (TEXT_COLUMN,)


def start_spark_phase3():
    return start_spark()


def leakage_audit(frame):
    audit_start = perf_counter()
    total = frame.count()
    rating_mismatches = frame.where(
        "(rating <= 2 AND sentiment != 'negative') "
        "OR (rating = 3 AND sentiment != 'neutral') "
        "OR (rating >= 4 AND sentiment != 'positive')"
    ).count()
    rating_groups = [
        row.asDict()
        for row in frame.groupBy("rating", "sentiment").count().orderBy("rating", "sentiment").collect()
    ]
    repeated_customers = frame.groupBy("customer_id").count().where("count > 1").count()
    cross_split_customers = (
        frame.groupBy("customer_id")
        .agg(F.countDistinct("dataset_split").alias("splits"))
        .where("splits > 1")
        .count()
    )
    distinct_text = frame.select(TEXT_COLUMN).distinct().count()
    duplicate_text_groups = (
        frame.groupBy(TEXT_COLUMN).count().where("count > 1").count()
    )
    cross_split_text = (
        frame.groupBy(TEXT_COLUMN)
        .agg(F.countDistinct("dataset_split").alias("splits"))
        .where("splits > 1")
        .count()
    )
    distinct_titles = (
        frame.select("review_title").distinct().count()
        if "review_title" in frame.columns
        else None
    )
    return {
        "rows": total,
        "generator_source_found": False,
        "review_text_column": TEXT_COLUMN,
        "target_column": TARGET_COLUMN,
        "target_derived_columns": ["rating", "sentiment_score", "review_title"],
        "existing_split_counts": [
            row.asDict()
            for row in frame.groupBy("dataset_split").count().orderBy("dataset_split").collect()
        ],
        "rating_sentiment_mismatches": rating_mismatches,
        "rating_sentiment_groups": rating_groups,
        "distinct_review_text": distinct_text,
        "duplicate_review_text_groups": duplicate_text_groups,
        "distinct_review_titles": distinct_titles,
        "repeated_customers": repeated_customers,
        "customers_crossing_existing_splits": cross_split_customers,
        "review_text_crossing_existing_splits": cross_split_text,
        "existing_splits_accepted": False,
        "seconds": perf_counter() - audit_start,
    }


def build_safe_splits(frame, seed=0):
    hashed = frame.withColumn(
        "safe_split",
        F.when(F.pmod(F.xxhash64("customer_id"), F.lit(100)) < 70, "train")
        .when(F.pmod(F.xxhash64("customer_id"), F.lit(100)) < 80, "validation")
        .otherwise("test"),
    )
    conflicting_text = (
        hashed.groupBy(TEXT_COLUMN)
        .agg(F.countDistinct("safe_split").alias("split_count"))
        .where("split_count > 1")
        .select(TEXT_COLUMN)
    )
    return hashed.join(F.broadcast(conflicting_text), on=TEXT_COLUMN, how="left_anti")


def split_isolation(frame):
    customer_crosses = (
        frame.groupBy("customer_id")
        .agg(F.countDistinct("safe_split").alias("splits"))
        .where("splits > 1")
        .count()
    )
    text_crosses = (
        frame.groupBy(TEXT_COLUMN)
        .agg(F.countDistinct("safe_split").alias("splits"))
        .where("splits > 1")
        .count()
    )
    return {
        "customers_crossing_safe_splits": customer_crosses,
        "review_text_crossing_safe_splits": text_crosses,
        "isolated": customer_crosses == 0 and text_crosses == 0,
    }


def build_pipeline(num_features=1 << 16):
    tokenizer = RegexTokenizer(
        inputCol=TEXT_COLUMN, outputCol="tokens", pattern=r"\W+", minTokenLength=2
    )
    remover = StopWordsRemover(
        inputCol="tokens",
        outputCol="filtered_tokens",
        stopWords=StopWordsRemover.loadDefaultStopWords("english"),
    )
    hashing = HashingTF(
        inputCol="filtered_tokens", outputCol="hashed_features", numFeatures=num_features
    )
    idf = IDF(inputCol="hashed_features", outputCol="features")
    indexer = StringIndexer(
        inputCol=TARGET_COLUMN, outputCol="label", handleInvalid="error"
    )
    return {
        "stages": [tokenizer, remover, hashing, idf, indexer],
    }


def model_pipeline(classifier_name):
    preprocessing = build_pipeline()["stages"]
    if classifier_name == "logistic_regression":
        classifier = LogisticRegression(
            featuresCol="features",
            labelCol="label",
            predictionCol="prediction",
            probabilityCol="probability",
            maxIter=50,
            regParam=0.1,
        )
    elif classifier_name == "naive_bayes":
        classifier = NaiveBayes(
            featuresCol="features",
            labelCol="label",
            predictionCol="prediction",
            probabilityCol="probability",
            smoothing=1.0,
            modelType="multinomial",
        )
    else:
        raise ValueError("Classifier inconnu: " + classifier_name)
    return Pipeline(stages=preprocessing + [classifier])


def evaluate(predictions, label_names):
    index_to_name = {index: name for index, name in enumerate(label_names)}
    rows = predictions.select("label", "prediction").collect()
    confusion = {}
    support = {}
    for actual_name in label_names:
        support[actual_name] = 0
        confusion[actual_name] = {predicted_name: 0 for predicted_name in label_names}
    correct = 0
    for row in rows:
        actual = index_to_name.get(int(row["label"]))
        predicted = index_to_name.get(int(row["prediction"]))
        if actual is None or predicted is None:
            raise ValueError("Classe inconnue dans les prédictions.")
        support[actual] += 1
        confusion[actual][predicted] += 1
        correct += actual == predicted

    per_class = {}
    weighted_f1 = 0.0
    for name in label_names:
        tp = confusion[name][name]
        fp = sum(confusion[actual][name] for actual in label_names if actual != name)
        fn = support[name] - tp
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[name] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support[name],
        }
        weighted_f1 += (support[name] / len(rows) if rows else 0.0) * f1
    macro_precision = sum(value["precision"] for value in per_class.values()) / len(per_class)
    macro_recall = sum(value["recall"] for value in per_class.values()) / len(per_class)
    macro_f1 = sum(value["f1"] for value in per_class.values()) / len(per_class)
    majority_name = max(label_names, key=lambda name: support[name])
    majority_baseline = support[majority_name] / len(rows) if rows else 0.0
    return {
        "accuracy": correct / len(rows) if rows else 0.0,
        "macro_precision": macro_precision,
        "macro_recall": macro_recall,
        "macro_f1": macro_f1,
        "weighted_f1": weighted_f1,
        "per_class": per_class,
        "confusion_matrix": {
            "labels": label_names,
            "matrix": [[confusion[actual][predicted] for predicted in label_names] for actual in label_names],
        },
        "majority_class": majority_name,
        "majority_baseline_accuracy": majority_baseline,
        "row_count": len(rows),
    }


def _murmur_hash3_32(text, seed=42):
    data = text.encode("utf-8")
    length = len(data)
    c1 = 0xcc9e2d51
    c2 = 0x1b873593
    h1 = seed
    rounded_end = (length // 4) * 4
    for index in range(0, rounded_end, 4):
        word = int.from_bytes(data[index:index + 4], "little")
        word = (word * c1) & 0xffffffff
        word = ((word << 15) | (word >> 17)) & 0xffffffff
        word = (word * c2) & 0xffffffff
        h1 ^= word
        h1 = ((h1 << 13) | (h1 >> 19)) & 0xffffffff
        h1 = (h1 * 5 + 0xe6546b64) & 0xffffffff
    tail = data[rounded_end:]
    word = 0
    if len(tail) == 3:
        word ^= tail[2] << 16
    if len(tail) >= 2:
        word ^= tail[1] << 8
    if len(tail) >= 1:
        word ^= tail[0]
        word = (word * c1) & 0xffffffff
        word = ((word << 15) | (word >> 17)) & 0xffffffff
        word = (word * c2) & 0xffffffff
        h1 ^= word
    h1 ^= length
    h1 ^= h1 >> 16
    h1 = (h1 * 0x85ebca6b) & 0xffffffff
    h1 ^= h1 >> 13
    h1 = (h1 * 0xc2b2ae35) & 0xffffffff
    h1 ^= h1 >> 16
    return h1


class SavedTextClassifier:
    def __init__(self, state):
        self.state = state
        self.labels = state["labels"]
        self.num_features = state["num_features"]
        self.idf = state["idf"]
        self.classifier = state["classifier"]
        self.stop_words = set(state["stop_words"])

    @classmethod
    def from_pipeline(cls, fitted, classifier_name):
        indexer = fitted.stages[4]
        idf_model = fitted.stages[3]
        classifier = fitted.stages[5]
        labels = list(indexer.labels)
        idf_vector = idf_model.idf.toArray().tolist()
        state = {
            "classifier_name": classifier_name,
            "labels": labels,
            "num_features": len(idf_vector),
            "idf": idf_vector,
            "stop_words": StopWordsRemover.loadDefaultStopWords("english"),
        }
        if classifier_name == "logistic_regression":
            if hasattr(classifier, "coefficientMatrix"):
                matrix = classifier.coefficientMatrix.toArray()
                intercept = (
                    classifier.interceptVector.toArray().tolist()
                    if hasattr(classifier, "interceptVector")
                    else [classifier.intercept] * len(labels)
                )
            else:
                matrix = [classifier.coefficients.toArray().tolist()]
                intercept = [classifier.intercept]
            state["classifier"] = {
                "coefficients": matrix.tolist() if hasattr(matrix, "tolist") else matrix,
                "intercepts": intercept,
            }
        else:
            state["classifier"] = {
                "pi": classifier.pi.toArray().tolist(),
                "theta": classifier.theta.toArray().tolist(),
            }
        return cls(state)

    def predict(self, text):
        tokens = [
            token
            for token in re.split(r"\W+", text.lower(), flags=re.ASCII)
            if len(token) >= 2 and token not in self.stop_words
        ]
        features = {}
        for token in tokens:
            index = _murmur_hash3_32(token) % self.num_features
            features[index] = features.get(index, 0.0) + 1.0
        vector = {
            index: count * (self.idf[index] if index < len(self.idf) else 1.0)
            for index, count in features.items()
        }

        if self.state["classifier_name"] == "logistic_regression":
            coefficients = self.classifier["coefficients"]
            intercepts = self.classifier["intercepts"]
            logits = []
            for class_index in range(len(coefficients)):
                logits.append(
                    intercepts[class_index]
                    + sum(
                        weight * vector.get(index, 0.0)
                        for index, weight in enumerate(coefficients[class_index])
                    )
                )
            if len(logits) == 1:
                logits = [-logits[0], logits[0]]
        else:
            theta = self.classifier["theta"]
            pi = self.classifier["pi"]
            logits = [
                pi[class_index]
                + sum(
                    theta[class_index][index] * count
                    for index, count in vector.items()
                    if index < len(theta[class_index])
                )
                for class_index in range(len(pi))
            ]
        maximum = max(logits)
        exp_logits = [math.exp(value - maximum) for value in logits]
        denominator = sum(exp_logits)
        probabilities = [value / denominator for value in exp_logits]
        if len(probabilities) != len(self.labels):
            probabilities = probabilities[-len(self.labels):]
        predicted_index = max(range(len(probabilities)), key=probabilities.__getitem__)
        return {
            "predicted_sentiment": self.labels[predicted_index],
            "probabilities": {
                name: float(probability)
                for name, probability in zip(self.labels, probabilities)
            },
        }

    def save(self, path):
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        (path / "text_classifier_state.json").write_text(
            json.dumps(self.state, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path):
        path = Path(path)
        state = json.loads(
            (path / "text_classifier_state.json").read_text(encoding="utf-8")
        )
        return cls(state)


def predict_sentiment(spark, pipeline_model, text):
    if isinstance(pipeline_model, SavedTextClassifier):
        return pipeline_model.predict(text)
    input_frame = spark.createDataFrame([(text,)], [TEXT_COLUMN])
    prediction = pipeline_model.transform(input_frame).select(
        "prediction", "probability"
    ).head()
    indexer = next(
        stage for stage in pipeline_model.stages
        if isinstance(stage, StringIndexer) or hasattr(stage, "labels")
    )
    label_names = indexer.labels
    predicted_index = int(prediction["prediction"])
    return {
        "predicted_sentiment": label_names[predicted_index],
        "probabilities": {
            name: float(probability)
            for name, probability in zip(label_names, prediction["probability"].toArray())
        },
    }


def run(spark, source=SOURCE, destination=DESTINATION):
    start = perf_counter()
    source = source.resolve()
    destination = destination.resolve()
    if source in destination.parents or destination == source:
        raise ValueError("Le dossier de sortie doit être distinct de la source.")

    raw = spark.read.parquet(source.as_posix())
    audit = leakage_audit(raw)
    safe = build_safe_splits(raw).cache()
    isolation = split_isolation(safe)
    if not isolation["isolated"]:
        raise ValueError("Le découpage sûr n'est pas isolé.")

    train = safe.where("safe_split = 'train'")
    validation = safe.where("safe_split = 'validation'")
    test = safe.where("safe_split = 'test'")
    distributions = {}
    for name, frame in (("train", train), ("validation", validation), ("test", test)):
        distributions[name] = [
            row.asDict()
            for row in frame.groupBy(TARGET_COLUMN).count().orderBy(TARGET_COLUMN).collect()
        ]

    run_id = uuid4().hex
    staging = destination / f".{run_id}"
    published = destination / f"run-{run_id}"
    staging.mkdir(parents=True)
    comparison = {}
    models = {}
    try:
        for classifier_name in ("logistic_regression", "naive_bayes"):
            fit_start = perf_counter()
            pipeline = model_pipeline(classifier_name)
            fitted = pipeline.fit(train.select(TEXT_COLUMN, TARGET_COLUMN, "safe_split"))
            fit_seconds = perf_counter() - fit_start
            validation_predictions = fitted.transform(
                validation.select(TEXT_COLUMN, TARGET_COLUMN)
            )
            indexer = fitted.stages[4]
            label_names = list(indexer.labels)
            metrics = evaluate(validation_predictions.select("label", "prediction"), label_names)
            metrics["fit_seconds"] = fit_seconds
            comparison[classifier_name] = metrics
            models[classifier_name] = fitted

        selected_name = max(
            comparison,
            key=lambda name: (
                comparison[name]["weighted_f1"],
                comparison[name]["accuracy"],
            ),
        )
        selected = models[selected_name]
        indexer = selected.stages[4]
        label_names = list(indexer.labels)

        test_predictions = selected.transform(test.select(TEXT_COLUMN, TARGET_COLUMN))
        test_metrics = evaluate(test_predictions.select("label", "prediction"), label_names)
        model_dir = staging / "pipeline"
        SavedTextClassifier.from_pipeline(selected, selected_name).save(model_dir)

        comparison_report = {
            "validation_comparison": comparison,
            "selected_model": selected_name,
            "test_metrics": test_metrics,
        }
        (staging / "model_comparison.json").write_text(
            json.dumps(comparison_report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (staging / "evaluation_metrics.json").write_text(
            json.dumps(test_metrics, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (staging / "confusion_matrix.json").write_text(
            json.dumps(test_metrics["confusion_matrix"], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        report = {
            "source": str(source),
            "runtime": {
                "python": platform.python_version(),
                "python_executable": sys.executable,
                "pyspark": pyspark.__version__,
                "spark": spark.version,
                "master": spark.sparkContext.master,
                "java": spark.sparkContext._jvm.java.lang.System.getProperty("java.version"),
                "java_home": __import__("os").environ.get("JAVA_HOME"),
            },
            "spark": {
                "parallelisme": spark.sparkContext.defaultParallelism,
                "partitions_shuffle": spark.conf.get("spark.sql.shuffle.partitions"),
                "execution_adaptative": spark.conf.get("spark.sql.adaptive.enabled"),
            },
            "data_audit": audit,
            "split_strategy": {
                "type": "customer_hash_plus_exact_text_conflict_removal",
                "reason": "Les affectations fournies croisent clients et textes exacts.",
                "seed": 0,
                "customer_hash_modulus": 100,
                "train_percentile": "<70",
                "validation_percentile": "[70,80)",
                "test_percentile": ">=80",
                "counts": {
                    name: frame.count()
                    for name, frame in (
                        ("train", train),
                        ("validation", validation),
                        ("test", test),
                    )
                },
                "class_distribution": distributions,
                "isolation": isolation,
                "text_only_features": list(FEATURE_COLUMNS),
                "excluded_columns": [
                    "rating",
                    "sentiment_score",
                    "review_title",
                    "review_id",
                    "customer_id",
                    "dataset_split",
                    "has_complaint",
                    "primary_aspect",
                    "secondary_aspect",
                ],
            },
            "preprocessing": {
                "tokenizer": "RegexTokenizer",
                "stop_words": "Spark English defaults",
                "features": "HashingTF(65536) + IDF",
                "target": "StringIndexer",
                "fitting_scope": "training data only",
            },
            "model_comparison": comparison_report,
            "saved_pipeline": "pipeline",
            "saved_pipeline_format": "archive_état_Spark_ML_JSON",
            "native_spark_pipeline_save": "non_utilisé",
            "native_spark_save_caveat": "winutils.exe absent sur Windows; l'archive conserve les états des transformations, indexeur, IDF et classificateur MLlib.",
            "seconds_pipeline": perf_counter() - start,
        }
        (staging / "rapport_execution.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        staging.rename(published)
        return published, report
    finally:
        safe.unpersist()


def main():
    parser = argparse.ArgumentParser(description="CloudMind, apprentissage Spark MLlib de la phase 3")
    parser.add_argument("--input", type=Path, default=SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DESTINATION)
    args = parser.parse_args()
    spark = start_spark_phase3()
    try:
        output, report = run(spark, args.input, args.output_dir)
        print(f"Résultats : {output}")
        print(
            f"Modèle retenu : {report['model_comparison']['selected_model']} "
            f"(validation, weighted F1)"
        )
        print(json.dumps(report["model_comparison"]["test_metrics"], ensure_ascii=False))
        print(f"Durée : {report['seconds_pipeline']:.3f} s")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
