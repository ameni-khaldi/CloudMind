export type Hotel = {
  hotel_id: string; hotel_name: string; avis: number; note_moyenne: number;
  positive: number; neutral: number; negative: number; reclamations: number; non_resolues: number;
  reponse_moyenne_heures: number | null; resolution_moyenne_jours: number | null;
};
export type Evidence = {
  quality: { rows: number; hotels: number };
  analytics: { runtime: { partitions_source: number }; validation: { avis: number; reclamations: number }; seconds: number };
  hotels: Hotel[];
  segments: Array<Hotel & { segment_client: string }>;
  monthly: Array<{ mois: string; avis: number; positive: number; neutral: number; negative: number }>;
  ml: { split: {train: number; validation: number; test: number}; originalCustomerOverlap: number; originalTextOverlap: number;
        comparison: { test_metrics: { accuracy: number; macro_f1: number; weighted_f1: number; row_count: number;
          per_class: Record<string, {recall: number}>; confusion_matrix: {labels: string[]; matrix: number[][]} };
          validation_comparison: Record<string, {accuracy: number; macro_f1: number}> } };
  cloud: { input_rows: number; output_rows: number; output_uri: string; verified_phase3_objects: number };
  benchmark: Array<{ rows: number; engine: string; stage: string; median_s: number; stdev_s: number }>;
  sources: string[];
};
export const fmt = (value: number, digits = 0) =>
  new Intl.NumberFormat("fr-FR", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
export const sentiments: Record<string, string> = { positive: "Positif", neutral: "Neutre", negative: "Négatif" };
