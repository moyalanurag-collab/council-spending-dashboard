-- =====================================================================================
-- 04_data_quality.sql
-- Purpose : data-quality scorecard + drill-through detail tables (consumed by the
--           "Data Quality" page of the Power BI report).
-- Creates : dq_results                       one row per check
--           dq_possible_duplicate_payments   lines flagged by DQ17
--           dq_supplier_id_conflicts         supplier IDs shared by different suppliers (DQ12)
--           dq_multi_id_suppliers            suppliers holding several IDs (DQ13)
--
-- result column:  PASS  = nothing found
--                 WARN  = issue found but handled / needs analyst awareness
--                 FAIL  = pipeline integrity problem (must be zero)
--                 INFO  = descriptive profile, not an error
-- =====================================================================================

DROP TABLE IF EXISTS dq_results;
CREATE TABLE dq_results (
    check_id        TEXT PRIMARY KEY,
    dimension       TEXT NOT NULL,      -- Completeness | Validity | Uniqueness | Consistency | Reconciliation | Coverage | Profile
    check_name      TEXT NOT NULL,
    rows_affected   INTEGER NOT NULL,
    rows_total      INTEGER NOT NULL,
    pct_affected    REAL,
    amount_affected REAL,
    result          TEXT NOT NULL,
    how_handled     TEXT
);

-- ---- helpers -------------------------------------------------------------------------
DROP TABLE IF EXISTS tmp_counts;
CREATE TEMP TABLE tmp_counts AS
SELECT (SELECT COUNT(*) FROM stg_payments)  AS staged_rows,
       (SELECT COUNT(*) FROM fact_payments) AS fact_rows,
       (SELECT COUNT(*) FROM excluded_rows) AS excluded_rows,
       (SELECT SUM(amount) FROM fact_payments) AS fact_amount;

-- ---- Reconciliation ------------------------------------------------------------------
INSERT INTO dq_results
SELECT 'DQ01','Reconciliation','Staged rows = fact rows + excluded rows',
       ABS(staged_rows - fact_rows - excluded_rows), staged_rows,
       100.0 * ABS(staged_rows - fact_rows - excluded_rows) / staged_rows, NULL,
       CASE WHEN staged_rows = fact_rows + excluded_rows THEN 'PASS' ELSE 'FAIL' END,
       'Row-count invariant: nothing is silently dropped'
FROM tmp_counts;

INSERT INTO dq_results
SELECT 'DQ02','Reconciliation','Fact total (GBP) = cleaned source total (GBP)',
       CASE WHEN ABS(c.fact_amount - o.amt) > 0.01 THEN 1 ELSE 0 END, 1, NULL, ROUND(ABS(c.fact_amount - o.amt), 2),
       CASE WHEN ABS(c.fact_amount - o.amt) <= 0.01 THEN 'PASS' ELSE 'FAIL' END,
       'Joins to dimensions neither lose nor multiply rows/value'
FROM tmp_counts c, (SELECT SUM(amount) AS amt FROM int_payments_ranked WHERE dup_rank = 1) o;

-- ---- Completeness / validity (rows excluded from the fact table) ---------------------
INSERT INTO dq_results
SELECT 'DQ03','Completeness','Completely blank rows in source files',
       COUNT(*), (SELECT staged_rows FROM tmp_counts), 100.0 * COUNT(*) / (SELECT staged_rows FROM tmp_counts), 0,
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END, 'Excluded (reason BLANK_ROW)'
FROM excluded_rows WHERE exclusion_reason = 'BLANK_ROW';

INSERT INTO dq_results
SELECT 'DQ04','Validity','Rows with missing / non-numeric amount',
       COUNT(*), (SELECT staged_rows FROM tmp_counts), 100.0 * COUNT(*) / (SELECT staged_rows FROM tmp_counts), 0,
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END, 'Excluded (reason INVALID_AMOUNT)'
FROM excluded_rows WHERE exclusion_reason = 'INVALID_AMOUNT';

INSERT INTO dq_results
SELECT 'DQ05','Validity','Rows with unparseable payment date',
       COUNT(*), (SELECT staged_rows FROM tmp_counts), 100.0 * COUNT(*) / (SELECT staged_rows FROM tmp_counts), 0,
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END, 'Excluded (reason INVALID_DATE)'
FROM excluded_rows WHERE exclusion_reason = 'INVALID_DATE';

INSERT INTO dq_results
SELECT 'DQ06','Completeness','Rows with no supplier name',
       COUNT(*), (SELECT staged_rows FROM tmp_counts), 100.0 * COUNT(*) / (SELECT staged_rows FROM tmp_counts), 0,
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END, 'Excluded (reason MISSING_SUPPLIER)'
FROM excluded_rows WHERE exclusion_reason = 'MISSING_SUPPLIER';

INSERT INTO dq_results
SELECT 'DQ07','Uniqueness','Exact duplicate rows (all business columns identical)',
       COUNT(*), (SELECT staged_rows FROM tmp_counts), 100.0 * COUNT(*) / (SELECT staged_rows FROM tmp_counts), ROUND(COALESCE(SUM(amount),0), 2),
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END, 'Earliest copy kept, later copies excluded (reason DUPLICATE_ROW)'
FROM excluded_rows WHERE exclusion_reason = 'DUPLICATE_ROW';

INSERT INTO dq_results
SELECT 'DQ08','Completeness','Valid payments missing a source Supplier ID',
       COUNT(*), (SELECT fact_rows FROM tmp_counts), 100.0 * COUNT(*) / (SELECT fact_rows FROM tmp_counts), ROUND(COALESCE(SUM(amount),0), 2),
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END, 'Kept; supplier identity falls back to the normalised name'
FROM fact_payments WHERE source_supplier_id IS NULL;

-- ---- Timeliness / coverage -----------------------------------------------------------
INSERT INTO dq_results
SELECT 'DQ09','Validity','Payment date falls outside the month of the file it was published in',
       COUNT(*), (SELECT fact_rows FROM tmp_counts), 100.0 * COUNT(*) / (SELECT fact_rows FROM tmp_counts), ROUND(COALESCE(SUM(f.amount),0), 2),
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END, 'Kept; report period = payment date, not file month'
FROM fact_payments f JOIN dim_date d ON d.date_key = f.date_key
WHERE d.year_month <> f.source_period;

INSERT INTO dq_results
WITH months AS (SELECT DISTINCT year_month FROM dim_date),
     covered AS (SELECT DISTINCT year_month FROM fact_payments f JOIN dim_date d ON d.date_key = f.date_key)
SELECT 'DQ10','Coverage','Calendar months with no payments between first and last month',
       (SELECT COUNT(*) FROM months WHERE year_month NOT IN (SELECT year_month FROM covered)),
       (SELECT COUNT(*) FROM months), NULL, NULL,
       CASE WHEN (SELECT COUNT(*) FROM months WHERE year_month NOT IN (SELECT year_month FROM covered)) = 0 THEN 'PASS' ELSE 'FAIL' END,
       'A missing monthly file would show here';

-- ---- Consistency / master data ------------------------------------------------------
INSERT INTO dq_results
SELECT 'DQ11','Consistency','Suppliers whose name appears in 2+ spellings (merged)',
       COUNT(*), (SELECT COUNT(*) FROM dim_supplier WHERE is_redacted = 0), 100.0 * COUNT(*) / (SELECT COUNT(*) FROM dim_supplier WHERE is_redacted = 0), NULL,
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END, 'Merged on normalised name (case, punctuation, LTD/LIMITED/PLC ...)'
FROM dim_supplier WHERE is_redacted = 0 AND name_variants > 1;

DROP TABLE IF EXISTS dq_supplier_id_conflicts;
CREATE TABLE dq_supplier_id_conflicts AS
SELECT supplier_id AS source_supplier_id,
       COUNT(DISTINCT supplier_entity_key)  AS distinct_suppliers,
       GROUP_CONCAT(DISTINCT supplier_name_raw) AS names_using_id,
       COUNT(*) AS payment_lines,
       ROUND(SUM(amount), 2) AS total_amount
FROM int_payments_ok
WHERE is_redacted = 0 AND supplier_id IS NOT NULL
GROUP BY supplier_id
HAVING COUNT(DISTINCT supplier_entity_key) > 1;

INSERT INTO dq_results
SELECT 'DQ12','Consistency','Supplier IDs reused by different suppliers',
       COUNT(*), (SELECT COUNT(DISTINCT source_supplier_id) FROM fact_payments), 100.0 * COUNT(*) / (SELECT COUNT(DISTINCT source_supplier_id) FROM fact_payments),
       ROUND(COALESCE(SUM(total_amount),0), 2),
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END, 'Not merged - supplier identity is name-based; listed in dq_supplier_id_conflicts for the council to fix'
FROM dq_supplier_id_conflicts;

DROP TABLE IF EXISTS dq_multi_id_suppliers;
CREATE TABLE dq_multi_id_suppliers AS
SELECT supplier_key, supplier_name, supplier_id_count, supplier_ids,
       (SELECT ROUND(SUM(amount), 2) FROM fact_payments f WHERE f.supplier_key = s.supplier_key) AS total_amount
FROM dim_supplier s
WHERE is_redacted = 0 AND supplier_id_count > 1;

INSERT INTO dq_results
SELECT 'DQ13','Uniqueness','Suppliers registered under 2+ Supplier IDs (duplicate vendor records)',
       COUNT(*), (SELECT COUNT(*) FROM dim_supplier WHERE is_redacted = 0), 100.0 * COUNT(*) / (SELECT COUNT(*) FROM dim_supplier WHERE is_redacted = 0),
       ROUND(COALESCE(SUM(total_amount),0), 2),
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END, 'Combined into one supplier_key; listed in dq_multi_id_suppliers'
FROM dq_multi_id_suppliers;

INSERT INTO dq_results
SELECT 'DQ14','Consistency','Lines with a spend category not in ref_spend_category',
       COUNT(*), (SELECT fact_rows FROM tmp_counts), 100.0 * COUNT(*) / (SELECT fact_rows FROM tmp_counts), ROUND(COALESCE(SUM(f.amount),0), 2),
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END, 'Shown as theme "Unmapped" - add the label to sql/02_reference_data.sql'
FROM fact_payments f JOIN dim_spend_category c ON c.spend_category_key = f.spend_category_key
WHERE c.spend_theme = 'Unmapped';

INSERT INTO dq_results
SELECT 'DQ15','Consistency','Lines with a directorate not in ref_department',
       COUNT(*), (SELECT fact_rows FROM tmp_counts), 100.0 * COUNT(*) / (SELECT fact_rows FROM tmp_counts), ROUND(COALESCE(SUM(amount),0), 2),
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END, 'Shown as expenditure_type "Unmapped" - add to sql/02_reference_data.sql'
FROM fact_payments WHERE expenditure_type = 'Unmapped';

INSERT INTO dq_results
SELECT 'DQ16','Consistency','Distinct raw department labels merged into fewer clean directorates',
       (SELECT COUNT(DISTINCT department_raw) FROM int_payments_ok) - (SELECT COUNT(*) FROM dim_directorate),
       (SELECT COUNT(DISTINCT department_raw) FROM int_payments_ok), NULL, NULL,
       'INFO', 'Capital / revenue prefixes split out into expenditure_type; &/AND variants unified';

-- ---- Business-rule checks (analyst review) ------------------------------------------
DROP TABLE IF EXISTS dq_possible_duplicate_payments;
CREATE TABLE dq_possible_duplicate_payments AS
SELECT f.payment_id, s.supplier_name, d.date AS payment_date, f.amount,
       f.transaction_number, f.source_file, f.source_row,
       COUNT(*) OVER (PARTITION BY f.supplier_key, f.date_key, f.amount) AS lines_in_group
FROM fact_payments f
JOIN dim_supplier s ON s.supplier_key = f.supplier_key
JOIN dim_date d     ON d.date_key = f.date_key
WHERE f.is_possible_duplicate_payment = 1;

INSERT INTO dq_results
SELECT 'DQ17','Uniqueness','Possible duplicate payments (same supplier, day and amount, >= GBP 1,000)',
       COUNT(*), (SELECT fact_rows FROM tmp_counts), 100.0 * COUNT(*) / (SELECT fact_rows FROM tmp_counts), ROUND(COALESCE(SUM(amount),0), 2),
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END, 'Kept; flagged is_possible_duplicate_payment. Many are legitimate batch payments - review list in dq_possible_duplicate_payments'
FROM dq_possible_duplicate_payments;

INSERT INTO dq_results
SELECT 'DQ18','Validity','Zero-value payment lines',
       COUNT(*), (SELECT fact_rows FROM tmp_counts), 100.0 * COUNT(*) / (SELECT fact_rows FROM tmp_counts), 0,
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END, 'Kept'
FROM fact_payments WHERE amount = 0;

-- ---- Profile (descriptive) -----------------------------------------------------------
INSERT INTO dq_results
SELECT 'DQ19','Profile','Credit notes / refunds (negative amounts)',
       COUNT(*), (SELECT fact_rows FROM tmp_counts), 100.0 * COUNT(*) / (SELECT fact_rows FROM tmp_counts), ROUND(COALESCE(SUM(amount),0), 2),
       'INFO', 'Kept - they reduce net spend; flagged is_credit_note'
FROM fact_payments WHERE is_credit_note = 1;

INSERT INTO dq_results
SELECT 'DQ20','Profile','Lines under GBP 500 (threshold applies to the invoice, not each line)',
       COUNT(*), (SELECT fact_rows FROM tmp_counts), 100.0 * COUNT(*) / (SELECT fact_rows FROM tmp_counts), ROUND(COALESCE(SUM(amount),0), 2),
       'INFO', 'Kept; flagged is_below_threshold'
FROM fact_payments WHERE is_below_threshold = 1 AND is_credit_note = 0;

INSERT INTO dq_results
SELECT 'DQ21','Profile','Payments to redacted (personal-data) payees',
       COUNT(*), (SELECT fact_rows FROM tmp_counts), 100.0 * COUNT(*) / (SELECT fact_rows FROM tmp_counts), ROUND(COALESCE(SUM(f.amount),0), 2),
       'INFO', 'Each redacted payee ID kept separate; excluded from supplier rankings via is_redacted'
FROM fact_payments f JOIN dim_supplier s ON s.supplier_key = f.supplier_key WHERE s.is_redacted = 1;

INSERT INTO dq_results
SELECT 'DQ22','Profile','Suppliers the sector heuristic could not classify',
       COUNT(*), (SELECT COUNT(*) FROM dim_supplier), 100.0 * COUNT(*) / (SELECT COUNT(*) FROM dim_supplier), NULL,
       'INFO', 'supplier_type = "Other / unclassified" (mostly individuals, sole traders, surgeries)'
FROM dim_supplier WHERE supplier_type = 'Other / unclassified';

UPDATE dq_results SET pct_affected = ROUND(pct_affected, 3);
