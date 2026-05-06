"""Load producer CSV files into SQLite."""
import pandas as pd
from sqlalchemy import create_engine
from pipeline.config import RAW_PRODUCER, DB_PATH, PRODUCER_FILES


def load_producer_files():
    """Load all producer CSVs into the SQLite database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{DB_PATH}")

    summary = []
    for filename, (table_name, date_cols) in PRODUCER_FILES.items():
        path = RAW_PRODUCER / filename
        if not path.exists():
            print(f"  [skip] {filename} — not found")
            continue

        df = pd.read_csv(path)

        # Parse date columns
        for col in date_cols:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")

        # Strip whitespace from string columns
        for col in df.select_dtypes(include="object").columns:
            df[col] = df[col].str.strip() if df[col].dtype == "object" else df[col]

        df.to_sql(table_name, engine, if_exists="replace", index=False)
        summary.append((table_name, len(df), len(df.columns)))
        print(f"  [ok]   {filename:55s} → {table_name:25s} ({len(df):,} rows)")

    return summary


if __name__ == "__main__":
    print("Loading producer files...")
    load_producer_files()
    print(f"\nDatabase: {DB_PATH}")