"""Data access for the dashboard.

If fact_cycle_pnl / fact_anomaly_explanations don't carry a `producer`
column (i.e. the upstream pipeline hasn't been patched yet), we synthesize
one deterministically from the cycle_id so the dashboard works regardless.
"""
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, inspect

from pipeline.config import DB_PATH


def _engine():
    return create_engine(f"sqlite:///{DB_PATH}")


def _has_table(name: str) -> bool:
    try:
        return name in inspect(_engine()).get_table_names()
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────
# Producer synthesis (fallback when pipeline didn't write it)
# ──────────────────────────────────────────────────────────────

_DEMO_PRODUCERS = ["Demo Producer A", "Demo Producer B", "Demo Producer C"]


def _synth_producer(cycle_id):
    """Deterministic round-robin partition. Used only when fact_cycle_pnl
    lacks a producer column from upstream."""
    try:
        n = int(str(cycle_id).split("-")[-1])
    except (ValueError, IndexError):
        n = abs(hash(cycle_id))
    return _DEMO_PRODUCERS[n % len(_DEMO_PRODUCERS)]


def _ensure_producer(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "producer" in df.columns or "cycle_id" not in df.columns:
        return df
    df = df.copy()
    df["producer"] = df["cycle_id"].apply(_synth_producer)
    return df


# ──────────────────────────────────────────────────────────────
# Raw table loaders
# ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_cycles() -> pd.DataFrame:
    if not _has_table("fact_cycle_pnl"):
        return pd.DataFrame()
    df = pd.read_sql("SELECT * FROM fact_cycle_pnl", _engine())
    return _ensure_producer(df)


@st.cache_data(ttl=60)
def load_summaries() -> pd.DataFrame:
    if not _has_table("fact_cycle_summaries"):
        return pd.DataFrame()
    df = pd.read_sql("SELECT * FROM fact_cycle_summaries", _engine())
    return _ensure_producer(df)


@st.cache_data(ttl=60)
def load_anomalies() -> pd.DataFrame:
    if not _has_table("fact_anomaly_explanations"):
        return pd.DataFrame()
    df = pd.read_sql("SELECT * FROM fact_anomaly_explanations", _engine())
    df = _ensure_producer(df)
    if df.empty:
        return df
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    df = df.assign(_ord=df["severity"].map(order).fillna(9))
    return df.sort_values(["_ord", "cycle_id"]).drop(columns="_ord").reset_index(drop=True)


@st.cache_data(ttl=60)
def load_costs(cycle_id: str) -> pd.DataFrame:
    if not _has_table("fact_cycle_costs"):
        return pd.DataFrame()
    return pd.read_sql(
        "SELECT * FROM fact_cycle_costs WHERE cycle_id = ?",
        _engine(),
        params=(cycle_id,),
    )


@st.cache_data(ttl=60)
def load_hedge(cycle_id: str) -> pd.DataFrame:
    if not _has_table("fact_hedge_pnl"):
        return pd.DataFrame()
    return pd.read_sql(
        "SELECT * FROM fact_hedge_pnl WHERE cycle_id = ?",
        _engine(),
        params=(cycle_id,),
    )


@st.cache_data(ttl=60)
def load_trail() -> pd.DataFrame:
    if not _has_table("cycle_trail"):
        return pd.DataFrame()
    return pd.read_sql("SELECT * FROM cycle_trail", _engine())


# ──────────────────────────────────────────────────────────────
# Derived
# ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def producer_rollup() -> pd.DataFrame:
    """One row per producer with portfolio stats + attention score.

    attention = (# HIGH flags × 2) + (# MEDIUM flags)
    """
    cycles = load_cycles()
    anomalies = load_anomalies()
    if cycles.empty:
        return pd.DataFrame()

    closed = cycles[cycles["status"] == "closed"]

    g = cycles.groupby("producer")
    rollup = pd.DataFrame({
        "cycles_total": g.size(),
        "cycles_closed": g.apply(lambda d: (d["status"] == "closed").sum()),
        "cycles_in_flight": g.apply(lambda d: (d["status"] == "in_flight").sum()),
        "head_placed": g["placed_head"].sum(),
        "total_net_pnl": closed.groupby("producer")["net_pnl"].sum().reindex(g.size().index, fill_value=0),
        "avg_pnl_per_head": closed.groupby("producer")["pnl_per_head"].mean().reindex(g.size().index, fill_value=None),
    }).reset_index()

    if not anomalies.empty and "producer" in anomalies.columns:
        score = anomalies.assign(
            w=anomalies["severity"].map({"HIGH": 2, "MEDIUM": 1, "LOW": 0}).fillna(0)
        ).groupby("producer")["w"].sum().rename("attention")
        flag_counts = anomalies.groupby("producer").size().rename("flag_count")
        rollup = rollup.merge(score, on="producer", how="left").merge(flag_counts, on="producer", how="left")
    else:
        rollup["attention"] = 0
        rollup["flag_count"] = 0

    rollup["attention"] = rollup["attention"].fillna(0).astype(int)
    rollup["flag_count"] = rollup["flag_count"].fillna(0).astype(int)
    return rollup.sort_values(["attention", "producer"], ascending=[False, True]).reset_index(drop=True)


def peer_comparison(cycles: pd.DataFrame, cycle_id: str, metric: str) -> dict:
    row = cycles[cycles["cycle_id"] == cycle_id]
    if row.empty:
        return {}
    row = row.iloc[0]
    val = row.get(metric)

    closed = cycles[cycles["status"] == "closed"]
    producer_avg = closed[closed["producer"] == row["producer"]][metric].mean()
    all_avg = closed[metric].mean()

    if pd.isna(val) or pd.isna(producer_avg) or producer_avg == 0:
        delta = None
    else:
        delta = (val - producer_avg) / abs(producer_avg) * 100

    return {
        "this": val,
        "producer_avg": producer_avg,
        "all_avg": all_avg,
        "delta_vs_producer_pct": delta,
    }


def producers(cycles_df: pd.DataFrame) -> list[str]:
    if cycles_df.empty or "producer" not in cycles_df.columns:
        return []
    return sorted(cycles_df["producer"].dropna().unique().tolist())