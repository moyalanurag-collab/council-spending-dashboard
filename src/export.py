"""Export the star schema + data-quality tables from SQLite to UTF-8 CSVs for Power BI."""
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "council_spending.db"
OUT_DIR = ROOT / "data" / "processed"

TABLES = [
    "fact_payments", "dim_date", "dim_supplier", "dim_directorate", "dim_service_area",
    "dim_spend_category", "dim_purpose",
    "dq_results", "dq_possible_duplicate_payments", "dq_supplier_id_conflicts", "dq_multi_id_suppliers",
    "excluded_rows",
]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        for t in TABLES:
            df = pd.read_sql(f"SELECT * FROM {t}", con)
            df.to_csv(OUT_DIR / f"{t}.csv", index=False, encoding="utf-8")
            print(f"  {t:34s} {len(df):>8,} rows")


if __name__ == "__main__":
    main()
