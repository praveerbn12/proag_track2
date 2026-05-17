"""LLM-based anomaly explanation generator.

Reads Phase 4's fact_anomalies table (stats-flagged outliers).
For each flag, generates a plain-English explanation via the LLM client.
Writes results to fact_anomaly_explanations for the dashboard to consume.

Flow:
    fact_anomalies (stats output)
        ↓
    for each flag → build context dict → llm_client.generate(...)
        ↓
    fact_anomaly_explanations (LLM output, dashboard input)

Key design decision: the LLM never sees raw data. It receives a structured
context dict with the metric name, the cycle's value, the peer average, and
the z-score. Numbers come from stats; words come from the LLM.
"""
import pandas as pd
from sqlalchemy import create_engine
from pipeline.config import DB_PATH
from analytics.llm_client import generate


def _engine():
    return create_engine(f"sqlite:///{DB_PATH}")


def _peer_average_for_metric(metric, cycle_id, all_pnl_df):
    """Look up the peer-average value for a given metric.

    Excludes the cycle being explained, and excludes in-flight cycles.
    """
    peers = all_pnl_df[
        (all_pnl_df["status"] == "closed")
        & (all_pnl_df["cycle_id"] != cycle_id)
    ]
    metric_col_map = {
        "pnl_per_head": "pnl_per_head",
        "cost_per_head": "cost_attributed",  # we'll compute per-head below
        "mortality_pct": "mortality_pct",
        "feed_cost_per_head": None,  # handled separately
        "nursery_days": None,  # handled separately
        "net_pnl": "net_pnl",
    }
    col = metric_col_map.get(metric)
    if col is None or col not in peers.columns:
        return None
    vals = peers[col].dropna()
    return float(vals.mean()) if len(vals) > 0 else None


def explain_anomaly(anomaly_row, all_pnl_df):
    """Build the context for one anomaly flag and call the LLM client.

    Args:
        anomaly_row: a single row from fact_anomalies (as dict or Series)
        all_pnl_df: the full fact_cycle_pnl DataFrame (for peer averages)

    Returns:
        str: the LLM-generated explanation
    """
    cycle_id = anomaly_row["cycle_id"]
    metric = anomaly_row["metric"]
    value = anomaly_row["value"]
    z_score = anomaly_row.get("z_score")
    severity = anomaly_row["severity"]
    note = anomaly_row.get("note", "")

    # Try to extract peer average from the note (e.g., "vs peer avg 43.00 (z=2.8)")
    peer_avg = None
    if note and "peer avg" in note:
        try:
            after = note.split("peer avg")[1]
            peer_avg = float(after.split("(")[0].strip())
        except Exception:
            peer_avg = None

    # Fall back to computing from the data if not in the note
    if peer_avg is None:
        peer_avg = _peer_average_for_metric(metric, cycle_id, all_pnl_df)

    # Build context for the LLM client
    context = {
        "cycle_id": cycle_id,
        "metric": metric,
        "value": float(value) if value is not None else 0,
        "peer_avg": float(peer_avg) if peer_avg is not None else 0,
        "z_score": float(z_score) if z_score is not None else 0,
        "severity": severity,
    }

    return generate("anomaly", context)


def explain_all_anomalies():
    """Process every row in fact_anomalies and write explanations to a new table.

    Returns:
        DataFrame with cycle_id, metric, severity, value, z_score, note, explanation
    """
    engine = _engine()

    # Load the stats-flagged anomalies
    try:
        anomalies = pd.read_sql("SELECT * FROM fact_anomalies", engine)
    except Exception:
        print("  ⚠️  fact_anomalies table not found. Run Phase 4 first:")
        print("      python -m analytics.pnl")
        return pd.DataFrame()

    if anomalies.empty:
        print("  No anomalies in fact_anomalies — nothing to explain.")
        return pd.DataFrame()

    # Load P&L for peer averages
    try:
        all_pnl = pd.read_sql("SELECT * FROM fact_cycle_pnl", engine)
    except Exception:
        all_pnl = pd.DataFrame()

    # Generate explanations
    # Skip status flags for in-flight cycles — these aren't real anomalies
    anomalies = anomalies[anomalies["metric"] != "status"].copy()

    # Generate explanations
    explanations = []
    for _, row in anomalies.iterrows():
        try:
            explanation = explain_anomaly(row.to_dict(), all_pnl)
        except Exception as e:
            explanation = f"(unable to generate explanation: {e})"

        explanations.append({
            "cycle_id": row["cycle_id"],
            "metric": row["metric"],
            "severity": row["severity"],
            "value": row.get("value"),
            "z_score": row.get("z_score"),
            "note": row.get("note"),
            "explanation": explanation,
        })

    out_df = pd.DataFrame(explanations)
    out_df.to_sql("fact_anomaly_explanations", engine, if_exists="replace", index=False)
    return out_df


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("LLM Anomaly Explainer")
    print("=" * 70)

    df = explain_all_anomalies()

    if df.empty:
        print("\nNo anomaly explanations generated.")
    else:
        print(f"\nGenerated {len(df)} anomaly explanations.")
        print(f"Wrote to table: fact_anomaly_explanations\n")

        # Print each one cleanly
        for _, row in df.iterrows():
            print(f"  [{row['severity']:<6}] {row['cycle_id']} — {row['metric']}")
            print(f"  {row['explanation']}")
            print()