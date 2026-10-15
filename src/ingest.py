"""Stage every monthly file in data/raw/ into one SQLite table (stg_payments), all columns as TEXT.

No cleaning happens here on purpose: staging is a faithful copy of the source, so the SQL
layer (sql/) is the single, reviewable place where every transformation is defined.
Handles both CSV and Excel releases (Excel files contain a hidden '_options' sheet that is skipped).
"""
import json
import re
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "council_spending.db"
CONFIG = json.loads((ROOT / "config" / "source_map.json").read_text(encoding="utf-8"))

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def period_from_filename(name: str) -> str:
    """'Invoices Over £500 Sept 2025-WfswPI.csv' -> '2025-09'."""
    n = name.lower()
    year = re.search(r"(20\d{2})", n).group(1)
    month = next(i for k, i in MONTHS.items() if re.search(rf"\b{k}", n))
    return f"{year}-{month:02d}"


def read_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False)
    else:
        sheets = pd.read_excel(path, sheet_name=None, dtype=str, keep_default_na=False)
        df = next(d for n, d in sheets.items() if not n.startswith("_"))
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns=CONFIG["columns"])
    for col in CONFIG["columns"].values():  # tolerate councils that do not publish every field
        if col not in df.columns:
            df[col] = ""
    return df[list(CONFIG["columns"].values())]


def main() -> None:
    files = sorted(p for p in RAW_DIR.iterdir() if p.suffix.lower() in {".csv", ".xlsx"})
    if not files:
        raise SystemExit("No files in data/raw - run `python src/download.py` first.")
    frames = []
    for p in files:
        df = read_file(p)
        df.insert(0, "source_row", range(2, len(df) + 2))  # 1-based incl. header, matches the spreadsheet row
        df.insert(0, "source_period", period_from_filename(p.name))
        df.insert(0, "source_file", p.name)
        frames.append(df)
        print(f"  {p.name[:44]:44s} {len(df):>6,} rows -> {frames[-1]['source_period'].iloc[0]}")
    all_rows = pd.concat(frames, ignore_index=True)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        all_rows.to_sql("stg_payments", con, if_exists="replace", index=False)
    print(f"Staged {len(all_rows):,} rows from {len(files)} files into {DB_PATH.name}")


if __name__ == "__main__":
    main()
