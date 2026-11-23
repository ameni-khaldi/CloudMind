import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const data = JSON.parse(readFileSync(new URL("./public/mesures-cloudmind.json", import.meta.url)));

test("les indicateurs des 50 hôtels couvrent les 100 000 avis", () => {
  assert.equal(data.hotels.length, 50);
  assert.equal(new Set(data.hotels.map((hotel) => hotel.hotel_id)).size, 50);
  assert.equal(data.hotels.reduce((total, hotel) => total + hotel.avis, 0), 100000);
  assert.equal(data.hotels.reduce((total, hotel) => total + hotel.reclamations, 0), data.analytics.validation.reclamations);
  assert.equal(data.monthly.reduce((total, month) => total + month.avis, 0), 100000);
});

test("la matrice correspond à la taille du test et au rappel neutre", () => {
  const metrics = data.ml.comparison.test_metrics;
  const { matrix, labels } = metrics.confusion_matrix;
  assert.deepEqual(labels, ["positive", "neutral", "negative"]);
  assert.deepEqual(matrix, [[4286,332,51],[1069,1268,843],[103,997,1889]]);
  assert.equal(matrix.flat().reduce((sum, cell) => sum + cell), metrics.row_count);
  assert.ok(Math.abs(metrics.per_class.neutral.recall - 1268 / 3180) < 1e-10);
  assert.equal((metrics.accuracy * 100).toFixed(2), "68.68");
  assert.equal(metrics.macro_f1.toFixed(4), "0.6467");
  assert.equal(metrics.weighted_f1.toFixed(4), "0.6740");
});

test("les résultats S3A et le benchmark sont complets", () => {
  assert.equal(data.cloud.input_rows, 100000);
  assert.equal(data.cloud.output_rows, 3);
  assert.equal(data.cloud.sentiment_distribution.reduce((sum, row) => sum + row.review_count, 0), 100000);
  assert.equal(data.benchmark.length, 18);
  assert.ok(data.benchmark.every((row) => Number.isFinite(row.median_s) && Number.isFinite(row.stdev_s)));
});
