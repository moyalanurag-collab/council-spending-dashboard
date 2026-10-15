-- =====================================================================================
-- 05_analysis_queries.sql
-- Ready-to-run analytical queries on the star schema (also executed by src/findings.py).
-- Each block starts with "-- name: <id>" so scripts can pick them out.
-- Redacted (personal-data) payees are excluded from supplier rankings; net spend = SUM(amount)
-- includes credit notes, gross = positive amounts only.
-- =====================================================================================

-- name: kpis
SELECT
    ROUND(SUM(f.amount), 0)                                                   AS net_spend,
    ROUND(SUM(CASE WHEN f.amount > 0 THEN f.amount END), 0)                   AS gross_spend,
    ROUND(SUM(CASE WHEN f.amount < 0 THEN f.amount END), 0)                   AS credit_notes,
    COUNT(*)                                                                  AS payment_lines,
    COUNT(DISTINCT CASE WHEN s.is_redacted = 0 THEN f.supplier_key END)       AS suppliers,
    ROUND(AVG(f.amount), 0)                                                   AS avg_payment,
    MIN(d.date)                                                               AS first_payment,
    MAX(d.date)                                                               AS last_payment
FROM fact_payments f
JOIN dim_supplier s ON s.supplier_key = f.supplier_key
JOIN dim_date d     ON d.date_key = f.date_key;

-- name: monthly_by_theme
SELECT d.year_month, c.spend_theme, ROUND(SUM(f.amount), 0) AS net_spend, COUNT(*) AS lines
FROM fact_payments f
JOIN dim_date d            ON d.date_key = f.date_key
JOIN dim_spend_category c  ON c.spend_category_key = f.spend_category_key
GROUP BY d.year_month, c.spend_theme
ORDER BY d.year_month, net_spend DESC;

-- name: monthly_mom
-- Month-on-month change with LAG(); the first month has no prior value.
WITH m AS (
    SELECT d.year_month, SUM(f.amount) AS net_spend, COUNT(*) AS lines
    FROM fact_payments f JOIN dim_date d ON d.date_key = f.date_key
    GROUP BY d.year_month
)
SELECT year_month, ROUND(net_spend, 0) AS net_spend, lines,
       ROUND(net_spend - LAG(net_spend) OVER (ORDER BY year_month), 0)                              AS mom_change,
       ROUND(100.0 * (net_spend / LAG(net_spend) OVER (ORDER BY year_month) - 1), 1)                AS mom_change_pct,
       ROUND(AVG(net_spend) OVER (ORDER BY year_month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 0) AS rolling_3m_avg
FROM m ORDER BY year_month;

-- name: top_suppliers
-- Pareto view: share and cumulative share of spend for named (non-redacted) suppliers.
WITH t AS (
    SELECT s.supplier_name, s.supplier_type, SUM(f.amount) AS net_spend, COUNT(*) AS lines
    FROM fact_payments f JOIN dim_supplier s ON s.supplier_key = f.supplier_key
    WHERE s.is_redacted = 0
    GROUP BY s.supplier_key
)
SELECT ROW_NUMBER() OVER (ORDER BY net_spend DESC) AS rank,
       supplier_name, supplier_type, ROUND(net_spend, 0) AS net_spend, lines,
       ROUND(100.0 * net_spend / SUM(net_spend) OVER (), 2) AS share_pct,
       ROUND(100.0 * SUM(net_spend) OVER (ORDER BY net_spend DESC ROWS UNBOUNDED PRECEDING) / SUM(net_spend) OVER (), 2) AS cumulative_share_pct
FROM t ORDER BY net_spend DESC LIMIT 15;

-- name: supplier_concentration
-- How many suppliers account for 50% / 80% of named-supplier spend, plus the Herfindahl-Hirschman index.
WITH t AS (
    SELECT SUM(f.amount) AS net_spend
    FROM fact_payments f JOIN dim_supplier s ON s.supplier_key = f.supplier_key
    WHERE s.is_redacted = 0 AND f.amount IS NOT NULL
    GROUP BY s.supplier_key
    HAVING SUM(f.amount) > 0
),
r AS (
    SELECT net_spend,
           SUM(net_spend) OVER (ORDER BY net_spend DESC ROWS UNBOUNDED PRECEDING) / SUM(net_spend) OVER () AS cum_share,
           ROW_NUMBER() OVER (ORDER BY net_spend DESC) AS rk,
           net_spend * 1.0 / SUM(net_spend) OVER () AS share
    FROM t
)
SELECT COUNT(*)                                                       AS suppliers_with_positive_spend,
       MIN(CASE WHEN cum_share >= 0.5 THEN rk END)                    AS suppliers_for_50pct,
       MIN(CASE WHEN cum_share >= 0.8 THEN rk END)                    AS suppliers_for_80pct,
       ROUND(100.0 * MAX(CASE WHEN rk = 10 THEN cum_share END), 1)    AS top10_share_pct,
       ROUND(SUM(share * share) * 10000, 0)                           AS hhi
FROM r;

-- name: by_directorate
SELECT dr.directorate, f.expenditure_type, ROUND(SUM(f.amount), 0) AS net_spend, COUNT(*) AS lines
FROM fact_payments f JOIN dim_directorate dr ON dr.directorate_key = f.directorate_key
GROUP BY dr.directorate, f.expenditure_type
ORDER BY net_spend DESC;

-- name: by_supplier_type
SELECT s.supplier_type, COUNT(DISTINCT s.supplier_key) AS suppliers, ROUND(SUM(f.amount), 0) AS net_spend,
       ROUND(100.0 * SUM(f.amount) / SUM(SUM(f.amount)) OVER (), 1) AS share_pct
FROM fact_payments f JOIN dim_supplier s ON s.supplier_key = f.supplier_key
GROUP BY s.supplier_type ORDER BY net_spend DESC;

-- name: largest_payments
SELECT d.date AS payment_date, s.supplier_name, c.spend_category, dr.directorate, ROUND(f.amount, 0) AS amount
FROM fact_payments f
JOIN dim_supplier s       ON s.supplier_key = f.supplier_key
JOIN dim_date d           ON d.date_key = f.date_key
JOIN dim_spend_category c ON c.spend_category_key = f.spend_category_key
JOIN dim_directorate dr   ON dr.directorate_key = f.directorate_key
ORDER BY f.amount DESC LIMIT 10;

-- name: new_vs_repeat_suppliers
-- Supplier churn: first-ever payment month in the dataset (excludes the first month, where everyone is "new").
SELECT STRFTIME('%Y-%m', first_payment_date) AS first_month, COUNT(*) AS new_suppliers
FROM dim_supplier WHERE is_redacted = 0
GROUP BY first_month ORDER BY first_month;

-- name: one_off_suppliers
-- Suppliers paid in only one month of the period (potential tail-spend / one-off vendors).
WITH t AS (
    SELECT s.supplier_key, COUNT(DISTINCT d.year_month) AS active_months, SUM(f.amount) AS net_spend
    FROM fact_payments f
    JOIN dim_supplier s ON s.supplier_key = f.supplier_key
    JOIN dim_date d     ON d.date_key = f.date_key
    WHERE s.is_redacted = 0
    GROUP BY s.supplier_key
)
SELECT SUM(active_months = 1)                                          AS one_month_suppliers,
       COUNT(*)                                                        AS suppliers,
       ROUND(100.0 * SUM(active_months = 1) / COUNT(*), 1)             AS one_month_pct,
       ROUND(SUM(CASE WHEN active_months = 1 THEN net_spend END), 0)   AS one_month_spend,
       ROUND(100.0 * SUM(CASE WHEN active_months = 1 THEN net_spend END) / SUM(net_spend), 1) AS one_month_spend_pct
FROM t;

-- name: round_sum_outliers
-- Statistical outliers within each spend category (z-score of amount > 4), largest first.
WITH stats AS (
    SELECT spend_category_key, AVG(amount) AS mu,
           SQRT(AVG(amount * amount) - AVG(amount) * AVG(amount)) AS sd
    FROM fact_payments WHERE amount > 0 GROUP BY spend_category_key
)
SELECT s.supplier_name, c.spend_category, d.date AS payment_date, ROUND(f.amount, 0) AS amount,
       ROUND((f.amount - st.mu) / st.sd, 1) AS z_score
FROM fact_payments f
JOIN stats st             ON st.spend_category_key = f.spend_category_key AND st.sd > 0
JOIN dim_supplier s       ON s.supplier_key = f.supplier_key
JOIN dim_spend_category c ON c.spend_category_key = f.spend_category_key
JOIN dim_date d           ON d.date_key = f.date_key
WHERE f.amount > 0 AND (f.amount - st.mu) / st.sd > 4
ORDER BY z_score DESC LIMIT 15;
