"""Phase 5 smoke tests — dashboard data layer.

These don't spin up Streamlit. They check the helpers work standalone so a
broken data path is caught before the dashboard launches.
"""
from pathlib import Path

import pandas as pd
import pytest

from pipeline.config import DB_PATH


pytestmark = pytest.mark.skipif(
    not Path(DB_PATH).exists(),
    reason="proag.db not built yet — run pipeline.load_all + .sites + analytics.pnl",
)


def _import_data():
    """Import dashboard.data without triggering Streamlit at module level."""
    # The dashboard.data module uses st.cache_data decorators which work
    # outside of a Streamlit run — they just become no-op caches.
    from dashboard import helpers as dd
    return dd


def test_engine_connects():
    dd = _import_data()
    tables = dd.list_tables()
    assert "cycle_trail" in tables
    assert "packer_settlement" in tables


def test_load_pnl_summary_has_18_cycles():
    dd = _import_data()
    df = dd.load_pnl_summary()
    assert len(df) == 18, f"expected 18 cycles, got {len(df)}"
    expected_cols = {"cycle_id", "status", "placed_head", "paid_head",
                     "packer_revenue", "cost_attributed", "hedge_pnl", "net_pnl"}
    assert expected_cols.issubset(df.columns)


def test_load_anomalies_returns_dataframe():
    dd = _import_data()
    df = dd.load_anomalies()
    assert isinstance(df, pd.DataFrame)
    if not df.empty:
        assert {"cycle_id", "metric", "severity", "note"}.issubset(df.columns)


def test_get_cycle_pnl_for_known_cycle():
    dd = _import_data()
    pnl = dd.get_cycle_pnl("PG-1014")
    assert pnl is not None
    assert pnl["cycle_id"] == "PG-1014"
    assert pnl["status"] in ("closed", "in_flight")
    assert "cost_breakdown" in pnl


def test_anonymize_is_stable_and_reversible_within_session():
    dd = _import_data()
    a1 = dd.anon_value("Producer B", "PROD")
    a2 = dd.anon_value("Producer B", "PROD")
    a3 = dd.anon_value("Producer A", "PROD")
    assert a1 == a2, "same input should produce same alias"
    assert a1 != a3, "different inputs should produce different aliases"
    assert a1.startswith("PROD-")


def test_cycle_producer_table_covers_all_cycles():
    dd = _import_data()
    pmap = dd.cycle_producer_table()
    trail = dd.load_cycle_trail()
    assert set(pmap["cycle_id"]) == set(trail["cycle_id"])


def test_apply_filters_status():
    dd = _import_data()
    df = dd.load_pnl_summary()
    closed = dd.apply_filters(df, {"status": "Closed only", "producers": [], "anon": False})
    assert (closed["status"] == "closed").all()


def test_market_table_loads():
    dd = _import_data()
    df = dd.load_market("hog_futures_hem25")
    assert not df.empty, "HEM25 should have rows"
    assert "close" in df.columns
