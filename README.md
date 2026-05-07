# AI-powered Football Prediction Model

A comprehensive Python project that combines several open data sources and trains a
prediction model for match outcomes (1X2), total goals (Over/Under), exact scores
(xG-based) and player-level metrics.

> **Target audience:** beginners — code is commented thoroughly and the notebook
> `notebooks/01_full_pipeline.ipynb` walks through the entire process.

---

## 1. Data sources and their roles

| Source | What it provides | What we use it for | Library |
|--------|------------------|---------------------|---------|
| **StatsBomb Open Data** ([github.com/statsbomb/open-data](https://github.com/statsbomb/open-data)) | Event-level data (every pass, shot, pressure): World Cups, Messi data, NWSL, Champions League finals | "Ground truth" xG, pressure and pass networks, model calibration | `statsbombpy` |
| **FBref** (Sports Reference) | Season- and match-level advanced stats for top-5 leagues, Euro cups, and many more | Base data — team xG, xGA, PPDA, corner and card stats. Direct export to Python / Power BI | `soccerdata.FBref` |
| **Understat** | Shot-level xG for six big leagues since 2014 | xG trend visualization, rolling-form features | `soccerdata.Understat` |
| **SofaScore** | Live match info, stats, momentum | Live tracking and in-game features | `soccerdata.Sofascore` (unofficial) |
| **ClubElo** | Team Elo ratings at daily granularity | Strength baseline | `soccerdata.ClubElo` |

**Important:** We use the `soccerdata` library, an open-source community project by
Pieter Robberechts that handles the complex scraping logic for us. Read each source's
terms of service (especially SofaScore — not for commercial use without permission).

---

## 2. Veikkausliiga and Nordic leagues

Veikkausliiga is not in StatsBomb's or Understat's open data. FBref covers Finland's
Veikkausliiga and many Nordic leagues — we use it as the primary source and complement
with ClubElo. For Veikkausliiga, player-level xG data is more limited, so player
predictions focus on the top-5 leagues and Euro cups.

---

## 3. Installation

```bash
# 1. Create a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch Jupyter
jupyter lab
```

Open `notebooks/01_full_pipeline.ipynb` and run the cells in order.

---

## 4. Folder layout

```
football-prediction/
├── README.md                     # This file
├── requirements.txt              # Python dependencies
├── config.py                     # Settings and constants
├── data/
│   ├── raw/                      # Raw data (downloaded here)
│   └── processed/                # Processed data
├── src/
│   ├── data/                     # Data source modules
│   │   ├── fbref.py              #   - FBref scraper
│   │   ├── understat.py          #   - Understat xG
│   │   ├── statsbomb.py          #   - StatsBomb open data
│   │   └── sofascore.py          #   - SofaScore live
│   ├── features/                 # Feature engineering
│   │   ├── team_features.py
│   │   └── player_features.py
│   ├── models/                   # Prediction models
│   │   ├── dixon_coles.py        #   - Poisson model for goals
│   │   ├── outcome_model.py      #   - 1X2 + O/U gradient boosting
│   │   └── player_model.py       #   - Player-level predictions
│   └── viz/
│       └── xg_plots.py           # Understat xG trends
├── notebooks/
│   └── 01_full_pipeline.ipynb    # Main tutorial
└── docs/
    └── arkkitehtuuri.md          # Technical architecture
```

---

## 5. Brief model descriptions

### Dixon-Coles Poisson (goals)
A cornerstone of football statistics: assume that home and away goals are
(approximately) Poisson-distributed. Dixon & Coles (1997) added a correction term
that handles the over-representation of low scores (0-0, 1-1, 0-1, 1-0).
From this model we get:
- Exact-score distribution
- 1X2 probabilities (by summing)
- Over/Under N goals (by summing)
- BTTS probability

### Gradient Boosting (1X2 and O/U)
An alternative model that uses team rolling-form features
(last 5 / 10 match averages of xG, xGA, PPDA, …) and learns to predict
the outcome directly. We use **LightGBM** because it's fast and works
well on small-to-medium tabular data.

### Player model
Simple baseline: **per-90 features** (xG/90, xA/90, shots/90),
weighted by exposure (minutes) and opponent strength. This is a
well-documented strong baseline that you can build hierarchical models on top of.

---

## 6. Live tracking (SofaScore)

The script `src/data/sofascore.py` contains a function that fetches matches in
progress. You can run it every 60 seconds in the notebook and update predictions
in-game.

> ⚠️ SofaScore does not have an official open API. The `soccerdata` library
> uses an unofficial route — use sparingly and only for personal experimentation.

---

## 7. Power BI integration

FBref data is stored as CSV in `data/processed/`. In Power BI:
1. **Get Data → Folder** and point to `data/processed/`
2. Combine files with Power Query
3. Build your own dashboards by team / league

This project focuses on the modeling itself — a Power BI dashboard is
a natural next step, but it's left to the reader to choose which KPIs to
start with.

---

## 8. What's next?

When the basic version works, try:
- **Bayesian models (PyMC):** include uncertainty estimates
- **Walk-forward CV:** more honest model evaluation (no future data
  predicting the past)
- **Odds comparison:** learn to calibrate model probabilities
  against the market
- **xT model (expected threat):** from StatsBomb event data
- **Live momentum feature:** SofaScore momentum scores as input

---

## 9. Disclaimer

This project is for **educational and research purposes**. Betting always
involves risk of loss — never bet more than you are willing to lose,
and remember that no model is bulletproof. In Finland, gambling is
currently regulated by Veikkaus, and information about responsible
gambling can be found at peluuri.fi.
