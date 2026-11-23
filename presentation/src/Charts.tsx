import { useEffect, useRef, useState } from "react";
import { fmt, sentiments, type Evidence } from "./types";

const blue = "#7CB5D5", coral = "#E9957D", navy = "#263746";
const segmentNames: Record<string, string> = { standard: "Standard", loyalty: "Fidélité", vip: "VIP" };

export default function Charts({ scene, data, hotel }: { scene: number; data: Evidence; hotel: number }) {
  const plot = useRef<HTMLDivElement>(null);
  const [series, setSeries] = useState("hôtels");
  const [stage, setStage] = useState("process");
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(true);
  const metrics = data.ml.comparison.test_metrics;
  const labels = metrics.confusion_matrix.labels.map((label) => sentiments[label]);
  useEffect(() => {
    const node = plot.current;
    if (!node) return;
    let alive = true;
    let resize: ResizeObserver | undefined;
    let api: typeof import("plotly.js-cartesian-dist-min")["default"] | undefined;
    const common = {
      margin: { l: 74, r: 30, t: 40, b: 55 }, font: { family: "Segoe UI, sans-serif", size: 15, color: navy },
      paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "#fffaf2",
      legend: { orientation: "h", y: 1.12 }, separators: ", ",
    };
    let traces: object[];
    let layout: object = common;
    if (scene === 6) {
      traces = [{
        type: "heatmap", z: metrics.confusion_matrix.matrix, x: labels, y: labels,
        text: metrics.confusion_matrix.matrix.map((row) => row.map((cell) => fmt(cell))),
        texttemplate: "%{text}", textfont: { size: 17, color: "#172b3b" }, showscale: false, xgap: 5, ygap: 5,
        colorscale: [[0, "#fff5e8"], [.45, "#c6deec"], [1, "#81b6d4"]],
        hovertemplate: "Réel : %{y}<br>Prédit : %{x}<br>%{z} avis<extra></extra>",
      }];
      layout = { ...common, xaxis: { title: { text: "Classe prédite" }, fixedrange: true },
        yaxis: { title: { text: "Classe réelle" }, autorange: "reversed", fixedrange: true } };
    } else if (scene === 10) {
      traces = ["Spark", "Pandas"].map((engine, i) => {
        const rows = data.benchmark.filter((row) => row.engine === engine && row.stage === stage);
        return { type: "bar", name: engine, x: rows.map((row) => fmt(row.rows)), y: rows.map((row) => row.median_s * 1000),
          error_y: { type: "data", array: rows.map((row) => row.stdev_s * 1000), visible: true },
          marker: { color: i ? coral : blue }, hovertemplate: "%{x} avis<br>%{y:.2f} ms<extra>%{fullData.name}</extra>" };
      });
      layout = { ...common, barmode: "group", xaxis: { title: { text: "Nombre d’avis" }, type: "category" },
        yaxis: { title: { text: "Temps médian (ms)" }, rangemode: "tozero" } };
    } else {
      const categories = [blue, "#c5c9ca", coral];
      const keys = ["positive", "neutral", "negative"] as const;
      if (series === "hôtels" || series === "réclamations") {
        const selected = data.hotels[hotel];
        const complaints = series === "réclamations";
        const value = (h: typeof selected) => complaints ? 100 * h.reclamations / h.avis : h.note_moyenne;
        const base = [...data.hotels].sort((a, b) => value(b) - value(a)).slice(0, 6);
        const displayed = base.includes(selected) ? base : [...base, selected];
        traces = [{ type: "bar", x: displayed.map((h) => h.hotel_id), y: displayed.map(value),
          customdata: displayed.map((h) => [h.hotel_name, h.avis, 100 * h.reclamations / h.avis, h.non_resolues, h.note_moyenne]),
          marker: { color: displayed.map((h) => h === selected ? coral : blue) },
          hovertemplate: "%{customdata[0]}<br>Note : %{customdata[4]:.2f}/5<br>Avis : %{customdata[1]}<br>Réclamations : %{customdata[2]:.1f} %<br>Non résolues : %{customdata[3]}<extra></extra>" }];
        layout = { ...common, yaxis: { title: { text: complaints ? "Taux de réclamation (%)" : "Note moyenne / 5" },
          range: complaints ? [0,100] : [0,5] } };
      } else if (series === "sentiments") {
        traces = keys.map((key, i) => ({ type: "scatter", mode: "lines+markers", name: sentiments[key],
          x: data.monthly.map((row) => row.mois), y: data.monthly.map((row) => row[key]),
          line: { color: ["#397b9f", "#536471", "#a64f3b"][i], dash: ["solid", "dot", "dash"][i], width: 2.5 },
          hovertemplate: "%{x|%m/%Y}<br>%{y} avis<extra>%{fullData.name}</extra>" }));
        layout = { ...common, xaxis: { tickformat: "%m/%Y" }, yaxis: { title: { text: "Avis par mois" } } };
      } else {
        traces = keys.map((key, i) => ({ type: "bar", name: sentiments[key],
          x: data.segments.map((row) => segmentNames[row.segment_client]), y: data.segments.map((row) => row[key]),
          marker: { color: categories[i] }, hovertemplate: "%{x}<br>%{y} avis<extra>%{fullData.name}</extra>" }));
        layout = { ...common, barmode: "stack", yaxis: { title: { text: "Nombre d’avis" } } };
      }
    }
    void import("plotly.js-cartesian-dist-min").then(async ({ default: plotly }) => {
      if (!alive) return;
      api = plotly;
      const draw = () => plotly.react(node, traces, { ...layout, width: node.clientWidth, height: node.clientHeight },
        { displayModeBar: false, staticPlot: false, responsive: false, scrollZoom: false });
      await draw();
      if (!alive) return;
      setLoading(false);
      resize = new ResizeObserver(() => { if (node.clientWidth && node.clientHeight) void draw().catch(() => setFailed(true)); });
      resize.observe(node);
    }).catch(() => { if (alive) { setFailed(true); setLoading(false); } });
    return () => { alive = false; resize?.disconnect(); api?.purge(node); };
  }, [data, hotel, labels.join("|"), metrics, scene, series, stage]);
  const matrix = scene === 6 && <table className="matrix">
    <caption>Matrice de confusion · lignes réelles, colonnes prédites</caption>
    <thead><tr><th scope="col">Classe réelle</th>{labels.map((label) => <th scope="col" key={label}>{label}</th>)}</tr></thead>
    <tbody>{metrics.confusion_matrix.matrix.map((row, i) => <tr key={labels[i]}>
      <th scope="row">{labels[i]}</th>{row.map((cell, j) => <td key={j}>{fmt(cell)}</td>)}</tr>)}</tbody>
  </table>;
  return <div className="chart-wrap">
    {scene === 7 && <div className="chart-tabs">{["hôtels", "réclamations", "sentiments", "segments"].map((key) =>
      <button key={key} aria-pressed={series === key} onClick={() => setSeries(key)}>{key}</button>)}</div>}
    {scene === 10 && <div className="chart-tabs">{[["read","Lecture"],["process","Traitement"],["export","Export"]].map(([key,text]) =>
      <button key={key} aria-pressed={stage === key} onClick={() => setStage(key)}>{text}</button>)}</div>}
    {loading && <p className="chart-status" role="status">Chargement du graphique…</p>}
    <div className={failed ? "plot hidden" : "plot"} ref={plot} aria-label={scene === 6 ? "Graphique de la matrice de confusion" : "Graphique interactif"} />
    {failed && (scene === 6 ? matrix : <a href={import.meta.env.BASE_URL + "mesures-cloudmind.json"} download>Télécharger les mesures du graphique</a>)}
    {!failed && scene === 6 && <div className="sr-only">{matrix}</div>}
  </div>;
}
