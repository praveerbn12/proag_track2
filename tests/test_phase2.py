"""Smoke tests for Phase 2: site hierarchy tables exist and have expected shape."""
import pandas as pd
from sqlalchemy import create_engine, inspect
from pipeline.config import DB_PATH


def _engine():
    return create_engine(f"sqlite:///{DB_PATH}")


def test_phase2_tables_present():
    tables = set(inspect(_engine()).get_table_names())
    expected = {
        "site_barn_mapping", "cycle_trail",
        "producer_packer_relationships", "producer_site_summary",
        "cost_center_profile", "cost_center_category_mix",
        "cost_center_phase_mix",
    }
    missing = expected - tables
    assert not missing, f"Missing Phase 2 tables: {missing}"


def test_cycle_trail_has_18_cycles():
    n = pd.read_sql("SELECT COUNT(DISTINCT cycle_id) AS n FROM cycle_trail",
                    _engine())["n"][0]
    assert n == 18, f"Expected 18 cycles in trail, got {n}"


def test_barn_mapping_one_site_per_barn():
    df = pd.read_sql("SELECT barn_id, COUNT(DISTINCT site) AS n FROM site_barn_mapping "
                     "GROUP BY barn_id", _engine())
    assert (df["n"] == 1).all(), "Some barns map to multiple sites"


def test_cost_centers_are_three():
    n = pd.read_sql("SELECT COUNT(*) AS n FROM cost_center_profile", _engine())["n"][0]
    assert n == 3, f"Expected 3 cost centers (A/B/C), got {n}"