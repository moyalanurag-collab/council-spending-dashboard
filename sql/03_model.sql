-- =====================================================================================
-- 03_model.sql
-- Purpose : build the analytical star schema that Power BI consumes.
--
--                         dim_date ─┐
--                    dim_supplier ──┤
--                  dim_directorate ─┼── fact_payments
--                 dim_service_area ─┤
--              dim_spend_category ──┤
--                     dim_purpose ──┘
--
-- Reads   : int_payments, int_supplier_names, ref_* tables
-- Creates : excluded_rows (audit trail), dim_*, fact_payments
-- =====================================================================================

-- -------------------------------------------------------------------------------------
-- 1. Remove exact duplicate lines.
--    A duplicate = every business column identical (same transaction number, supplier, date,
--    amount, purpose ...). The earliest staged row is kept, later copies are excluded.
-- -------------------------------------------------------------------------------------
DROP TABLE IF EXISTS int_payments_ranked;
CREATE TABLE int_payments_ranked AS
SELECT
    p.*,
    ROW_NUMBER() OVER (
        PARTITION BY department_raw, service_area_raw, supplier_name_raw, supplier_id, payment_date,
                     transaction_number, amount, irrecoverable_vat, purpose_raw, spend_category_raw
        ORDER BY stg_id
    ) AS dup_rank
FROM int_payments p
WHERE load_status = 'OK';

-- -------------------------------------------------------------------------------------
-- 2. Audit trail: every staged row that is NOT loaded, with the reason.
--    Invariant (tested in 04_data_quality.sql): staged rows = fact rows + excluded rows.
-- -------------------------------------------------------------------------------------
DROP TABLE IF EXISTS excluded_rows;
CREATE TABLE excluded_rows AS
SELECT stg_id, source_file, source_period, source_row, load_status AS exclusion_reason, amount
FROM int_payments
WHERE load_status <> 'OK'
UNION ALL
SELECT stg_id, source_file, source_period, source_row, 'DUPLICATE_ROW', amount
FROM int_payments_ranked
WHERE dup_rank > 1;

-- -------------------------------------------------------------------------------------
-- 3. Clean base set used by every dimension and the fact table.
--    supplier_entity_key is the identity of a supplier:
--      * normalised name (see 01_clean_staging.sql) for ordinary suppliers
--      * 'REDACTED|<supplier_id>' for GDPR-redacted payees, which must NOT be merged by name
-- -------------------------------------------------------------------------------------
DROP TABLE IF EXISTS int_payments_ok;
CREATE TABLE int_payments_ok AS
SELECT
    r.*,
    n.is_redacted,
    CASE WHEN n.is_redacted = 1 THEN 'REDACTED|' || COALESCE(r.supplier_id, '?')
         ELSE n.supplier_name_key END AS supplier_entity_key
FROM int_payments_ranked r
JOIN int_supplier_names n ON n.supplier_name_raw = r.supplier_name_raw
WHERE r.dup_rank = 1;

CREATE INDEX idx_ok_entity ON int_payments_ok(supplier_entity_key);

-- -------------------------------------------------------------------------------------
-- 4. dim_supplier  (one row per real-world supplier)
--    canonical name = most frequent raw spelling (ties -> longest, then alphabetical)
-- -------------------------------------------------------------------------------------
DROP TABLE IF EXISTS dim_supplier;
CREATE TABLE dim_supplier AS
WITH name_counts AS (
    SELECT supplier_entity_key, supplier_name_raw, COUNT(*) AS n
    FROM int_payments_ok GROUP BY supplier_entity_key, supplier_name_raw
),
canonical AS (
    SELECT supplier_entity_key, supplier_name_raw AS canonical_name
    FROM (
        SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY supplier_entity_key
                    ORDER BY n DESC, LENGTH(supplier_name_raw) DESC, supplier_name_raw) AS rk
        FROM name_counts)
    WHERE rk = 1
),
agg AS (
    SELECT supplier_entity_key,
           MAX(is_redacted)                      AS is_redacted,
           COUNT(DISTINCT supplier_name_raw)     AS name_variants,
           COUNT(DISTINCT supplier_id)           AS supplier_id_count,
           GROUP_CONCAT(DISTINCT supplier_id)    AS supplier_ids,
           MIN(payment_date)                     AS first_payment_date,
           MAX(payment_date)                     AS last_payment_date
    FROM int_payments_ok GROUP BY supplier_entity_key
)
SELECT
    ROW_NUMBER() OVER (ORDER BY a.supplier_entity_key)                         AS supplier_key,
    a.supplier_entity_key,
    CASE WHEN a.is_redacted = 1 THEN 'REDACTED PERSONAL DATA' ELSE c.canonical_name END AS supplier_name,
    a.is_redacted,
    -- Heuristic sector classification from the name (reviewable; unmatched -> 'Other / unclassified')
    CASE
        WHEN a.is_redacted = 1 THEN 'Individual (redacted)'
        WHEN ' ' || UPPER(c.canonical_name) || ' ' LIKE '% COUNCIL %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% LONDON BOROUGH %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% ROYAL BOROUGH %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% NHS %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% ICB %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% HOSPITAL %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% POLICE %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% FIRE AUTHORITY %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% TRANSPORT FOR LONDON %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% MAYOR OF LONDON %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% GREATER LONDON AUTHORITY %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% HMRC %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% HM REVENUE %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% DEPARTMENT FOR %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% ENVIRONMENT AGENCY %'                     THEN 'Public sector'
        WHEN ' ' || UPPER(c.canonical_name) || ' ' LIKE '% SCHOOL %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% COLLEGE %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% UNIVERSITY %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% ACADEMY %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% NURSERY %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% PRIMARY %'                                THEN 'Education'
        WHEN ' ' || UPPER(c.canonical_name) || ' ' LIKE '% CHARITY %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% FOUNDATION %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% TRUST %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% ASSOCIATION %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% SOCIETY %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% CHURCH %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% COMMUNITY %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% CIC %'                                    THEN 'Charity / voluntary'
        WHEN ' ' || UPPER(c.canonical_name) || ' ' LIKE '% LTD %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% LTD. %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% LIMITED %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% PLC %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% LLP %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% LLC %'
          OR ' ' || UPPER(c.canonical_name) || ' ' LIKE '% INC %'                                    THEN 'Private company'
        ELSE 'Other / unclassified'
    END                                                                          AS supplier_type,
    a.name_variants,
    a.supplier_id_count,
    a.supplier_ids,
    a.first_payment_date,
    a.last_payment_date
FROM agg a
JOIN canonical c ON c.supplier_entity_key = a.supplier_entity_key;

CREATE UNIQUE INDEX idx_dim_supplier_entity ON dim_supplier(supplier_entity_key);

-- -------------------------------------------------------------------------------------
-- 5. Small dimensions built from the reference tables (unmapped values are kept and labelled)
-- -------------------------------------------------------------------------------------
DROP TABLE IF EXISTS dim_directorate;
CREATE TABLE dim_directorate AS
SELECT ROW_NUMBER() OVER (ORDER BY directorate) AS directorate_key, directorate
FROM (SELECT DISTINCT COALESCE(d.directorate, COALESCE(p.department_raw, 'Unknown')) AS directorate
      FROM int_payments_ok p LEFT JOIN ref_department d ON d.department_raw = p.department_raw);

DROP TABLE IF EXISTS dim_service_area;
CREATE TABLE dim_service_area AS
SELECT ROW_NUMBER() OVER (ORDER BY service_area) AS service_area_key, service_area
FROM (SELECT DISTINCT COALESCE(s.service_area_clean, COALESCE(p.service_area_raw, 'Unknown')) AS service_area
      FROM int_payments_ok p LEFT JOIN ref_service_area s ON s.service_area_raw = p.service_area_raw);

DROP TABLE IF EXISTS dim_spend_category;
CREATE TABLE dim_spend_category AS
SELECT ROW_NUMBER() OVER (ORDER BY spend_theme, spend_category) AS spend_category_key, spend_category, spend_theme
FROM (SELECT DISTINCT COALESCE(c.spend_category_clean, COALESCE(p.spend_category_raw, 'Unknown')) AS spend_category,
                      COALESCE(c.spend_theme, 'Unmapped')                                         AS spend_theme
      FROM int_payments_ok p LEFT JOIN ref_spend_category c ON c.spend_category_raw = p.spend_category_raw);

DROP TABLE IF EXISTS dim_purpose;
CREATE TABLE dim_purpose AS
SELECT ROW_NUMBER() OVER (ORDER BY purpose) AS purpose_key, purpose
FROM (SELECT DISTINCT COALESCE(purpose_raw, 'Unknown') AS purpose FROM int_payments_ok);

-- -------------------------------------------------------------------------------------
-- 6. dim_date  (UK local-government financial year runs 1 April - 31 March)
-- -------------------------------------------------------------------------------------
DROP TABLE IF EXISTS dim_date;
CREATE TABLE dim_date AS
WITH RECURSIVE days(d) AS (
    SELECT DATE(MIN(payment_date), 'start of month') FROM int_payments_ok
    UNION ALL
    SELECT DATE(d, '+1 day') FROM days
    WHERE d < (SELECT DATE(MAX(payment_date), 'start of month', '+1 month', '-1 day') FROM int_payments_ok)
)
SELECT
    CAST(STRFTIME('%Y%m%d', d) AS INTEGER)                              AS date_key,
    d                                                                   AS date,
    CAST(STRFTIME('%Y', d) AS INTEGER)                                  AS calendar_year,
    CAST(STRFTIME('%m', d) AS INTEGER)                                  AS month_number,
    CASE STRFTIME('%m', d) WHEN '01' THEN 'Jan' WHEN '02' THEN 'Feb' WHEN '03' THEN 'Mar' WHEN '04' THEN 'Apr'
         WHEN '05' THEN 'May' WHEN '06' THEN 'Jun' WHEN '07' THEN 'Jul' WHEN '08' THEN 'Aug'
         WHEN '09' THEN 'Sep' WHEN '10' THEN 'Oct' WHEN '11' THEN 'Nov' ELSE 'Dec' END AS month_name,
    STRFTIME('%Y-%m', d)                                                AS year_month,
    CASE WHEN CAST(STRFTIME('%m', d) AS INTEGER) >= 4
         THEN STRFTIME('%Y', d) || '/' || SUBSTR(CAST(CAST(STRFTIME('%Y', d) AS INTEGER) + 1 AS TEXT), 3, 2)
         ELSE CAST(CAST(STRFTIME('%Y', d) AS INTEGER) - 1 AS TEXT) || '/' || SUBSTR(STRFTIME('%Y', d), 3, 2)
    END                                                                 AS financial_year,
    ((CAST(STRFTIME('%m', d) AS INTEGER) + 8) % 12) + 1                 AS financial_month_number,   -- Apr = 1 ... Mar = 12
    ((CAST(STRFTIME('%m', d) AS INTEGER) + 8) % 12) / 3 + 1             AS financial_quarter,        -- Q1 = Apr-Jun
    CASE STRFTIME('%w', d) WHEN '0' THEN 'Sun' WHEN '1' THEN 'Mon' WHEN '2' THEN 'Tue' WHEN '3' THEN 'Wed'
         WHEN '4' THEN 'Thu' WHEN '5' THEN 'Fri' ELSE 'Sat' END         AS day_of_week,
    CASE WHEN STRFTIME('%w', d) IN ('0','6') THEN 1 ELSE 0 END          AS is_weekend
FROM days;

-- -------------------------------------------------------------------------------------
-- 7. fact_payments  (grain: one payment line as published)
-- -------------------------------------------------------------------------------------
DROP TABLE IF EXISTS fact_payments;
CREATE TABLE fact_payments AS
SELECT
    p.stg_id                                                          AS payment_id,
    CAST(STRFTIME('%Y%m%d', p.payment_date) AS INTEGER)               AS date_key,
    s.supplier_key,
    dd.directorate_key,
    sa.service_area_key,
    sc.spend_category_key,
    pu.purpose_key,
    COALESCE(d.expenditure_type, 'Unmapped')                          AS expenditure_type,
    p.transaction_number,
    p.supplier_id                                                     AS source_supplier_id,
    p.supplier_name_raw                                               AS source_supplier_name,
    p.source_period,
    p.source_file,
    p.source_row,
    p.amount,
    p.irrecoverable_vat,
    CASE WHEN p.amount < 0   THEN 1 ELSE 0 END                        AS is_credit_note,
    CASE WHEN p.amount < 500 THEN 1 ELSE 0 END                        AS is_below_threshold,
    -- Candidate duplicate payment: same supplier, same day, same amount (>= GBP 1,000), appearing more than once
    CASE WHEN p.amount >= 1000 AND COUNT(*) OVER (PARTITION BY p.supplier_entity_key, p.payment_date, p.amount) > 1
         THEN 1 ELSE 0 END                                            AS is_possible_duplicate_payment
FROM int_payments_ok p
JOIN dim_supplier s          ON s.supplier_entity_key = p.supplier_entity_key
LEFT JOIN ref_department d   ON d.department_raw = p.department_raw
JOIN dim_directorate dd      ON dd.directorate = COALESCE(d.directorate, COALESCE(p.department_raw, 'Unknown'))
LEFT JOIN ref_service_area r ON r.service_area_raw = p.service_area_raw
JOIN dim_service_area sa     ON sa.service_area = COALESCE(r.service_area_clean, COALESCE(p.service_area_raw, 'Unknown'))
LEFT JOIN ref_spend_category c ON c.spend_category_raw = p.spend_category_raw
JOIN dim_spend_category sc   ON sc.spend_category = COALESCE(c.spend_category_clean, COALESCE(p.spend_category_raw, 'Unknown'))
                            AND sc.spend_theme    = COALESCE(c.spend_theme, 'Unmapped')
JOIN dim_purpose pu          ON pu.purpose = COALESCE(p.purpose_raw, 'Unknown');

CREATE UNIQUE INDEX idx_fact_payment_id ON fact_payments(payment_id);
CREATE INDEX idx_fact_supplier ON fact_payments(supplier_key);
CREATE INDEX idx_fact_date     ON fact_payments(date_key);
