"""Fuzzy supplier-matching: find *probable* duplicate supplier records that exact
normalisation (sql/01_clean_staging.sql) cannot catch, e.g. 'SUNRO PROPERTIES' vs 'SUNRO PROPETIES'.

Candidates are REPORTED, never merged automatically: a data analyst (or the council's
procurement team) should confirm before consolidating vendor records.

Blocking on the first 5 characters of the normalised key keeps the comparison cheap.
"""
import sqlite3
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "council_spending.db"
OUT_DIR = ROOT / "data" / "processed"
THRESHOLD = 92          # rapidfuzz ratio (0-100) on the space-less normalised name

QUERY = """
SELECT s.supplier_key, s.supplier_name, s.supplier_ids,
       REPLACE(UPPER(s.supplier_entity_key), ' ', '') AS key,
       ROUND(SUM(f.amount), 2) AS total_amount
FROM dim_supplier s JOIN fact_payments f ON f.supplier_key = s.supplier_key
WHERE s.is_redacted = 0
GROUP BY s.supplier_key
"""


def main() -> None:
    with sqlite3.connect(DB_PATH) as con:
        sup = pd.read_sql(QUERY, con)
    blocks = defaultdict(list)
    for r in sup.itertuples():
        blocks[r.key[:5]].append(r)

    rows = []
    for members in blocks.values():
        for a, b in combinations(members, 2):
            score = fuzz.ratio(a.key, b.key)
            if score >= THRESHOLD:
                ids_a, ids_b = set(str(a.supplier_ids).split(",")), set(str(b.supplier_ids).split(","))
                rows.append({
                    "supplier_key_a": a.supplier_key, "supplier_a": a.supplier_name, "total_a": a.total_amount,
                    "supplier_key_b": b.supplier_key, "supplier_b": b.supplier_name, "total_b": b.total_amount,
                    "similarity": round(score, 1),
                    "shares_supplier_id": int(bool(ids_a & ids_b)),
                })
    out = pd.DataFrame(rows).sort_values(["shares_supplier_id", "similarity"], ascending=False) if rows else pd.DataFrame(
        columns=["supplier_key_a", "supplier_a", "total_a", "supplier_key_b", "supplier_b", "total_b", "similarity", "shares_supplier_id"])
    with sqlite3.connect(DB_PATH) as con:
        out.to_sql("dq_supplier_match_candidates", con, if_exists="replace", index=False)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_DIR / "dq_supplier_match_candidates.csv", index=False)
    print(f"{len(out)} candidate supplier pairs (similarity >= {THRESHOLD}); "
          f"{int(out['shares_supplier_id'].sum()) if len(out) else 0} also share a Supplier ID")


if __name__ == "__main__":
    main()
