# ProAg Track 2 -- Producer Analytics

A tool for ProAg advisors to centralize hog producer data and generate AI-assisted insights. Built for the Spring 2026 AI & Analytics Innovation Challenge.

## Team

| Name | Focus |
|------|-------|
| Jayesh Sawarkar | Analytics & AI |
| Praveer Byndoor | Data Pipeline & Architecture |
| Roshni More | Dashboard & UX |

Faculty Mentor: Professor Chris Dunham, Syracuse University iSchool

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the full pipeline

```bash
python3 -m pipeline.load_all    # Phase 1: Load raw data into SQLite
python3 -m pipeline.sites       # Phase 2: Build site hierarchy and cycle trails
python3 -m pipeline.cycles      # Phase 3: Assemble canonical cycle model
python3 -m analytics.pnl        # Phase 4: Compute P&L, hedge gains, anomalies
streamlit run dashboard/app.py  # Phase 5: Launch the Streamlit dashboard
```

## Run tests

```bash
python3 -m pytest tests/ -v
```

36 tests across 5 phases (4 + 4 + 6 + 14 + 8).

## Phase 4 results

- 14 closed cycles, 4 in-flight
- Total revenue: $5,756,845
- Total attributed costs: $722,146
- Total hedge P&L: -$119,947
- Total net P&L: $4,914,752
- Average margin: $157.72/head

## Project structure

- `pipeline/` -- data ingestion and transformation (Phases 1-3)
- `analytics/` -- P&L engine and metrics (Phase 4)
- `dashboard/` -- Streamlit app (Phase 5): `app.py` + `helpers.py`
- `data/raw/` -- source files (do not edit)
- `data/processed/` -- generated SQLite database
- `tests/` -- smoke tests per phase
