# Methodology and design decisions

## 1. Pipeline

```
 data.gov.uk (CKAN API)        14 monthly files, CSV + Excel
        |  src/download.py
        v
   data/raw/                  untouched source files
        |  src/ingest.py      all columns kept as TEXT, + file / period / row lineage
        v
   stg_payments               faithful copy of the source (37,267 rows)
        |  sql/01_clean_staging.sql   trim, type, parse dates/amounts, normalise supplier names, flag bad rows
        |  sql/02_reference_data.sql  analyst-maintained mapping tables
        |  sql/03_model.sql           de-duplicate, build dim_* and fact_payments (star schema)
        |  sql/04_data_quality.sql    22 checks + drill-through tables
        v
   SQLite star schema  --->  src/supplier_matching.py  (fuzzy candidates)
        |                    src/classify.py           (text classification)
        |  src/export.py
        v
   data/processed/*.csv  --->  Power BI (powerbi/)       src/findings.py -> docs/findings.md + charts
```

Why this shape:
* **Staging is dumb on purpose.** Everything lands as text with lineage (`source_file`, `source_row`), so any number in the dashboard can be traced to a spreadsheet row.
* **All business logic is SQL.** Reviewers can read `sql/` top to bottom; Python only moves data and does the ML.
* **Nothing is dropped silently.** Rows that cannot be loaded go to `excluded_rows` with a reason, and DQ01 asserts `staged = loaded + excluded`; DQ02 asserts the loaded total equals the cleaned source total in GBP.
* **Mappings are data, not code.** `ref_spend_category`, `ref_department`, `ref_service_area` are tables; unmapped values are kept, labelled `Unmapped` and raise DQ14/DQ15 - so a new month or council never breaks the load.

## 2. Cleaning rules (what exactly happens)

| Problem seen in the real files | Rule |
|---|---|
| CSV dates `dd/mm/yyyy` vs Excel dates `yyyy-mm-dd hh:mm:ss` | Both parsed to ISO; unparseable -> `INVALID_DATE` (excluded) |
| Excel releases have a hidden `_options` sheet | Skipped by `ingest.py` |
| Text padding / non-breaking spaces / double spaces | Trimmed and collapsed in every text column |
| Blank rows at the end of CSVs | `BLANK_ROW`, excluded |
| Same supplier spelled differently (`3B DATA SECURITY` / `3B DATA SECURITY LTD`, `POINT2 SURVEYORS LTD` / `POINT 2 SURVEYORS LIMITED`) | Normalised key = upper-case, `&`->AND, punctuation removed, leading `THE`, trailing `LTD/LIMITED/PLC/LLP/LLC/INC/CIC/UK` stripped (twice), spaces removed. Same key = same supplier |
| ~500 different payees all named `REDACTED PERSONAL DATA` | **Not** merged: identity is `REDACTED|<SupplierID>`. Merging them would invent a GBP 6.7m "supplier" |
| Same Supplier ID used by different names, or one supplier with several IDs | Not used for identity (IDs proved unreliable); reported in DQ12 / DQ13 and drill-through tables |
| Probable typos that exact matching misses (`PROPERTIES`/`PROPETIES`) | Reported by `supplier_matching.py` (fuzzy ratio >= 92); **not** auto-merged |
| Directorate renamed / "CAPITAL ..." prefix / `&` vs `AND` | Mapped in `ref_department`; capital vs revenue becomes `expenditure_type` |
| Typos in service area (`Regualtory`), synonym (`Culture & Related`) | Mapped in `ref_service_area` |
| Negative amounts | Kept: credit notes reduce net spend; flagged `is_credit_note` |
| Lines below GBP 500 | Kept (threshold applies to the invoice); flagged `is_below_threshold` |
| Exact duplicate rows | Earliest kept, others excluded as `DUPLICATE_ROW` (none occurred in this release) |
| Same supplier, day and amount (>= GBP 1,000) on several lines | Kept, flagged `is_possible_duplicate_payment` - often genuine batch payments, so it is a review list only |

## 3. Analytical choices worth knowing
* **Net vs gross spend.** `Net Spend = SUM(amount)` (includes credit notes). Gross is positive amounts only.
* **Supplier rankings exclude redacted payees** (they would otherwise form one meaningless bar).
* **Report period = payment date**, not file month. DQ09 confirms the two agree for every row in this release.
* **Financial year** is 1 April - 31 March (UK local government), with Apr = financial month 1.
* **`spend_theme`** (9 groups) and **`supplier_type`** (name keywords) are analyst-defined; they are transparent and editable but are judgement calls - agree them with a domain owner before publishing.
* **Scope.** Payments over GBP 500 are a subset of council spending (no payroll, no sub-GBP 500 invoices), so totals are *not* the council's total expenditure.

## 4. Text classification (optional extra)
See [classification_report.md](classification_report.md). Key decisions:
* **GroupKFold by supplier** - random splits would let the model memorise supplier names and report a flattering score. Grouping measures performance on suppliers it has never seen.
* The target is the council's own coding, so the model reproduces the council's *habits*; confident disagreements are an audit queue, not errors.
* Linear model on TF-IDF (word + character n-grams) - simple, fast, explainable. Accuracy is moderate by design of the task (the same supplier often supplies several categories); the value is the review queue, not the headline accuracy.

## 5. Porting the SQL to SQL Server / PostgreSQL
The scripts use SQLite but only standard constructs plus a few functions that have direct equivalents:

| SQLite | T-SQL (SQL Server) | PostgreSQL |
|---|---|---|
| `STRFTIME('%Y-%m', d)` | `FORMAT(d,'yyyy-MM')` | `TO_CHAR(d,'YYYY-MM')` |
| `SUBSTR` / `||` | `SUBSTRING` / `+` or `CONCAT` | `SUBSTR` / `||` |
| `GLOB '*[^0-9.-]*'` | `PATINDEX('%[^0-9.-]%', x) > 0` | `x ~ '[^0-9.-]'` |
| `GROUP_CONCAT(DISTINCT x)` | `STRING_AGG(x, ',')` over a `DISTINCT` subquery | `STRING_AGG(DISTINCT x, ',')` |
| `CREATE TABLE ... AS SELECT` | `SELECT ... INTO` | `CREATE TABLE ... AS` |
| recursive CTE without `RECURSIVE` keyword | same, drop the word `RECURSIVE` | same as SQLite |
| `CHAR(160)` | `NCHAR(160)` | `CHR(160)` |

The window functions (`ROW_NUMBER`, `LAG`, `SUM() OVER`) are portable as written.

## 6. Known limitations
* One council and 14 months of data. The pipeline is multi-council ready (see [adapting_to_another_council.md](adapting_to_another_council.md)) but only Hounslow has been run.
* Supplier identity is name-based; two different legal entities with near-identical names would be merged (mitigated by keeping the normalisation conservative and reporting fuzzy candidates separately).
* The Power BI report is delivered as a text-based Power BI Project (`powerbi/council-spending.pbip`); a binary `.pbix` is not committed. The DataFolder parameter holds an absolute path and must be re-pointed on another machine.
