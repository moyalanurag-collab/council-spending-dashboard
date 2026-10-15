"""Execute the numbered SQL scripts in sql/ against the SQLite database, in order."""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "council_spending.db"
SQL_DIR = ROOT / "sql"
PIPELINE = ["01_clean_staging.sql", "02_reference_data.sql", "03_model.sql", "04_data_quality.sql"]


def run(db_path: Path = DB_PATH, sql_dir: Path = SQL_DIR, scripts=PIPELINE) -> None:
    with sqlite3.connect(db_path) as con:
        for name in scripts:
            con.executescript((sql_dir / name).read_text(encoding="utf-8"))
            print(f"  ran {name}")


if __name__ == "__main__":
    if not DB_PATH.exists():
        sys.exit("Database not found - run `python src/ingest.py` first.")
    run()
