"""Central configuration for paths and table names."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_PRODUCER = ROOT / "data" / "raw" / "producer"
RAW_MARKET = ROOT / "data" / "raw" / "market"
PROCESSED = ROOT / "data" / "processed"
DB_PATH = PROCESSED / "proag.db"

# Producer files: filename → (table_name, date_columns)
PRODUCER_FILES = {
    "2025_dummy_sow_farm_weekly_farrowing.csv": (
        "sow_farrowing", ["Week_Start_Date"]
    ),
    "2025_dummy_nursery_intake.csv": (
        "nursery_intake", ["Placement_Date"]
    ),
    "2025_dummy_barn_to_barn_pig_flow.csv": (
        "pig_flow", ["Movement_Date"]
    ),
    "2025_dummy_barn_environmental_utilities.csv": (
        "barn_environment", ["Date"]
    ),
    "2025_dummy_packer_settlement.csv": (
        "packer_settlement", ["Kill_Date"]
    ),
    "2025_dummy_hog_hedging_aligned_to_nursery.csv": (
        "hedging", ["Trade_Date"]
    ),
    "2025_swine_accounting_dummy_.csv": (
        "accounting", ["Date"]
    ),
}

# Market files: filename → (table_name, file_type, date_column, sheet_name)
MARKET_FILES = {
    "HEM25_HISTORY.xlsx": ("hog_futures_hem25", "excel", "Date", 0),
    "ZCN25.xlsx": ("corn_futures_zcn25", "excel", "Date", 0),
    "Pork_Primal_Values.csv": ("pork_primal", "csv", "report_date", None),
}