"""Run all loaders. This is the main entry point for Phase 1."""
from pipeline.load_producer import load_producer_files
from pipeline.load_market import load_market_files
from pipeline.config import DB_PATH


def main():
    print("=" * 60)
    print("ProAg Track 2 — Phase 1: Loading raw data")
    print("=" * 60)

    print("\n[1/2] Producer files")
    producer_summary = load_producer_files()

    print("\n[2/2] Market files")
    market_summary = load_market_files()

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    total_rows = 0
    for name, rows, cols in producer_summary + market_summary:
        print(f"  {name:25s}  {rows:>8,} rows  {cols:>3} cols")
        total_rows += rows
    print(f"\n  Total: {total_rows:,} rows across {len(producer_summary) + len(market_summary)} tables")
    print(f"  Database: {DB_PATH}")


if __name__ == "__main__":
    main()