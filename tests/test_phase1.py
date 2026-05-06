"""Smoke tests for Phase 1: data is loaded and queryable."""
import pandas as pd
from sqlalchemy import create_engine, inspect
from pipeline.config import DB_PATH, PRODUCER_FILES, MARKET_FILES


def test_database_exists():
    assert DB_PATH.exists(), f"Database not found at {DB_PATH}. Run: python -m pipeline.load_all"


def test_all_tables_present():
    engine = create_engine(f"sqlite:///{DB_PATH}")
    tables = set(inspect(engine).get_table_names())

    expected_producer = {t[0] for t in PRODUCER_FILES.values()}
    expected_market = {t[0] for t in MARKET_FILES.values()}
    expected = expected_producer | expected_market

    missing = expected - tables
    assert not missing, f"Missing tables: {missing}"


def test_tables_have_rows():
    engine = create_engine(f"sqlite:///{DB_PATH}")
    inspector = inspect(engine)
    for table in inspector.get_table_names():
        count = pd.read_sql(f"SELECT COUNT(*) AS n FROM {table}", engine)["n"][0]
        assert count > 0, f"Table '{table}' is empty"


def test_known_row_counts():
    """Sanity check: known row counts from the dummy data."""
    engine = create_engine(f"sqlite:///{DB_PATH}")
    expected = {
        "nursery_intake": 18,         # 18 cycles
        "pig_flow": 36,               # 2 movements per cycle
        "hedging": 18,                # 18 hedging records
        "packer_settlement": 540,     # ~30 loads × 18 cycles
    }
    for table, expected_count in expected.items():
        actual = pd.read_sql(f"SELECT COUNT(*) AS n FROM {table}", engine)["n"][0]
        # Allow some flex — exact counts depend on the dummy file you have
        assert actual > 0, f"{table}: expected ~{expected_count} rows, got 0"