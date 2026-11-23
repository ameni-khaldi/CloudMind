from pathlib import Path
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard import data


PAGES = ("Vue d’ensemble", "Analyse des hôtels", "Satisfaction client", "Intelligence artificielle", "Spark & cloud", "Performance")
COLORS = {"Positif": "#7CB5D5", "Neutre": "#A8A094", "Négatif": "#E9957D"}
BLUE, CORAL, NAVY = "#7CB5D5", "#E9957D", "#263746"
SETTINGS = data.cloud_settings()
analytics = st.cache_data(ttl=300, max_entries=4, show_spinner=False)(data.load_analytics)
status_check = st.cache_data(ttl=20, show_spinner=False)(data.cloud_status)
classifier = st.cache_resource(show_spinner=False)(data.load_classifier)


def number(value, decimals=0):
    if pd.isna(value):
        return "—"
    return f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")


def chart(figure):
    figure.update_layout(
        font=dict(family="Inter, Segoe UI, sans-serif", color=NAVY, size=14),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=16, b=68, l=56, r=24), height=345,
        legend=dict(orientation="h", y=-0.3, title=None),
    )
    figure.update_yaxes(gridcolor="#E6DED2", zerolinecolor="#D9CEC0", automargin=True)
    figure.update_xaxes(gridcolor="#E6DED2", automargin=True)
    st.plotly_chart(figure, width="stretch", theme=None, config={"displayModeBar": False})


def card(title, value):
    with st.container(border=True):
        st.metric(title, value)


def filter_controls(reviews):
    dates = reviews.review_date
    limits = (dates.min().date(), dates.max().date())
    names = reviews.drop_duplicates("hotel_id").set_index("hotel_id").hotel_name.to_dict()
    options = sorted(names, key=names.get)
    segments = sorted(reviews.customer_segment.dropna().unique())
    defaults = st.session_state.get("filters", ([], limits, [], ""))
    a, b, c = st.columns([1.2, 1, 1])
    hotels = a.multiselect("Hôtels", options, default=defaults[0], format_func=names.get,
                           placeholder="Tous les hôtels")
    selected_dates = b.date_input("Dates des avis", value=defaults[1], min_value=limits[0],
                                  max_value=limits[1], format="DD/MM/YYYY")
    selected_segments = c.multiselect("Segments clients", segments, default=defaults[2],
                                      format_func=lambda value: data.SEGMENTS.get(value, value),
                                      placeholder="Tous les segments")
    with st.expander("Filtrer par client"):
        customer = st.text_input("Identifiant client exact", value=defaults[3])
    st.session_state["filters"] = hotels, selected_dates, selected_segments, customer
    if len(selected_dates) != 2:
        st.info("Sélectionnez les dates de début et de fin.")
        st.stop()
    return data.filter_reviews(reviews, hotels, selected_dates, selected_segments, customer)


def overview(rows, tables):
    for column, (label, value) in zip(st.columns(4), (
        ("Avis", number(len(rows))), ("Hôtels", number(rows.hotel_id.nunique())),
        ("Note moyenne", number(rows.rating.mean(), 2) + " / 5"),
        ("Taux de réclamation", number(100 * rows.reclamations.mean(), 1) + " %"),
    )):
        with column:
            card(label, value)
    with st.container(border=True):
        st.subheader("Évolution mensuelle des avis")
        monthly = tables["monthly_trends"] if tables else data.aggregate(rows, ["mois"])
        monthly = monthly.assign(mois=pd.to_datetime(monthly.mois)).sort_values("mois")
        figure = px.area(monthly, x="mois", y="avis", labels={"mois": "Mois", "avis": "Avis"},
                         color_discrete_sequence=[BLUE], markers=True)
        figure.update_traces(line_color="#366783")
        figure.update_xaxes(tickformat="%m/%Y")
        chart(figure)
    with st.container(border=True):
        st.subheader("Répartition des sentiments")
        counts = (tables["sentiment_distribution"].groupby("sentiment_normalise").avis.sum()
                  if tables else rows.sentiment.value_counts())
        sentiment = counts.rename(index=data.SENTIMENTS).rename_axis("Sentiment").reset_index(name="Avis")
        chart(px.bar(sentiment, x="Avis", y="Sentiment", color="Sentiment", text="Avis",
                     color_discrete_map=COLORS).update_layout(showlegend=False))


def hotels(rows, tables):
    ranked = data.aggregate(rows, ["hotel_id", "hotel_name"])
    if tables:
        recorded = tables["hotel_kpis"].drop(columns=["resolues"], errors="ignore")
        ranked = recorded.merge(ranked[["hotel_id", "resolues"]], on="hotel_id", validate="one_to_one")
    ranked = ranked.sort_values(["note_moyenne", "avis", "hotel_id"], ascending=[False, False, True])
    ranked["taux_resolution"] = 100 * ranked.resolues / ranked.reclamations.where(ranked.reclamations > 0)
    a, b = st.columns([1, 1])
    with a.container(border=True):
        st.subheader("Hôtels les mieux notés")
        chart(px.bar(ranked.head(10).iloc[::-1], x="note_moyenne", y="hotel_name", hover_data=["avis"],
                     labels={"note_moyenne": "Note / 5", "hotel_name": "Hôtel"},
                     color_discrete_sequence=[BLUE]).update_xaxes(range=[0, 5]))
    with b.container(border=True):
        st.subheader("Comparer les hôtels")
        names = ranked.set_index("hotel_id").hotel_name.to_dict()
        selection = st.multiselect("Hôtels à comparer", list(names), default=list(names)[:3],
                                   max_selections=8, format_func=names.get)
        chosen = ranked[ranked.hotel_id.isin(selection)]
        metrics = {"Note moyenne / 5": "note_moyenne", "Réclamations (%)": "pct_reclamations",
                   "Réclamations résolues (%)": "taux_resolution", "Non résolues": "non_resolues",
                   "Délai de réponse (h)": "reponse_moyenne_heures"}
        metric = st.selectbox("Indicateur de comparaison", list(metrics))
        chart(px.bar(chosen, x="hotel_name", y=metrics[metric],
                     labels={"hotel_name": "Hôtel", metrics[metric]: metric},
                     color_discrete_sequence=[CORAL]))
    st.subheader("Classement et traitement des réclamations")
    st.dataframe(ranked[["hotel_name", "avis", "note_moyenne", "pct_reclamations", "non_resolues",
                       "taux_resolution", "reponse_moyenne_heures", "resolution_moyenne_jours"]].round(2)
                 .rename(columns={"hotel_name": "Hôtel", "avis": "Avis", "note_moyenne": "Note / 5",
                                  "pct_reclamations": "Réclamations (%)", "non_resolues": "Non résolues",
                                  "taux_resolution": "Résolues (%)", "reponse_moyenne_heures": "Réponse moy. (h)",
                                  "resolution_moyenne_jours": "Résolution moy. (j)"}), hide_index=True)
    st.caption("« Non résolues » désigne le statut unresolved. Le taux de résolution est calculé sur toutes les réclamations.")


def customers(rows, tables):
    with st.container(border=True):
        st.subheader("Sentiments au fil des mois")
        trend = rows.groupby(["mois", "sentiment"]).size().reset_index(name="Avis")
        trend["Sentiment"] = trend.sentiment.map(data.SENTIMENTS)
        chart(px.line(trend, x="mois", y="Avis", color="Sentiment", markers=True,
                      labels={"mois": "Mois"}, color_discrete_map=COLORS, line_dash="Sentiment")
              .update_xaxes(tickformat="%m/%Y"))
    a, b = st.columns(2)
    segments = (tables["customer_segments"].rename(columns={"segment_client": "customer_segment"})
                if tables else data.aggregate(rows, ["customer_segment"]))
    complaints = rows[rows.reclamations]
    categories = (tables["complaint_analytics"].groupby("categorie_reclamation").avis.sum()
                  if tables else complaints.primary_aspect.value_counts())
    with a.container(border=True):
        st.subheader("Segments clients")
        segments = segments.assign(Segment=segments.customer_segment.replace(data.SEGMENTS))
        chart(px.bar(segments.sort_values("avis", ascending=False), x="Segment", y="avis",
                     labels={"avis": "Avis"}, color_discrete_sequence=[BLUE]))
    with b.container(border=True):
        st.subheader("Motifs de réclamation")
        categories = categories.nlargest(8).sort_values().rename(index=data.ASPECTS).rename_axis("Motif").reset_index(name="Réclamations")
        chart(px.bar(categories, x="Réclamations", y="Motif", color_discrete_sequence=[CORAL]))
    for column, label, metric, unit in (
        (a, "Délai moyen de réponse", "reponse_moyenne_heures", "h"),
        (b, "Délai moyen de résolution", "resolution_moyenne_jours", "j"),
    ):
        with column:
            value = rows[metric].mean()
            card(label, f"{number(value, 1)} {unit}" if pd.notna(value) else "—")
            st.caption(f"{number(rows[metric].count())} délais mesurés")


def ai():
    try:
        model, evaluation = classifier()
    except (OSError, ValueError):
        st.error("Le modèle Phase 3 ou son rapport est indisponible.")
        return
    with st.container(border=True):
        st.subheader("Tester un nouvel avis")
        with st.form("prediction"):
            review = st.text_area("Texte de l’avis", max_chars=4000,
                                  placeholder="Saisissez un avis en anglais pour une analyse représentative du jeu d’entraînement.")
            submitted = st.form_submit_button("Analyser l’avis", type="primary")
        if submitted and review.strip():
            result = model.predict(review.strip())
            sentiment = data.SENTIMENTS[result["predicted_sentiment"]]
            st.success(f"Sentiment prédit · {sentiment}")
            probabilities = result.get("probabilities", {})
            if probabilities:
                frame = pd.DataFrame({"Sentiment": [data.SENTIMENTS[k] for k in probabilities],
                                      "Probabilité (%)": [100 * p for p in probabilities.values()]})
                chart(px.bar(frame, x="Probabilité (%)", y="Sentiment", color="Sentiment",
                             color_discrete_map=COLORS, text_auto=".1f")
                      .update_xaxes(range=[0, 100]).update_layout(showlegend=False))
        elif submitted:
            st.warning("Saisissez un avis avant de lancer l’analyse.")
    metrics = evaluation["test_metrics"]
    for column, label, value in zip(st.columns(3), ("Exactitude", "F1 macro", "Avis de test"),
                                    (number(100 * metrics["accuracy"], 2) + " %",
                                     number(metrics["macro_f1"], 3), number(metrics["row_count"]))):
        with column:
            card(label, value)
    confusion = metrics["confusion_matrix"]
    labels = [data.SENTIMENTS[label] for label in confusion["labels"]]
    with st.container(border=True):
        st.subheader("Matrice de confusion")
        chart(px.imshow(confusion["matrix"], x=labels, y=labels, text_auto=True, aspect="auto",
                        labels={"x": "Prédit", "y": "Réel", "color": "Avis"},
                        color_continuous_scale=["#F8F3EA", "#7CB5D5", "#3B6D88"]))
    st.info("Le classificateur a été entraîné sur des avis synthétiques en anglais. Les résultats présentés mesurent "
            "les performances sur un test synthétique. La généralisation aux avis réels et aux autres langues reste à valider.")


def cloud():
    if st.button("Actualiser l’état de MinIO"):
        status_check.clear()
    with st.spinner("Vérification de MinIO…"):
        status = status_check(SETTINGS)
    if status["accessible"]:
        st.success(f"MinIO opérationnel · bucket {SETTINGS['bucket']} accessible")
    elif status["ready"]:
        st.warning("MinIO répond. Vérifiez les identifiants et le nom du bucket.")
    else:
        st.warning("MinIO ne répond pas depuis cette application.")
    st.caption("La sonde vérifie la disponibilité HTTP et l’accès au bucket. Les contrôles sont mis en cache 20 secondes.")
    for column, label, value in zip(st.columns(3), ("Stockage", "Exécution Spark", "Connecteur"),
                                    ("MinIO · volume Docker", "Linux · local[2]", "Hadoop S3A")):
        with column:
            card(label, value)
    st.subheader("Architecture vérifiée")
    st.markdown("**Parquet dans MinIO** → **Lecture Spark S3A** → **Agrégation** → **Écriture Parquet** → **Relecture S3A**")
    st.caption("Le SDK MinIO publie les fichiers existants. Hadoop S3A prend en charge les opérations Parquet de Spark.")
    report = status["report"]
    if not report:
        saved = ROOT / "dashboard" / "phase4_verified.json"
        if saved.is_file():
            report = json.loads(saved.read_text(encoding="utf-8"))
            st.info("Exécution historique · copie locale du rapport vérifié.")
    if report:
        for column, label, value in zip(st.columns(3), ("Avis lus", "Lignes écrites et relues", "Artefacts Phase 3 vérifiés"),
                                        (report["input_rows"], report["output_rows"], report["verified_phase3_objects"])):
            with column:
                card(label, number(value))
        st.code(report["output_uri"], language=None)
        with st.expander("Versions du runtime et schéma Parquet"):
            st.json({"Runtime": report["runtime"], "Schéma": report["output_schema"]})
    else:
        st.info("Le rapport d’exécution Phase 4 est indisponible.")


def performance():
    path = ROOT / "benchmarks" / "phase5_results.json"
    if not path.is_file():
        st.info("Aucun résultat enregistré. Lancez le benchmark avec la commande du README.")
        return
    report = json.loads(path.read_text(encoding="utf-8"))
    st.caption(f"{report['configuration']['warmups']} échauffement(s) et {report['configuration']['repeats']} répétitions par moteur et par taille.")
    stages = {"read": "Lecture", "process": "Traitement", "export": "Export"}
    label = st.radio("Étape comparée", list(stages.values()), horizontal=True)
    summary = pd.DataFrame(report["summary"])
    selected = summary[summary.stage.map(stages).eq(label)].copy()
    selected["Taille"] = selected.rows.map(number)
    selected["Moteur"] = selected.engine
    with st.container(border=True):
        st.subheader(f"{label} · temps médian")
        chart(px.bar(selected, x="Taille", y="median_s", color="Moteur", barmode="group",
                     error_y="stdev_s", labels={"median_s": "Secondes", "Taille": "Nombre d’avis"},
                     color_discrete_map={"Spark": BLUE, "Pandas": CORAL}))
        st.caption("Les barres d’erreur indiquent un écart-type. Les temps sont des mesures sur cet ordinateur.")
    st.dataframe(selected[["Taille", "Moteur", "median_s", "stdev_s", "min_s", "max_s"]].round(4)
                 .rename(columns={"median_s": "Médiane (s)", "stdev_s": "Écart-type (s)",
                                  "min_s": "Minimum (s)", "max_s": "Maximum (s)"}), hide_index=True)
    st.markdown("Spark et Pandas lisent le même Parquet et calculent les mêmes agrégats mensuels par sentiment. "
                "L’export utilise le même écrivain CSV pour les deux moteurs. Les temps varient avec la taille, "
                "le parallélisme et le coût de démarrage des tâches.")
    with st.expander("Machine, paramètres et protocole"):
        st.json(report["configuration"])
    csv = path.with_suffix(".csv")
    if csv.is_file():
        st.download_button("Télécharger les mesures CSV", csv.read_bytes(), file_name=csv.name, mime="text/csv")


def main():
    st.set_page_config(page_title="CloudMind · Observatoire hôtelier", layout="wide")
    st.markdown("""
    <style>
    [data-testid="stMainBlockContainer"] { max-width: 1360px; padding-top: 2rem; }
    [data-testid="stSidebar"] { border-right: 1px solid #e4d9ce; }
    [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] > [data-testid="stMetric"]),
    [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] > [data-testid="stPlotlyChart"]) {
      background: #fffcf7; border-radius: 16px; box-shadow: 0 4px 18px #2637460d; }
    [data-testid="stCaptionContainer"] p { color: #536271; }
    [data-testid="stMetricValue"] { font-weight: 670; }
    [data-testid="stWidgetLabel"] p, [data-testid="stSidebar"] label p { font-size: .9rem; }
    [data-testid="stAppDeployButton"] { display: none; }
    .cloud-brand { font-size: 1.65rem; font-weight: 750; letter-spacing: -.04em; color: #263746; }
    .cloud-kicker { color: #8a4435; font-size: .94rem; font-weight: 650; }
    .cloud-hero { padding: 1.4rem 1.6rem; border-radius: 18px; border: 1px solid #e9d9cb;
      background: linear-gradient(115deg,#fff6ed 15%,#fbe7db 63%,#e0eef3 100%); margin-bottom: 1.35rem; }
    .cloud-hero h1 { font-family: Georgia,serif; font-weight: 500; padding: .14rem 0 0;
      font-size: clamp(1.9rem, 4vw, 3rem); }
    </style>
    """, unsafe_allow_html=True)
    with st.sidebar:
        st.markdown('<div class="cloud-brand">CloudMind</div>', unsafe_allow_html=True)
        st.caption("Observatoire des avis hôteliers")
        page = st.radio("Navigation", PAGES, label_visibility="collapsed")
        st.divider()
        source = st.selectbox("Source analytique", ["Locale", "MinIO"],
                              index=1 if os.environ.get("CLOUDMIND_DASHBOARD_SOURCE", "").lower() == "minio" else 0)
    st.markdown(f'<div class="cloud-hero"><div class="cloud-kicker">Observatoire hôtelier</div><h1>{page}</h1></div>',
                unsafe_allow_html=True)
    views = dict(zip(PAGES, (overview, hotels, customers, ai, cloud, performance)))
    if page in PAGES[3:]:
        views[page]()
        return
    try:
        with st.spinner("Chargement des avis et des indicateurs…"):
            reviews, tables = analytics(source, SETTINGS)
    except Exception:
        if source != "MinIO":
            st.error("Les Parquet locaux des phases 1 et 2 sont indisponibles ou incomplets.")
            return
        st.warning("Les données MinIO sont indisponibles. Le tableau de bord utilise les fichiers locaux.")
        try:
            reviews, tables = analytics("Locale", SETTINGS)
        except Exception:
            st.error("Les fichiers locaux de secours sont indisponibles.")
            return
    selected = filter_controls(reviews)
    if selected.empty:
        st.info("Aucun avis ne correspond à cette combinaison de filtres.")
        return
    st.caption(f"{number(len(selected))} avis dans la sélection")
    views[page](selected, tables if len(selected) == len(reviews) else None)


main()
