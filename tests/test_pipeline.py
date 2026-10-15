"""Unit tests for the SQL pipeline, run against a tiny synthetic staging table (no downloads needed).

    pytest -q
"""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import run_sql  # noqa: E402
from ingest import period_from_filename  # noqa: E402

COLS = ["source_file", "source_period", "source_row", "department", "service_area", "supplier_name_raw",
        "supplier_id", "payment_date", "transaction_number", "amount", "irrecoverable_vat", "purpose", "spend_category"]


def row(**kw):
    base = dict(source_file="a.csv", source_period="2025-04", source_row=2, department="RESOURCES",
                service_area="Central Services", supplier_name_raw="ACME LTD", supplier_id="1",
                payment_date="05/04/2025", transaction_number="100", amount="1,000.50",
                irrecoverable_vat="0.00", purpose="SERVICES/FEES",
                spend_category="Suppliers - General Goods & Services")
    base.update(kw)
    return tuple(base[c] for c in COLS)


@pytest.fixture()
def db(tmp_path):
    rows = [
        row(),                                                                                   # 1 baseline
        row(supplier_name_raw="Acme Limited.", transaction_number="101", payment_date="2025-04-06 00:00:00"),  # 2 name variant, Excel date
        row(supplier_name_raw="THE ACME LTD", transaction_number="102", amount="1,100.00"),                          # 3 'THE' prefix
        row(transaction_number="100"),                                                           # 4 exact duplicate of 1
        row(supplier_name_raw="REDACTED PERSONAL DATA", supplier_id="900", transaction_number="200"),  # 5 redacted A
        row(supplier_name_raw="REDACTED PERSONAL DATA", supplier_id="901", transaction_number="201"),  # 6 redacted B
        row(department="", service_area="", supplier_name_raw="", supplier_id="", payment_date="",
            transaction_number="", amount="", irrecoverable_vat="", purpose="", spend_category=""),   # 7 blank
        row(supplier_name_raw="BADAMT LTD", supplier_id="3", amount="n/a", transaction_number="300"),  # 8 invalid amount
        row(supplier_name_raw="BADDATE LTD", supplier_id="4", payment_date="31/02/2025", transaction_number="301"),  # 9 invalid date
        row(supplier_name_raw="CREDIT CO", supplier_id="5", amount="-750.00", transaction_number="400"),  # 10 credit note
        row(supplier_name_raw="UNMAPPED CO", supplier_id="6", spend_category="Brand New Category", department="NEW DEPT", transaction_number="500"),  # 11
        row(supplier_name_raw="TWIN CO", supplier_id="7", amount="2000", transaction_number="600"),   # 12 same supplier/day/amount ...
        row(supplier_name_raw="TWIN CO", supplier_id="7", amount="2000", transaction_number="601"),   # 13 ... different txn -> possible dup payment
    ]
    path = tmp_path / "t.db"
    con = sqlite3.connect(path)
    con.execute(f"CREATE TABLE stg_payments ({', '.join(c + ' TEXT' for c in COLS)})")
    con.executemany(f"INSERT INTO stg_payments VALUES ({','.join('?' * len(COLS))})", rows)
    con.commit()
    con.close()
    run_sql.run(db_path=path, sql_dir=run_sql.SQL_DIR)
    con = sqlite3.connect(path)
    yield con
    con.close()


def q(con, sql):
    return con.execute(sql).fetchall()


def test_row_reconciliation_holds(db):
    staged, fact, excluded = (q(db, f"SELECT COUNT(*) FROM {t}")[0][0] for t in ("stg_payments", "fact_payments", "excluded_rows"))
    assert staged == fact + excluded == 13


def test_exclusion_reasons(db):
    reasons = dict(q(db, "SELECT exclusion_reason, COUNT(*) FROM excluded_rows GROUP BY 1"))
    assert reasons == {"BLANK_ROW": 1, "INVALID_AMOUNT": 1, "INVALID_DATE": 1, "DUPLICATE_ROW": 1}


def test_name_variants_merge_into_one_supplier(db):
    # 'ACME LTD', 'Acme Limited.', 'THE ACME LTD' -> one supplier
    assert q(db, "SELECT COUNT(*) FROM dim_supplier WHERE supplier_entity_key = 'ACME'")[0][0] == 1
    assert q(db, "SELECT name_variants FROM dim_supplier WHERE supplier_entity_key = 'ACME'")[0][0] == 3


def test_redacted_payees_are_not_merged(db):
    assert q(db, "SELECT COUNT(*) FROM dim_supplier WHERE is_redacted = 1")[0][0] == 2


def test_both_date_formats_parse(db):
    dates = {r[0] for r in q(db, "SELECT d.date FROM fact_payments f JOIN dim_date d ON d.date_key = f.date_key JOIN dim_supplier s ON s.supplier_key=f.supplier_key WHERE s.supplier_entity_key='ACME'")}
    assert dates == {"2025-04-05", "2025-04-06"}


def test_thousands_separator_amount_parsed(db):
    assert q(db, "SELECT amount FROM fact_payments WHERE transaction_number = '100'")[0][0] == 1000.50


def test_credit_note_flag(db):
    assert q(db, "SELECT is_credit_note, amount FROM fact_payments WHERE transaction_number = '400'")[0] == (1, -750.0)


def test_unmapped_values_are_kept_and_reported(db):
    assert q(db, "SELECT spend_theme FROM dim_spend_category WHERE spend_category = 'Brand New Category'")[0][0] == "Unmapped"
    results = dict(q(db, "SELECT check_id, result FROM dq_results"))
    assert results["DQ14"] == "WARN" and results["DQ15"] == "WARN"


def test_possible_duplicate_payment_flag(db):
    assert q(db, "SELECT COUNT(*) FROM fact_payments WHERE is_possible_duplicate_payment = 1")[0][0] == 2


def test_integrity_checks_pass(db):
    results = dict(q(db, "SELECT check_id, result FROM dq_results"))
    assert results["DQ01"] == "PASS" and results["DQ02"] == "PASS"


def test_fact_keys_all_resolve(db):
    for dim, key in [("dim_supplier", "supplier_key"), ("dim_date", "date_key"), ("dim_directorate", "directorate_key"),
                     ("dim_service_area", "service_area_key"), ("dim_spend_category", "spend_category_key"),
                     ("dim_purpose", "purpose_key")]:
        assert q(db, f"SELECT COUNT(*) FROM fact_payments f LEFT JOIN {dim} d ON d.{key}=f.{key} WHERE d.{key} IS NULL")[0][0] == 0


@pytest.mark.parametrize("name,expected", [
    ("Invoices Over £500 Sept 2025-WfswPI.csv", "2025-09"),
    ("Invoices Over 500 April 2026-PgLmul.csv", "2026-04"),
    ("Invoices Over £500 December 2025-tSEnnB.csv", "2025-12"),
    ("Invoices Over £500 Jan 2026-DqZIWo.xlsx", "2026-01"),
])
def test_period_from_filename(name, expected):
    assert period_from_filename(name) == expected
