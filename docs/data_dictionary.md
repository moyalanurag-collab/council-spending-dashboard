# Data dictionary

All tables are produced by `sql/03_model.sql` / `sql/04_data_quality.sql` and exported to `data/processed/*.csv`.

## fact_payments  (grain: one payment line as published by the council)
| Column | Type | Description |
|---|---|---|
| payment_id | int | Stable id = row id in staging (unique) |
| date_key | int | `yyyymmdd` -> `dim_date` |
| supplier_key / directorate_key / service_area_key / spend_category_key / purpose_key | int | Foreign keys to the dimensions |
| expenditure_type | text | `Revenue`, `Capital`, `HRA`, `HRA Capital` (derived from the "CAPITAL ..." prefix on the council's department); `Unmapped` if the department is not in `ref_department` |
| transaction_number | text | Council transaction reference. **Not unique** - one invoice can have several lines |
| source_supplier_id | text | Supplier ID as published (may be reused/duplicated - see DQ12/DQ13) |
| source_supplier_name | text | Supplier name exactly as published (trimmed) |
| source_period / source_file / source_row | text/int | Lineage back to the monthly file and spreadsheet row |
| amount | real | GBP as published (confirm VAT treatment with the publisher's metadata); negative = credit note/refund |
| irrecoverable_vat | real | VAT the council cannot reclaim |
| is_credit_note | 0/1 | `amount < 0` |
| is_below_threshold | 0/1 | `amount < 500` (the publication threshold applies to the invoice, so some lines are lower) |
| is_possible_duplicate_payment | 0/1 | Same supplier, same day, same amount (>= GBP 1,000) on more than one line. **A review flag, not an error** |

## dim_supplier  (one row per real-world supplier)
| Column | Description |
|---|---|
| supplier_key | Surrogate key |
| supplier_entity_key | Identity key: normalised name (`ACME` for "Acme Ltd.", "THE ACME LIMITED" ...) or `REDACTED|<id>` |
| supplier_name | Most frequent raw spelling (upper-case as published) |
| is_redacted | 1 = payee name withheld for personal-data reasons ("REDACTED PERSONAL DATA"). Each redacted supplier ID stays a separate entity |
| supplier_type | Heuristic from the name: `Public sector`, `Education`, `Charity / voluntary`, `Private company`, `Individual (redacted)`, `Other / unclassified` |
| name_variants | How many distinct spellings were merged into this supplier |
| supplier_id_count / supplier_ids | Number / list of source Supplier IDs used by this supplier |
| first_payment_date / last_payment_date | Range of payments in the dataset |

## dim_date
`date_key`, `date`, `calendar_year`, `month_number`, `month_name`, `year_month` (`2025-04`), `financial_year` (`2025/26`, 1 Apr - 31 Mar), `financial_month_number` (Apr=1), `financial_quarter` (Q1=Apr-Jun), `day_of_week`, `is_weekend`.

## dim_directorate / dim_service_area / dim_spend_category / dim_purpose
Clean labels from the `ref_*` mapping tables in `sql/02_reference_data.sql`. `dim_spend_category.spend_theme` is an **analyst-defined grouping into 9 themes** (it is not part of the council's data - review it with the business owner).

## dq_results
`check_id`, `dimension`, `check_name`, `rows_affected`, `rows_total`, `pct_affected`, `amount_affected`, `result` (`PASS` / `WARN` / `FAIL` / `INFO`), `how_handled`.

## Other diagnostic tables
* `excluded_rows` - every staged row not loaded and why (`BLANK_ROW`, `INVALID_AMOUNT`, `INVALID_DATE`, `MISSING_SUPPLIER`, `DUPLICATE_ROW`).
* `dq_possible_duplicate_payments`, `dq_supplier_id_conflicts`, `dq_multi_id_suppliers` - drill-through lists behind DQ17, DQ12, DQ13.
* `dq_supplier_match_candidates` (CSV only) - fuzzy-matched probable duplicate suppliers (`src/supplier_matching.py`).
* `ml_predictions`, `ml_review_queue` (CSV) - text-classification output.

## Source columns (as published) and how they map
| Published column | Pipeline name |
|---|---|
| OrganisationalUnit | department -> `dim_directorate` + `expenditure_type` |
| ServiceCategoryLabel | service_area -> `dim_service_area` |
| BeneficiaryName | supplier_name_raw -> `dim_supplier` |
| SupplierID | supplier_id |
| PaymentDate | payment_date |
| TransactionNumber | transaction_number |
| Amount | amount |
| IrrecoverableVATAmount | irrecoverable_vat |
| Purpose | purpose -> `dim_purpose` |
| CategoryInternalName | spend_category -> `dim_spend_category` |
