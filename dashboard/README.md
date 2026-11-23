# Phase 5 — Observatoire hôtelier CloudMind

## Lancer le tableau de bord

Depuis la racine du projet dans PowerShell :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-phase5.txt
.\.venv\Scripts\python.exe -m streamlit run dashboard\app.py --server.address 127.0.0.1 --server.port 8505 --server.headless true
```

Ouvrez http://127.0.0.1:8505. Le tableau de bord est lié à l’interface de bouclage locale. Si nécessaire, remplacez `8505` par un port libre.

Les trois vues analytiques utilisent les cinq tables Parquet Phase 2 pour le périmètre complet. Dès qu’un filtre réduit ce périmètre, les indicateurs sont calculés sur les avis Phase 1 sélectionnés. Les filtres hôtel, dates inclusives, segment et identifiant client sont partagés. Le taux de réclamation utilise tous les avis de la sélection comme dénominateur. Le taux de résolution utilise toutes ses réclamations. Le délai de réponse concerne les réclamations résolues ou en cours avec un délai mesuré. Le délai de résolution utilise les réclamations résolues avec un délai mesuré.

Les Parquet sont mis en cache cinq minutes. La prédiction recharge le modèle enregistré Phase 3 une fois par processus Streamlit, après le premier accès à la vue IA. Elle utilise le texte saisi sans Spark ni réentraînement. Le modèle a été entraîné sur des avis synthétiques en anglais.

## Utiliser MinIO

L’option **Source analytique** permet de choisir les fichiers locaux ou la copie MinIO vérifiée. L’application utilise les valeurs de `.env.phase4` lorsqu’il existe. Les variables du processus ont priorité. Le fichier réel de la Phase 4 reste ignoré par Git.

| Variable | Valeur ou rôle |
|---|---|
| `CLOUDMIND_DASHBOARD_SOURCE` | Facultatif. `minio` sélectionne MinIO au lancement. |
| `CLOUDMIND_MINIO_ENDPOINT` | URL API. Par défaut, `http://127.0.0.1:9000`, en tenant compte de `MINIO_API_PORT`. |
| `CLOUDMIND_BUCKET` | `cloudmind` par défaut. |
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | Identifiants locaux de la configuration Phase 4. |
| `CLOUDMIND_PHASE4_RUN` | Par défaut, `run-4ff3862adb014f2ca339df466c17e025`. Le snapshot doit contenir les Parquet Phase 1 et 2. |

En cas d’échec de lecture MinIO, la vue analytique avertit l’utilisateur puis utilise les mêmes Parquet locaux. La page Spark & cloud affiche l’état courant de la sonde HTTP et de l’accès au bucket. Elle étiquette la copie locale du rapport vérifié comme historique quand le rapport distant est indisponible. La page sépare les opérations Spark S3A historiques des lectures du tableau de bord via le SDK.

## Reproduire les mesures

```powershell
.\.venv\Scripts\python.exe benchmarks\phase5.py --sizes 10000 50000 100000 --warmups 1 --repeats 3
.\.venv\Scripts\python.exe -m pytest -q
```

Le benchmark crée des Parquet temporaires à partir des premières N lignes physiques du Parquet existant. Les deux moteurs lisent des fichiers identiques, agrègent par mois et sentiment, et calculent le nombre d’avis, la note moyenne et le nombre de réclamations. Chaque paire de résultats est vérifiée, avec une tolérance relative de `1e-12` sur les moyennes. Les fichiers d’origine sont conservés. Les empreintes SHA-256 des entrées, la configuration et chaque chronométrage sont enregistrés en JSON. Le CSV contient chaque mesure chronométrée.

- **Lecture.** Chargement matérialisé, incluant `persist().count()` pour Spark.
- **Traitement.** Agrégation et matérialisation des résultats sous forme de tuples Python.
- **Export.** Même écrivain CSV Python pour les deux moteurs, jusqu’à la fermeture du fichier. Cette étape mesure l’export local commun après matérialisation.

Chaque combinaison est échauffée avant trois répétitions chronométrées. L’ordre des moteurs est alterné. Le démarrage de la JVM, la préparation des Parquet et la libération du cache Spark sont hors chronométrage. Le cache disque du système est conservé. La page Performance affiche la médiane, l’écart-type d’échantillon et les extrêmes de chaque étape. Les mesures caractérisent une machine et un traitement précis.

## Mesures du 23 novembre 2026

Hôte Windows, processeur Intel avec 12 processeurs logiques et 16,87 Go de mémoire, Python 3.11.9, Java 21.0.13.1, Spark 4.0.4 en `local[2]`, Pandas 2.3.3 et PyArrow 26.0.1. Les médianes ci-dessous sont en millisecondes.

| Avis | Moteur | Lecture | Traitement | Export |
|---:|---|---:|---:|---:|
| 10 000 | Spark | 227,09 | 269,07 | 0,68 |
| 10 000 | Pandas | 2,99 | 44,07 | 0,69 |
| 50 000 | Spark | 175,59 | 213,78 | 0,70 |
| 50 000 | Pandas | 5,33 | 199,39 | 0,74 |
| 100 000 | Spark | 201,71 | 213,33 | 0,69 |
| 100 000 | Pandas | 7,86 | 398,38 | 0,75 |

Sur ce poste, Pandas a été plus rapide en lecture aux trois tailles. À 100 000 avis, Spark a été plus rapide sur la phase de traitement seule. Les 54 mesures individuelles et leur variabilité sont disponibles dans [le JSON](../benchmarks/phase5_results.json) et [le CSV](../benchmarks/phase5_results.csv).

## Validation du tableau de bord

- Pytest a terminé avec **12 tests réussis et 6 ignorés** en 121,76 secondes. Les six tests ignorés sont les tests Docker de la Phase 4, exécutables séparément. Les tests Phase 5 couvrent le rapprochement des Parquet, les filtres partagés et leurs dénominateurs, la navigation, le retour aux fichiers locaux en cas de panne MinIO et l’égalité des probabilités affichées avec celles du modèle Phase 3.
- Vérification Chromium sur les six pages à 1 440 px et sur la vue d’ensemble à 390 px. Le passage à la source MinIO a chargé les 100 000 avis sans déclencher le secours local, et la page Spark & cloud a confirmé l’accès au bucket.

## Incidents résolus

- Streamlit 1.51 imposait une version de PyArrow antérieure à celle du projet. Streamlit 1.67 conserve PyArrow 26.0.1 et les dépendances des phases précédentes.
- Le port 8501 était occupé. Le tableau de bord a démarré sur 8505 et a répondu HTTP 200.
- Le premier lancement du benchmark s’est arrêté avant les mesures, car PyArrow attend une liste de colonnes. Après correction, chaque paire Spark/Pandas a produit les mêmes agrégats aux trois tailles. Sous Windows, Spark a signalé l’absence de `winutils.exe` et a affiché un message d’accès refusé à l’arrêt. Le benchmark a écrit les deux fichiers et s’est terminé avec le code 0.
- La vérification visuelle a révélé des étiquettes coupées sur le graphique mensuel. Les marges et l’ajustement des axes ont été corrigés puis revérifiés. Le test de navigation a ensuite ciblé explicitement la barre latérale pour la distinguer du sélecteur d’étape ajouté par les résultats du benchmark.
