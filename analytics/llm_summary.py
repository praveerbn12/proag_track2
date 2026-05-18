"""LLM-based cycle summary generator.

For every cycle in fact_cycle_pnl, generates a 2-3 sentence narrative
that describes the cycle's outcome in plain English. Writes to
fact_cycle_summaries for the dashboard to consume.

Flow:
    fact_cycle_pnl
        ↓
    for each cycle → build context dict → llm_client.generate(...)
        ↓
    fact_cycle_summaries (cycle_id, summary)
"""
import pandas as pd
from sqlalchemy import create_engine
from pipeline.config import DB_PATH
from analytics.llm_client import generate


def _engine():
    return create_engine(f"sqlite:///{DB_PATH}")


def summarize_cycle(pnl_row):
    """Build context for one cycle and call the LLM client.

    Args:
        pnl_row: a single row from fact_cycle_pnl (as dict)

    Returns:
        str: the LLM-generated summary
    """
    context = {
        "cycle_id": pnl_row["cycle_id"],
        "status": pnl_row["status"],
        "placed_head": int(pnl_row["placed_head"]) if pd.notna(pnl_row.get("placed_head")) else 0,
        "mortality_pct": float(pnl_row["mortality_pct"]) if pd.notna(pnl_row.get("mortality_pct")) else 0,
        "pnl_per_head": float(pnl_row["pnl_per_head"]) if pd.notna(pnl_row.get("pnl_per_head")) else None,
        "cost_per_head": (
            float(pnl_row["cost_attributed"]) / int(pnl_row["placed_head"])
            if pd.notna(pnl_row.get("cost_attributed")) and pnl_row.get("placed_head", 0) > 0
            else 0
        ),
        "packer_revenue": float(pnl_row["packer_revenue"]) if pd.notna(pnl_row.get("packer_revenue")) else None,
        "hedge_pnl": float(pnl_row["hedge_pnl"]) if pd.notna(pnl_row.get("hedge_pnl")) else 0,
    }
    return generate("summary", context)


def summarize_all_cycles():
    """Generate summaries for every cycle in fact_cycle_pnl.

    Returns:
        DataFrame with cycle_id, status, summary
    """
    engine = _engine()

    try:
        pnl = pd.read_sql("SELECT * FROM fact_cycle_pnl", engine)
    except Exception:
        print("  ⚠️  fact_cycle_pnl table not found. Run Phase 4 first:")
        print("      python -m analytics.pnl")
        return pd.DataFrame()

    if pnl.empty:
        print("  No cycles in fact_cycle_pnl.")
        return pd.DataFrame()

    summaries = []
    for _, row in pnl.iterrows():
        try:
            summary = summarize_cycle(row.to_dict())
        except Exception as e:
            summary = f"(unable to generate summary: {e})"

        summaries.append({
            "cycle_id": row["cycle_id"],
            "producer": row.get("producer"), 
            "status": row["status"],
            "summary": summary,
        })

    out_df = pd.DataFrame(summaries)
    out_df.to_sql("fact_cycle_summaries", engine, if_exists="replace", index=False)
    return out_df


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("LLM Cycle Summary Generator")
    print("=" * 70)

    df = summarize_all_cycles()

    if df.empty:
        print("\nNo summaries generated.")
    else:
        print(f"\nGenerated {len(df)} cycle summaries.")
        print(f"Wrote to table: fact_cycle_summaries\n")
        for _, row in df.iterrows():
            print(f"  [{row['status']}] {row['cycle_id']}")
            print(f"  {row['summary']}")
            print()