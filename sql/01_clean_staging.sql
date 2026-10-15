-- =====================================================================================
-- 01_clean_staging.sql
-- Purpose : turn the all-TEXT staging table (stg_payments) into typed, trimmed rows and
--           flag rows that cannot be loaded into the fact table (with a reason).
-- Reads   : stg_payments           (one row per source line, all columns TEXT)
-- Creates : int_payments           typed + cleaned rows (one per staged row)
--           int_supplier_names     every distinct raw supplier name with its normalised key
-- Dialect : SQLite (ANSI-style; see docs/methodology.md for T-SQL notes)
-- =====================================================================================

DROP TABLE IF EXISTS int_payments;
CREATE TABLE int_payments AS
WITH trimmed AS (
    -- Trim, replace non-breaking spaces and collapse runs of spaces in every text column.
    SELECT
        rowid AS stg_id,
        source_file, source_period, source_row,
        NULLIF(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(department,        CHAR(160),' '),'  ',' '),'  ',' '),'  ',' ')),'') AS department_raw,
        NULLIF(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(service_area,      CHAR(160),' '),'  ',' '),'  ',' '),'  ',' ')),'') AS service_area_raw,
        NULLIF(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(supplier_name_raw, CHAR(160),' '),'  ',' '),'  ',' '),'  ',' ')),'') AS supplier_name_raw,
        NULLIF(TRIM(supplier_id),'')                                                                                     AS supplier_id,
        NULLIF(TRIM(payment_date),'')                                                                                    AS payment_date_raw,
        NULLIF(TRIM(transaction_number),'')                                                                              AS transaction_number,
        REPLACE(REPLACE(REPLACE(TRIM(amount),',',''),'£',''),' ','')                                                     AS amount_txt,
        REPLACE(REPLACE(REPLACE(TRIM(irrecoverable_vat),',',''),'£',''),' ','')                                          AS vat_txt,
        NULLIF(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(purpose,           CHAR(160),' '),'  ',' '),'  ',' '),'  ',' ')),'') AS purpose_raw,
        NULLIF(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(spend_category,    CHAR(160),' '),'  ',' '),'  ',' '),'  ',' ')),'') AS spend_category_raw
    FROM stg_payments
),
typed AS (
    SELECT
        t.*,
        -- The CSV releases use dd/mm/yyyy text; the Excel releases arrive as 'yyyy-mm-dd hh:mm:ss'.
        CASE
            WHEN payment_date_raw LIKE '__/__/____'  THEN SUBSTR(payment_date_raw,7,4) || '-' || SUBSTR(payment_date_raw,4,2) || '-' || SUBSTR(payment_date_raw,1,2)
            WHEN payment_date_raw LIKE '____-__-__%' THEN SUBSTR(payment_date_raw,1,10)
        END AS payment_date_try,
        CASE WHEN amount_txt <> '' AND amount_txt NOT GLOB '*[^0-9.-]*' AND amount_txt GLOB '*[0-9]*'
             THEN CAST(amount_txt AS REAL) END AS amount,
        CASE WHEN vat_txt = '' THEN 0.0
             WHEN vat_txt NOT GLOB '*[^0-9.-]*' AND vat_txt GLOB '*[0-9]*' THEN CAST(vat_txt AS REAL) END AS irrecoverable_vat
    FROM trimmed t
)
SELECT
    stg_id, source_file, source_period, source_row,
    department_raw, service_area_raw, supplier_name_raw, supplier_id,
    CASE WHEN payment_date_try IS NOT NULL AND DATE(payment_date_try) = payment_date_try THEN payment_date_try END AS payment_date,
    payment_date_raw, transaction_number, amount, irrecoverable_vat,
    purpose_raw, spend_category_raw,
    -- Row-level load decision. Anything other than 'OK' is kept out of the fact table (see 03_model.sql).
    CASE
        WHEN department_raw IS NULL AND supplier_name_raw IS NULL AND supplier_id IS NULL
             AND payment_date_raw IS NULL AND amount_txt = ''                       THEN 'BLANK_ROW'
        WHEN amount IS NULL                                                         THEN 'INVALID_AMOUNT'
        WHEN payment_date_try IS NULL OR DATE(payment_date_try) <> payment_date_try THEN 'INVALID_DATE'
        WHEN supplier_name_raw IS NULL                                              THEN 'MISSING_SUPPLIER'
        ELSE 'OK'
    END AS load_status
FROM typed;

CREATE INDEX idx_int_payments_stg ON int_payments(stg_id);

-- -------------------------------------------------------------------------------------
-- Supplier-name normalisation (pure SQL, applied to the ~2.6k DISTINCT names, not 37k rows)
--   1. upper-case, '&' -> AND, strip punctuation, collapse spaces
--   2. strip leading 'THE ' and trailing legal-form words (LTD, LIMITED, PLC, LLP, LLC, INC, CIC, UK)
--      - applied twice so 'ACME UK LTD' -> 'ACME'
--   3. remove all spaces so 'POINT 2 SURVEYORS' = 'POINT2 SURVEYORS'
--   Personal-data redactions are NOT merged by name (see 03_model.sql).
-- -------------------------------------------------------------------------------------
DROP TABLE IF EXISTS int_supplier_names;
CREATE TABLE int_supplier_names AS
WITH s1 AS (
    SELECT DISTINCT
        supplier_name_raw,
        REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
            UPPER(supplier_name_raw),
            '&', ' AND '), '.', ''), ',', ' '), '''', ''), '’', ''), '"', ''), '(', ' '), ')', ' '), '-', ' '), '/', ' '), '*', ' '), '  ', ' ') AS n1
    FROM int_payments
    WHERE supplier_name_raw IS NOT NULL
),
s2 AS (SELECT supplier_name_raw, TRIM(REPLACE(REPLACE(REPLACE(n1,'  ',' '),'  ',' '),'  ',' ')) AS n2 FROM s1),
s3 AS (SELECT supplier_name_raw, CASE WHEN n2 LIKE 'THE %' THEN SUBSTR(n2,5) ELSE n2 END AS n3 FROM s2),
strip1 AS (
    SELECT supplier_name_raw,
        TRIM(CASE
            WHEN n3 LIKE '% LIMITED' THEN SUBSTR(n3,1,LENGTH(n3)-8)
            WHEN n3 LIKE '% LTD'     THEN SUBSTR(n3,1,LENGTH(n3)-4)
            WHEN n3 LIKE '% PLC'     THEN SUBSTR(n3,1,LENGTH(n3)-4)
            WHEN n3 LIKE '% LLP'     THEN SUBSTR(n3,1,LENGTH(n3)-4)
            WHEN n3 LIKE '% LLC'     THEN SUBSTR(n3,1,LENGTH(n3)-4)
            WHEN n3 LIKE '% INC'     THEN SUBSTR(n3,1,LENGTH(n3)-4)
            WHEN n3 LIKE '% CIC'     THEN SUBSTR(n3,1,LENGTH(n3)-4)
            WHEN n3 LIKE '% UK'      THEN SUBSTR(n3,1,LENGTH(n3)-3)
            ELSE n3 END) AS n4
    FROM s3
),
strip2 AS (
    SELECT supplier_name_raw,
        TRIM(CASE
            WHEN n4 LIKE '% LIMITED' THEN SUBSTR(n4,1,LENGTH(n4)-8)
            WHEN n4 LIKE '% LTD'     THEN SUBSTR(n4,1,LENGTH(n4)-4)
            WHEN n4 LIKE '% PLC'     THEN SUBSTR(n4,1,LENGTH(n4)-4)
            WHEN n4 LIKE '% LLP'     THEN SUBSTR(n4,1,LENGTH(n4)-4)
            WHEN n4 LIKE '% UK'      THEN SUBSTR(n4,1,LENGTH(n4)-3)
            ELSE n4 END) AS n5
    FROM strip1
)
SELECT
    supplier_name_raw,
    n5                                                                    AS supplier_name_norm,
    REPLACE(n5, ' ', '')                                                  AS supplier_name_key,
    CASE WHEN UPPER(supplier_name_raw) LIKE 'REDACTED%' THEN 1 ELSE 0 END AS is_redacted
FROM strip2;

CREATE UNIQUE INDEX idx_int_supplier_names ON int_supplier_names(supplier_name_raw);
