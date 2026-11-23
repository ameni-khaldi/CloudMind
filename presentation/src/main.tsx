import { Component, Suspense, lazy, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import gsap from "gsap";
import { story, type Item } from "./story";
import { fmt, type Evidence, type Hotel } from "./types";
import "./style.css";

const World = lazy(() => import("./World"));
const Charts = lazy(() => import("./Charts"));
const featured = [6, 7, 10];
const dashboard = import.meta.env.VITE_DASHBOARD_URL || "http://127.0.0.1:8505";
const measures = import.meta.env.BASE_URL + "mesures-cloudmind.json";
const pad = (value: number) => String(value).padStart(2, "0");

class CanvasBoundary extends Component<{ children: ReactNode; fallback: () => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() { this.props.fallback(); }
  render() { return this.state.failed ? null : this.props.children; }
}

function cardFromHotel(hotel: Hotel): Item {
  return { title: hotel.hotel_name, detail:
    `${fmt(hotel.avis)} avis · ${fmt(hotel.note_moyenne, 2)}/5 · ${fmt(100 * hotel.reclamations / hotel.avis, 1)} % de réclamations · ${fmt(hotel.non_resolues)} non résolues.` };
}

function sceneMetrics(index: number, data: Evidence) {
  const { test_metrics: model } = data.ml.comparison;
  const values: Record<number, [string, string][]> = {
    0: [[fmt(data.quality.rows), "Avis analysés"], [fmt(data.quality.hotels), "Hôtels"], ["3", "Classes de sentiment"]],
    1: [[fmt(data.quality.hotels), "Établissements"], [fmt(data.analytics.validation.reclamations), "Réclamations"]],
    2: [[String(data.analytics.runtime.partitions_source), "Partitions d’entrée"], ["local[2]", "Mode Spark"]],
    3: [[fmt(data.analytics.validation.avis), "Avis validés"], ["5", "Tables analytiques"]],
    4: [[fmt(data.cloud.input_rows), "Avis lus via S3A"], [fmt(data.cloud.output_rows), "Lignes relues"]],
    5: [[fmt(data.ml.split.train), "Entraînement"], [fmt(data.ml.split.validation), "Validation"], [fmt(data.ml.split.test), "Test"]],
    6: [[fmt(100 * model.accuracy, 2) + " %", "Exactitude"],
        [fmt(model.macro_f1, 4), "F1 macro"], [fmt(model.weighted_f1, 4), "F1 pondérée"]],
    7: [[fmt(100 * data.analytics.validation.reclamations / data.quality.rows, 1) + " %", "Taux de réclamation"]],
  };
  return values[index] ?? [];
}

function FlatScene({ scene, items, active, onPick }: { scene: number; items: Item[]; active: number | null; onPick: (i: number) => void }) {
  return <div className={"flat-scene" + (items.length === 50 ? " flat-city" : "")} aria-label="Schéma interactif en 2D">
    {items.map((item, i) => <button key={item.title} title={item.title}
      aria-label={item.title} aria-pressed={active === i} onClick={() => onPick(i)}>
      <span className="flat-symbol">{items.length === 50 ? pad(i + 1) : "◆"}</span>
      {items.length !== 50 && item.title}
    </button>)}
    {scene === 0 && <p>Trois étapes, du fichier source au sentiment.</p>}
  </div>;
}

function Presentation({ data }: { data: Evidence }) {
  const [scene, setScene] = useState(() => {
    const match = /^#scene-(\d{1,2})$/.exec(location.hash);
    return match ? Math.min(story.length - 1, Math.max(0, Number(match[1]) - 1)) : 0;
  });
  const [reduced, setReduced] = useState(() => matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [flat, setFlat] = useState(() => {
    if (new URLSearchParams(location.search).get("mode") === "2d") return true;
    try { return !document.createElement("canvas").getContext("webgl2"); } catch { return true; }
  });
  const [autoFallback, setAutoFallback] = useState(false);
  const [explore, setExplore] = useState(false);
  const [notes, setNotes] = useState(false);
  const [replay, setReplay] = useState(0);
  const [picked, setPicked] = useState<number | null>(null);
  const [hotel, setHotel] = useState(0);
  const [showChart, setShowChart] = useState(featured.includes(scene));
  const [full, setFull] = useState(false);
  const [browserMessage, setBrowserMessage] = useState("");
  const index = useRef<HTMLDialogElement>(null);
  const content = useRef<HTMLElement>(null);
  const chapter = story[scene];
  const city = scene === 1 || scene === 7;
  const items = city ? data.hotels.map(cardFromHotel) : chapter.items;
  const current = picked === null ? null : items[picked];
  const update = useCallback((next: number) => {
    if (next < 0 || next >= story.length || next === scene) return;
    setScene(next);
    setPicked(null);
    setExplore(false);
    setShowChart(featured.includes(next));
    history.replaceState(null, "", `#scene-${pad(next + 1)}`);
  }, [scene]);
  const select = (i: number) => { setPicked(i); if (city) setHotel(i); };
  const fail = useCallback(() => { setFlat(true); setAutoFallback(true); setExplore(false); }, []);

  useEffect(() => {
    const node = content.current;
    if (!node || reduced) return;
    const animation = gsap.fromTo(node.querySelectorAll("[data-reveal]"),
      { y: 19, opacity: 0 }, { y: 0, opacity: 1, duration: .7, stagger: .075, ease: "power3.out" });
    return () => { animation.revert(); };
  }, [scene, replay, reduced]);
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      const target = event.target;
      if (event.altKey || event.metaKey || event.ctrlKey || index.current?.open ||
          target instanceof HTMLElement && target.closest("input,textarea,select,[contenteditable='true']")) return;
      if (event.code === "Space" && target instanceof HTMLElement && target.closest("button,a")) return;
      if (["ArrowRight", "ArrowDown", "Space"].includes(event.code)) { event.preventDefault(); update(scene + 1); }
      if (["ArrowLeft", "ArrowUp", "Backspace"].includes(event.code)) { event.preventDefault(); update(scene - 1); }
      if (event.key.toLowerCase() === "n") setNotes((shown) => !shown);
      if (event.key.toLowerCase() === "r") setReplay((value) => value + 1);
    };
    const onFull = () => setFull(Boolean(document.fullscreenElement));
    window.addEventListener("keydown", keydown);
    document.addEventListener("fullscreenchange", onFull);
    return () => { window.removeEventListener("keydown", keydown); document.removeEventListener("fullscreenchange", onFull); };
  }, [scene, update]);
  const fullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
      setBrowserMessage("");
    } catch { setBrowserMessage("Le plein écran est indisponible dans ce navigateur."); }
  };

  return <main className={reduced ? "shell reduced" : "shell"}>
    <header className="top">
      <a className="brand" href="#scene-01" onClick={(e) => { e.preventDefault(); update(0); }} aria-label="CloudMind, retour à l’introduction">
        <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span><span>Cloud<span>Mind.</span></span>
      </a>
      <p className="top-label">LE VOYAGE AU CŒUR DES DONNÉES</p>
      <nav aria-label="Outils de présentation">
        <button className="top-action" onClick={() => index.current?.showModal()}><span aria-hidden="true">▦</span> Scènes</button>
        <button className="top-action" aria-pressed={notes} onClick={() => setNotes(!notes)}><span aria-hidden="true">▤</span> Notes <kbd>N</kbd></button>
        <button className="top-action" aria-pressed={full} onClick={() => void fullscreen()} aria-label={full ? "Quitter le plein écran" : "Plein écran"}><span aria-hidden="true">⛶</span></button>
      </nav>
    </header>
    <section className="spread" aria-label={chapter.label}>
      <article className="editorial" ref={content}>
        <div className="chapter-index" data-reveal><span className="status-dot" /> CHAPITRE {pad(scene + 1)} <span className="slash">/</span> {chapter.label}</div>
        <p className="kicker" data-reveal>{chapter.kicker}</p>
        <h1 data-reveal>{chapter.title}<br /><em>{chapter.accent}</em></h1>
        <p className="lead" data-reveal>{chapter.text}</p>
        {sceneMetrics(scene, data).length > 0 && <div className="metrics" data-reveal>
          {sceneMetrics(scene, data).map(([value, label]) => <div key={label}><strong>{value}</strong><span>{label}</span></div>)}
        </div>}
        {scene === 0 && <button className="primary begin" data-reveal onClick={() => update(1)}>Commencer le voyage <span aria-hidden="true">→</span></button>}
        {(city || scene > 1 && ![6, 10, 11].includes(scene)) && <div className="picker" data-reveal>
          <label htmlFor="item-picker">{city ? "Choisir un hôtel" : "Examiner un élément"}</label>
          <select id="item-picker" value={picked ?? ""} onChange={(event) => {
            if (event.target.value === "") setPicked(null); else select(Number(event.target.value));
          }}><option value="">Sélectionner…</option>{items.map((item, i) => <option key={i} value={i}>{item.title}</option>)}</select>
        </div>}
        {scene === 5 && <p className="fine" data-reveal>Exactitude en validation · régression logistique {fmt(100 * data.ml.comparison.validation_comparison.logistic_regression.accuracy, 2)} % · naïf bayésien {fmt(100 * data.ml.comparison.validation_comparison.naive_bayes.accuracy, 2)} %.</p>}
        {scene === 6 && <p className="fine" data-reveal>Rappel de la classe neutre · {fmt(100 * data.ml.comparison.test_metrics.per_class.neutral.recall, 2)} %.</p>}
        {scene === 9 && <div data-reveal className="demo-link"><a className="primary" href={dashboard} target="_blank" rel="noreferrer">Ouvrir le tableau de bord</a><p className="fine">Puis ouvrir « Intelligence artificielle » et choisir « Analyser l’avis ». Streamlit doit être lancé sur le poste.</p></div>}
        {scene === 11 && <div data-reveal className="sources">
          <a href={measures} download>Télécharger les mesures vérifiées</a>
          <details><summary>Rapports et documentation</summary>
            <ul>{data.sources.map((path) => <li key={path}><code>{path}</code></li>)}</ul>
            <p><a href="https://spark.apache.org/docs/4.0.4/" target="_blank" rel="noreferrer">Apache Spark</a> · <a href="https://hadoop.apache.org/docs/r3.4.1/hadoop-aws/tools/hadoop-aws/" target="_blank" rel="noreferrer">Hadoop S3A</a> · <a href="https://github.com/minio/minio/releases/tag/RELEASE.2025-09-07T16-13-09Z" target="_blank" rel="noreferrer">MinIO</a> · <a href="https://docs.streamlit.io/" target="_blank" rel="noreferrer">Streamlit</a></p>
          </details>
        </div>}
      </article>
      <section className={"visual" + (showChart ? " has-chart" : "")} aria-label={chapter.visual}>
        <div className="visual-grid" aria-hidden="true" />
        <div className="stage-header">
          <span className="stage-chip"><span className="status-dot" /> {pad(scene + 1)} / {chapter.visual}</span>
          <div className="mode">
            {featured.includes(scene) && <button aria-pressed={showChart} onClick={() => setShowChart(!showChart)}>{showChart ? "Voir la scène" : "Voir le graphique"}</button>}
            {!flat && !showChart && <button aria-pressed={explore} onClick={() => setExplore(!explore)}>{explore ? "Quitter l’exploration" : "Explorer en 3D"}</button>}
          </div>
        </div>
        {!flat && <div className={"canvas" + (showChart ? " behind-chart" : "")}>
          <CanvasBoundary fallback={fail}><Suspense fallback={<p className="loading">Chargement de la scène…</p>}>
            <World scene={scene} evidence={data} selected={current?.title ?? ""} onPick={select} reduced={reduced}
              explore={explore && !showChart} replay={replay} paused={showChart} onFailure={fail} />
          </Suspense></CanvasBoundary>
        </div>}
        {flat && !showChart && <FlatScene scene={scene} items={items} active={picked} onPick={select} />}
        {showChart && <div className="chart-panel">
          <Suspense fallback={<p className="loading">Chargement du graphique…</p>}>
            <Charts key={scene} scene={scene} data={data} hotel={hotel} />
          </Suspense>
        </div>}
        {notes && <aside className="notes" aria-label="Notes de présentation">
          <strong>Notes de présentation</strong><button onClick={() => setNotes(false)} aria-label="Fermer les notes">×</button><p>{chapter.notes}</p>
        </aside>}
        {current && <aside className="info" aria-live="polite">
          <strong>{current.title}</strong><button onClick={() => setPicked(null)} aria-label="Fermer le détail">×</button><p>{current.detail}</p>
        </aside>}
        <div className="visual-foot">
          <span><b>{showChart ? "DONNÉES VÉRIFIÉES" : flat ? "VUE 2D" : "MONDE 3D"}</b> · {showChart ? "Survolez le graphique" : scene === 1 ? "Implantation illustrative" : "Animation illustrative"}</span>
          <span>{autoFallback ? "WebGL indisponible" : explore ? "Glisser pour pivoter · molette pour zoomer" : "CloudMind"}</span>
        </div>
      </section>
    </section>
    <footer className="bottom">
      <div className="progress">
        <div className="progress-meta"><strong>{pad(scene + 1)} <span>/</span> {pad(story.length)}</strong><span>{chapter.label}</span></div>
        <div className="timeline" aria-label="Progression et navigation directe">
          {story.map((step, i) => <button key={step.label} className={i < scene ? "visited" : ""}
            aria-current={i === scene ? "step" : undefined} aria-label={`Chapitre ${i + 1} : ${step.label}`}
            title={step.label} onClick={() => update(i)} />)}
        </div>
      </div>
      <div className="access">
        <button title="Rejouer (R)" aria-label="Rejouer l’animation" onClick={() => setReplay(replay + 1)}>↻ <kbd>R</kbd></button>
        <button aria-pressed={reduced} onClick={() => setReduced(!reduced)}>Mouvement réduit</button>
        <button aria-pressed={flat} onClick={() => { setFlat(!flat); setAutoFallback(false); setExplore(false); }}>2D</button>
      </div>
      <div className="next">
        <button aria-label="Chapitre précédent" disabled={!scene} onClick={() => update(scene - 1)}>←</button>
        <button className="primary" disabled={scene === story.length - 1} onClick={() => update(scene + 1)}>Suivant <span aria-hidden="true">→</span></button>
      </div>
    </footer>
    {browserMessage && <p role="status" className="browser-message">{browserMessage}</p>}
    <dialog ref={index} className="scene-index" onClick={(event) => { if (event.target === event.currentTarget) index.current?.close(); }}>
      <div><header><h2>Trajet de la présentation</h2><button onClick={() => index.current?.close()} aria-label="Fermer les scènes">×</button></header>
        <ol>{story.map((entry, i) => <li key={entry.label}><button aria-current={i === scene ? "step" : undefined}
          onClick={() => { update(i); index.current?.close(); }}><span>{pad(i + 1)}</span>{entry.label}</button></li>)}</ol>
        <p className="fine">Flèches ou Espace pour avancer · Retour arrière pour revenir · N pour les notes · R pour rejouer.</p>
      </div>
    </dialog>
  </main>;
}

async function start() {
  const root = createRoot(document.getElementById("root")!);
  root.render(<p className="loading">Chargement des données CloudMind…</p>);
  try {
    const response = await fetch(measures);
    if (!response.ok) throw new Error();
    const data = await response.json() as Evidence;
    root.render(<Presentation data={data} />);
  } catch {
    root.render(<main className="boot-error"><h1>Les mesures CloudMind sont indisponibles.</h1><p>Lancez la présentation avec la commande du guide local.</p></main>);
  }
}
void start();
