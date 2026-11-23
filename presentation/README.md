# CloudMind — Le voyage au cœur des données

Présentation universitaire interactive en français, séparée des phases de traitement CloudMind.

**Ameni Khaldi · ESEN M2DSSD**

## Lancement local

Sous Windows, ouvrez le dossier `presentation` et double-cliquez sur `Launch-CloudMind.bat`. Le lanceur compile la présentation si nécessaire, choisit un port local libre et ouvre le navigateur par défaut.

Pour la première utilisation, installez Node.js 20 ou une version ultérieure, puis exécutez `npm.cmd ci` dans le dossier `presentation`. Une fois les dépendances installées, la compilation et les douze scènes fonctionnent hors ligne. Les liens vers la documentation externe nécessitent une connexion.

Gardez la fenêtre CloudMind ouverte pendant la présentation. Pour arrêter le serveur, fermez cette fenêtre. Vous pouvez ensuite fermer l’onglet du navigateur. Si l’ouverture automatique échoue, copiez l’adresse affichée dans la fenêtre.

Pour le développement, exécutez `npm.cmd run dev` dans `presentation` et ouvrez http://127.0.0.1:5176. Exécutez `npm.cmd run build` pour recompiler après une modification des sources.

L’étape Démonstration ouvre le vrai tableau de bord dans un autre onglet. Lancez-le depuis la racine du projet avec :

```powershell
.\.venv\Scripts\python.exe -m streamlit run dashboard\app.py --server.address 127.0.0.1 --server.port 8505 --server.headless true
```

`VITE_DASHBOARD_URL` permet de choisir une autre adresse avant le lancement ou la compilation.

## Raccourcis

| Commande | Action |
|---|---|
| →, ↓, Espace | Chapitre suivant |
| ←, ↑, Retour arrière | Chapitre précédent |
| N | Afficher ou fermer les notes |
| R | Rejouer l’entrée de la scène |
| Scènes ou progression | Accéder directement à un chapitre |
| Explorer en 3D | Activer la rotation et le zoom |
| Plein écran | Utiliser le mode plein écran du navigateur |
| Mouvement réduit | Couper les déplacements, particules et révélations animées |

Le mode 2D s’active automatiquement si WebGL 2 est indisponible ou si le contexte échoue. Le bouton **2D** et le paramètre `?mode=2d` dans l’adresse de la présentation permettent de le sélectionner manuellement. Les diagrammes 2D, listes de sélection et graphiques restent disponibles. Le réglage système de mouvement réduit est repris au chargement.

## Storyboard et direction graphique

Le parcours traverse des zones du même espace 3D. Les transitions déplacent la caméra entre leurs coordonnées, et la scène précédente est conservée le temps du déplacement. Le fond crème `#F8F3EA`, le corail `#E9957D`, le bleu doux `#7CB5D5` et le bleu nuit `#263746` forment la palette principale. Les titres utilisent une typographie éditoriale avec empattements et les données sont affichées en HTML ou Plotly. Les géométries, particules et trajets sont des illustrations.

| Chapitre | Scène et interaction |
|---|---|
| Introduction | Noyau vitré, orbites et points d’intérêt |
| Problématique | Quartier de 50 bâtiments sélectionnables et indicateurs réels |
| Big Data | Division en partitions, échange et agrégation |
| ETL | Parcours des objets CSV, schéma, contrôle, Parquet et tables |
| Cloud | Bucket, préfixes d’objets et trajet S3A |
| Intelligence artificielle | Tokenisation, TF-IDF, branches de classification et test isolé |
| Résultats IA | Matrice de confusion Plotly et tableau sémantique |
| Analyse métier | Classement par note, réclamations, séries de sentiment et segments |
| Architecture | Carte de composants et chemins analytique et IA |
| Démonstration | Ouverture de Streamlit et indication du parcours d’inférence |
| Limites | Benchmark par étape et perspectives |
| Conclusion et sources | Sources, navigation et téléchargement des mesures |

## Traçabilité

`public/mesures-cloudmind.json` est un extrait des rapports de qualité, Phase 2, Phase 3, Phase 4 et benchmarks, complété par les agrégats Parquet existants. Les chemins d’origine figurent dans le chapitre Sources. Les placements et hauteurs des bâtiments sont illustratifs. Leurs indicateurs sont extraits du Parquet Phase 2.

Pour réexporter l’instantané sans modifier les fichiers sources, exécutez depuis la racine du projet :

```powershell
.\.venv\Scripts\python.exe presentation\export_data.py
```

## Validation

- Trois tests automatisés vérifient les agrégats des hôtels, la matrice de confusion et les mesures S3A et Spark/Pandas.
- Chromium en 1 920 × 1 080 a rendu les douze chapitres. Les vérifications ont couvert le survol et le clic 3D, l’orbite, la navigation clavier et par index, les notes, le plein écran et les graphiques.
- Chromium à 390 px avec WebGL désactivé a confirmé le repli automatique, l’accès à la première et à la dernière des 50 entrées et l’absence de débordement horizontal.
- La présentation fonctionne localement après installation. La démonstration de prédiction dépend du service Streamlit sur le poste. Les modules 3D et Plotly sont chargés à la demande.
