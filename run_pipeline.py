"""Run the whole pipeline end to end:

    python run_pipeline.py              # use files already in data/raw/
    python run_pipeline.py --download   # fetch the latest files first
    python run_pipeline.py --skip-ml    # skip the optional classifier
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def step(title: str, script: str, *args: str) -> None:
    print(f"\n== {title}")
    subprocess.run([sys.executable, str(ROOT / "src" / script), *args], check=True, cwd=ROOT)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true", help="download the latest monthly files first")
    ap.add_argument("--skip-ml", action="store_true", help="skip the optional text-classification step")
    args = ap.parse_args()

    if args.download:
        step("1. Download open data", "download.py")
    step("2. Stage raw files (CSV + Excel) into SQLite", "ingest.py")
    step("3. SQL: clean, model, data-quality checks", "run_sql.py")
    step("4. Fuzzy supplier-match candidates", "supplier_matching.py")
    if not args.skip_ml:
        step("5. Text classification (optional extra)", "classify.py")
    step("6. Export CSVs for Power BI", "export.py")
    step("7. Findings + charts", "findings.py")
    print("\nDone. Power BI inputs are in data/processed/.")


if __name__ == "__main__":
    main()
