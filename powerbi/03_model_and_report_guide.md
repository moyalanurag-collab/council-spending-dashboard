# Manual build guide (alternative to the ready-made project)

> A finished, tested report is already provided: open `council-spending.pbip` (see [00_START_HERE.md](00_START_HERE.md)). Use this guide only if you want to rebuild or redesign it by hand (about 60-90 minutes).

The files in this folder:

| File | What it is |
|---|---|
| `01_load_data.m` | Power Query for every table (typed, with a tidy-name function for supplier names) |
| `02_measures.dax` | All DAX measures, commented |
| `theme.json` | Colour/typography theme (View > Themes > Browse for themes) |
| this file | Model relationships, page-by-page report layout, formatting rules |

Chart previews of what each page should show are in [`docs/images/`](../docs/images) and the numbers to expect are in [`docs/findings.md`](../docs/findings.md), so you can sanity-check your report against them.

---

## 1. Load the data
1. Run the pipeline once (`python run_pipeline.py`) so `data/processed/*.csv` exists. The repo ships with these files already built.
2. Follow the header comment in `01_load_data.m` (create the `DataFolder` parameter, then `fnTidyName`, then each table).
3. After loading, set **dim_date** as the date table: select the table > Table tools > *Mark as date table* > column `date`.

## 2. Model (star schema)

```
                     dim_date
                        | 1
dim_supplier --*  fact_payments  *-- dim_directorate
dim_spend_category --*   |  *-- dim_service_area
                         *-- dim_purpose
```

Create these relationships (Model view). All are **many-to-one, single direction, from the fact table to the dimension**:

| From (many) | To (one) | Active |
|---|---|---|
| `fact_payments[date_key]` | `dim_date[date_key]` | Yes |
| `fact_payments[supplier_key]` | `dim_supplier[supplier_key]` | Yes |
| `fact_payments[directorate_key]` | `dim_directorate[directorate_key]` | Yes |
| `fact_payments[service_area_key]` | `dim_service_area[service_area_key]` | Yes |
| `fact_payments[spend_category_key]` | `dim_spend_category[spend_category_key]` | Yes |
| `fact_payments[purpose_key]` | `dim_purpose[purpose_key]` | Yes |
| `dim_supplier[first_payment_date]` | `dim_date[date]` | **No (inactive)** - used by the `New Suppliers` measure via `USERELATIONSHIP` |
| `ml_predictions[payment_id]` | `fact_payments[payment_id]` | Yes, **one-to-one** (optional page 5) |

Leave `dq_results`, `dq_possible_duplicate_payments`, `dq_supplier_id_conflicts`, `dq_multi_id_suppliers` and `excluded_rows` **unrelated** - they are stand-alone diagnostic tables.

Housekeeping:
* Hide the key columns (`*_key`, `payment_id`) and `source_*` columns from Report view.
* Sort `dim_date[month_name]` by `month_number`; sort `dim_date[year_month]` ascending (it sorts correctly as text).
* Formats: `amount` and every currency measure `£#,0;-£#,0`; percentages `0.0%`.
* Add `dim_spend_category[spend_theme]` > `spend_category` as a hierarchy; add `dim_date` hierarchy `financial_year > financial_quarter > year_month`.

## 3. Measures
Create an empty table `_Measures` and paste each measure from `02_measures.dax`. Group them into display folders: *Core*, *Time*, *Suppliers*, *Data quality*, *Classification*.

## 4. Report pages

Apply `theme.json` first. Canvas 16:9. Put a thin title strip on every page ("Hounslow payments over £500 - Apr 2025 to May 2026") and a footer text box: *"Source: London Borough of Hounslow, Invoices over £500, Open Government Licence v3.0."*

### Page 1 - Overview
* **Slicers (left rail):** `dim_date[financial_year]`, `dim_date[year_month]` (dropdown), `fact_payments[expenditure_type]`, `dim_directorate[directorate]` (dropdown).
* **KPI cards (top row, 6):** `Net Spend`, `Gross Spend`, `Credit Notes`, `Payment Lines`, `Named Suppliers`, `Average Payment`.
* **Stacked column:** axis `dim_date[year_month]`, legend `dim_spend_category[spend_theme]`, values `Net Spend`. Title "Monthly spend by theme".
* **Line (secondary visual in the same row):** `Net Spend` with `Rolling 3M Net Spend`, or a card pair `Net Spend` / `MoM Change %` for the latest month.
* **Bar:** `dim_directorate[directorate]` x `Net Spend`, sorted descending, top 10.
* **Bar:** `dim_spend_category[spend_theme]` x `Net Spend` with data labels showing % of grand total.

### Page 2 - Suppliers
* **Cards:** `Top 10 Suppliers Share %`, `Named Suppliers`, `One-Month Suppliers`, `Redacted Share %`.
* **Pareto (combo chart):** clustered column `Net Spend (Named Suppliers)` + line `Cumulative Share %` on the secondary axis; X = `dim_supplier[supplier_display]`; visual filter *Top N = 20 by Net Spend (Named Suppliers)*; add visual filter `is_named_supplier = Yes`.
* **Bar:** `dim_supplier[supplier_type]` x `Net Spend` (shows the public / private / voluntary split).
* **Table:** `Supplier Rank`, `supplier_display`, `supplier_type`, `Net Spend (Named Suppliers)`, `Share of Total %`, `Payment Lines`, `first_payment_date`, `last_payment_date`; visual filter `is_named_supplier = Yes`; data bars on spend.
* **Column:** `dim_date[year_month]` x `New Suppliers` (supplier churn).
* Add a **drill-through** page target on `dim_supplier[supplier_display]` showing that supplier's monthly spend, categories and largest payments.

### Page 3 - Categories and directorates
* **Matrix:** rows `dim_directorate[directorate]`, columns `dim_spend_category[spend_theme]`, values `Net Spend`; conditional-format background colour scale (white to `#2F5D8A`).
* **Treemap:** `dim_spend_category[spend_category]` sized by `Net Spend`.
* **Bar:** `dim_service_area[service_area]` x `Net Spend`.
* **Clustered column:** `fact_payments[expenditure_type]` x `Net Spend` by `financial_year` (capital vs revenue vs HRA).
* **Table:** `dim_purpose[purpose]`, `Net Spend`, `Payment Lines` (top 15).

### Page 4 - Data quality
* **Cards:** `DQ Checks Passed`, `DQ Checks Warning`, `DQ Checks Failed`, `DQ Pass Rate %`, `Rows Excluded`, `Reconciliation Status`.
* **Table:** `dq_results[check_id]`, `dimension`, `check_name`, `rows_affected`, `pct_affected`, `amount_affected`, `result`, `how_handled`. Conditional formatting on `result` (rules): PASS `#4C9F70`, WARN `#C9A227`, FAIL `#B5484C`, INFO `#7A7A7A` (font colour).
* **Bar:** `dq_results[check_id]` x `pct_affected` filtered to `result` in (WARN, FAIL).
* **Three drill tables** (tabbed with bookmarks): `dq_possible_duplicate_payments`, `dq_supplier_id_conflicts`, `dq_multi_id_suppliers`.
* **Text box** explaining: *"Redacted payees are kept (value is real spend) but excluded from supplier rankings; possible duplicates are flagged for review, not removed."*

### Page 5 - Classification review (optional extra)
* **Cards:** `Model Theme Agreement %`, `Model Category Agreement %`, `Lines For Coding Review`, `Value For Coding Review`.
* **Matrix:** rows `ml_predictions[council_theme]`, columns `ml_predictions[predicted_theme]`, values count of `payment_id` (confusion matrix; diagonal = agreement).
* **Table:** the review queue - join in `data/processed/ml_review_queue.csv` as an extra table, or filter `fact_payments` by `ml_predictions[review_flag] = 1` and show supplier, amount, `council_category`, `predicted_category`, `confidence`.
* **Note box:** the model is trained on the council's own coding, so a disagreement is an *audit lead*, not proof of an error.

## 5. Quality checklist before you publish
- [ ] `Net Spend` card with no slicers = **£347,756,717** (the same figure as `docs/findings.md` and `SELECT SUM(amount) FROM fact_payments`).
- [ ] Payment Lines = **37,261**; Named Suppliers = **2,645**.
- [ ] Every visual has a title, units, and sensible sort; no default "Sum of ..." labels.
- [ ] Colour is not the only carrier of meaning (data labels on bars; PASS/WARN text visible).
- [ ] Tab order / alt text set on each visual (View > Selection pane, Format > General > Alt text).
- [ ] Page navigator or tabs, a reset-slicers bookmark button, and the OGL attribution footer.
- [ ] Save as `council-spending-dashboard.pbix`; export a PDF and add 2-3 PNGs to `docs/images/` for the README.

## Publishing note
If you publish to the Power BI Service, only share the report publicly if the data licence allows it. The Hounslow data is OGL (reuse with attribution), but remember the **redacted payee** rows are already redacted at source - do not try to re-identify them.
