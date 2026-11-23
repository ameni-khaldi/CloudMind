# CloudMind

Phase 1 validates the existing 100,000 synthetic hotel reviews with local Spark SQL, profiles the data, and exports a typed Parquet file. The two CSV copies in the workspace are source files. The default input is `data/raw/hotel_reviews_100k.csv`.

## Reproduce Phase 1 on Windows

Use Python 3.11 and a JDK 17 or 21 installation. From the project root in PowerShell:

```powershell
# Use an existing virtual environment when available.
if (-not (Test-Path .\.venv\Scripts\python.exe)) { python -m venv .venv }
if (-not $env:JAVA_HOME) { $env:JAVA_HOME = [Environment]::GetEnvironmentVariable('JAVA_HOME', 'Machine') }
# If necessary, set JAVA_HOME to the root directory of your JDK 17 or 21.
& (Join-Path $env:JAVA_HOME 'bin\java.exe') -version
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe src\ingestion.py
.\.venv\Scripts\python.exe -m pytest -q
```

Spark uses `JAVA_HOME` even if the shell's `java` resolves to a different installation. The job records the Java version reported by Spark itself. The default master is `local[2]`. Set `CLOUDMIND_SPARK_MASTER` to change it. Use `--input` or `--output-dir` to override the default paths.

## Validation and outputs

- `src/ingestion.py` checks the ordered CSV header against the observed 31-column contract, applies Spark types, and prints the schema and first ten source records. The CSV parser fails on malformed typed values.
- `src/quality.py` checks review grain, ID formats, duplicates, rating bounds, null counts, synthetic flags, and split membership. It profiles rating and split distributions, date range, hotel counts, and response and resolution metrics by status.
- `data/processed/data_quality.json` contains the runtime, schema, full first ten records, quality metrics, and exploratory summaries.
- `data/processed/hotel_reviews.parquet` contains the validated reviews. PyArrow writes a single Snappy-compressed file on the driver because the native Windows Spark writer requires Hadoop's `winutils.exe`. The pipeline compares every value with an Arrow readback and verifies Spark can read the same row count and column types before publishing the file.
- Expected nulls in the response and resolution duration fields are preserved. The pipeline fails validation for unexpected nulls or invalid keys, ratings, splits, or synthetic flags. The original split assignments are preserved for evaluation.

The PyArrow export holds this 100,000-row dataset in driver memory. Docker and Compose are outside the local job's runtime requirements.

## Phase 2 — ETL et analyses Spark

Depuis la racine du projet, après avoir configuré `JAVA_HOME` comme indiqué plus haut :

```powershell
.\.venv\Scripts\python.exe src\phase2.py
.\.venv\Scripts\python.exe -m pytest -q
```

La commande lit `data/processed/hotel_reviews.parquet` et affiche le chemin du nouveau dossier `data/processed/phase2/run-…`. Chaque exécution réussie publie son propre dossier avec cinq fichiers Parquet Snappy et un `rapport_execution.json`. Les options `--input` et `--output-dir` changent la source et le dossier parent. Le pipeline réutilise PyArrow pour l’écriture locale après les calculs Spark et vérifie chaque fichier par relecture Spark.

| Table | Niveau d’agrégation | Lignes vérifiées |
| --- | --- | ---: |
| `hotel_kpis` | Hôtel | 50 |
| `monthly_trends` | Mois civil de l’avis | 46 |
| `customer_segments` | Segment client | 3 |
| `sentiment_distribution` | Segment et sentiment | 9 |
| `complaint_analytics` | Hôtel, segment, catégorie principale et statut | 4 804 |

Chaque table est rapprochée de son équivalent Spark SQL à partir d’une vue temporaire. Le rapport enregistre les schémas, les nombres de lignes, les temps mesurés avec `perf_counter()`, le maître Spark et les partitions observées. Pour les valeurs flottantes, la comparaison SQL utilise une tolérance absolue de 1e-8. Les durées décrivent une exécution locale sur les données synthétiques.

### Définitions des indicateurs

- Le taux de réclamation divise les avis avec réclamation par l’ensemble des avis du groupe. La table `complaint_analytics` contient uniquement les réclamations. Utiliser `hotel_kpis` ou `customer_segments` pour le taux sur l’ensemble des avis.
- Le taux de réclamations non résolues divise les réclamations au statut `unresolved` par l’ensemble des réclamations. Le statut `in_progress` est distinct. Sans réclamation, le taux reste nul au sens SQL (`NULL`).
- Le délai moyen de réponse utilise les délais renseignés des dossiers résolus ou en cours. Le délai moyen de résolution utilise les délais renseignés des dossiers résolus. Les dénominateurs sont `reponses_mesurees` et `resolutions_mesurees`. Une moyenne sans observation reste `NULL`.
- La catégorie d’une réclamation est l’aspect principal normalisé de l’avis signalé. Le rapport classe les catégories par fréquence et présente les volumes et les délais par statut.
- La note moyenne sert d’indicateur de satisfaction. Le rapport compare VIP à Régulier, qui regroupe Standard et Loyalty en pondérant par le nombre d’avis. La table `customer_segments` conserve les trois segments de la source. Dans `sentiment_distribution`, `pct_segment` représente la part du sentiment au sein du segment.

La validation rapproche 100 000 avis et 42 509 réclamations. Les fichiers source de la phase 1 sont conservés.

## Phase 3 — MLlib et audit des fuites

La phase 3 utilise uniquement Apache Spark MLlib. Elle entraîne deux classificateurs pour prédire `sentiment` à partir de `review_text` seulement :

```powershell
.\.venv\Scripts\python.exe src\phase3.py
.\.venv\Scripts\python.exe -m pytest -q
```

La commande lit `data/processed/hotel_reviews.parquet` et publie un nouveau dossier `data/processed/phase3/run-…`. Les options `--input` et `--output-dir` restent disponibles. Le pipeline MLlib utilise `RegexTokenizer`, les mots vides anglais Spark, `HashingTF`, `IDF`, `StringIndexer` et le classificateur choisi. Toutes les transformations apprises sont ajustées uniquement sur l'échantillon d'entraînement.

Les données synthétiques présentent des fuites connues :

- `rating` est exactement associé aux classes : 1-2 = négatif, 3 = neutre, 4-5 = positif.
- `sentiment_score` est dérivé du même sentiment.
- Les titres sont réduits à seulement 24 valeurs exactes.
- 29 786 clients sont répétés au moins une fois ; 17 045 clients se trouvent déjà dans plusieurs divisions fournies.
- 11 502 textes exacts se trouvent dans plusieurs divisions fournies.

Les divisions fournies 70k/10k/20k ne sont donc pas conservées pour l'entraînement. La phase 3 crée une division documentée sans fuite exacte : affectation déterministe des clients par hachage dans les trois groupes, puis retrait des textes exacts présents dans plusieurs groupes. Cette division peut avoir des proportions différentes des divisions 70k/10k/20k.

Les variables `rating`, `sentiment_score`, `review_title`, identifiants, réclamation et autres colonnes dérivées ne sont pas utilisées comme caractéristiques. Les textes et clients sont vérifiés pour détecter tout croisement entre les nouvelles divisions. La validation sert au choix du modèle ; le jeu test n'est utilisé qu'après ce choix. Les métriques, la matrice de confusion, les distributions de classes, les temps d'exécution et les limitations synthétiques sont enregistrés dans `rapport_execution.json`.

Sur Windows, `winutils.exe` n'est pas disponible. Le modèle retenu est donc enregistré comme une archive JSON complète de ses états Spark ML (vocabulaire via IDF, indexeur de classes, coefficients ou paramètres multinomiaux). Cette archive permet la recharge par `SavedTextClassifier`, mais elle n'est pas une commande native `PipelineModel.save/load`.

## Phase 4 — Stockage objet et Spark S3A

La phase 4 utilise MinIO et Docker Compose pour publier les artefacts des phases précédentes et exécuter une analyse Spark sur des fichiers Parquet via S3A. Les commandes et les résultats de vérification figurent dans le [guide de la phase 4](phase4/README.md).

## Phase 5 — Tableau de bord et benchmarks

Depuis la racine du projet, dans PowerShell :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-phase5.txt
.\.venv\Scripts\python.exe -m streamlit run dashboard\app.py --server.address 127.0.0.1 --server.port 8505 --server.headless true
```

Ouvrez http://127.0.0.1:8505. Le [guide de la phase 5](dashboard/README.md) contient le protocole de mesure, les résultats, les options MinIO et les commandes de test.

## Phase 5 — Tableau de bord et benchmarks

Depuis la racine du projet, dans PowerShell :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-phase5.txt
.\.venv\Scripts\python.exe -m streamlit run dashboard\app.py --server.address 127.0.0.1 --server.port 8505 --server.headless true
```

Ouvrez http://127.0.0.1:8505. Le [guide de la phase 5](dashboard/README.md) contient le protocole de mesure, les résultats, les options MinIO et les commandes de test.
