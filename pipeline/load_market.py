"""Load market reference files into SQLite."""
import pandas as pd
from sqlalchemy import create_engine
from pipeline.config import RAW_MARKET, DB_PATH, MARKET_FILES


def load_market_files():
    """Load all market reference files into the SQLite database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{DB_PATH}")

    summary = []
    for filename, (table_name, file_type, date_col, sheet) in MARKET_FILES.items():
        path = RAW_MARKET / filename
        if not path.exists():
            print(f"  [skip] {filename} — not found")
            continue

        if file_type == "csv":
            df = pd.read_csv(path)
        else:  # excel
            # Hog/corn futures files have a quirky header — skip first row,
            # use second row as headers
            df = pd.read_excel(path, sheet_name=sheet, header=1)

        # Drop fully-empty columns and rows
        df = df.dropna(axis=1, how="all").dropna(how="all")

        # Parse the date column
        if date_col and date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")

        # Normalize column names: strip and lowercase-with-underscores
        df.columns = [
            str(c).strip().replace(" ", "_").replace("/", "_").lower()
            for c in df.columns
        ]

        df.to_sql(table_name, engine, if_exists="replace", index=False)
        summary.append((table_name, len(df), len(df.columns)))
        print(f"  [ok]   {filename:30s} → {table_name:25s} ({len(df):,} rows)")

    return summary


if __name__ == "__main__":
    print("Loading market files...")
    load_market_files()
    print(f"\nDatabase: {DB_PATH}")