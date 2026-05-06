# ProAg Track 2 — Producer Analytics

A tool for ProAg advisors to centralize producer data and generate AI-assisted insights.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Phase 1: Load data

```bash
python -m pipeline.load_all
```

This reads everything in `data/raw/` and creates `data/processed/proag.db`.

## Project structure

- `pipeline/` — data ingestion and transformation
- `analytics/` — P&L engine and metrics
- `dashboard/` — Streamlit app
- `data/raw/` — source files (do not edit)
- `data/processed/` — generated SQLite database