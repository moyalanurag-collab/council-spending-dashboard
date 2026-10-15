# Adapting the project to another council (e.g. a Scottish council such as Stirling)

The pipeline was run end to end on **London Borough of Hounslow** because its monthly "Invoices over £500" files are published as open data under the Open Government Licence on data.gov.uk and could be downloaded and verified. Scottish councils generally publish their own payments files on their own websites (not through data.gov.uk), and the Local Government Transparency Code that sets the £500 rule applies to English authorities - so Scottish files, formats and licences vary by council.

**Before using a Scottish council's data, check on its website (a) that the files are published for reuse and under which licence, and (b) the column layout.** Then:

## Steps
1. Put the monthly files (CSV or Excel) in `data/raw/`. Name each with its month and year, e.g. `Payments over 500 March 2025.csv` (`ingest.py` reads the month/year from the filename). Skip `src/download.py`.
2. Edit `config/source_map.json`:
   * set `council_name`, `licence`, `source_url`;
   * change the **left-hand side** of `columns` to the new council's headers (right-hand side stays as is). If the council has no `SupplierID` or `PurposeCode` column, the pipeline tolerates a missing/blank ID (supplier identity is name-based) - map the nearest equivalent or add an empty column.
3. Run `python run_pipeline.py --skip-ml`. Open `data/processed/dq_results.csv`:
   * **DQ14 / DQ15** list every spend category / department that is not in the mapping tables - add them to `sql/02_reference_data.sql` (category -> theme, department -> directorate + capital/revenue) and re-run;
   * check **DQ03-DQ10** for parsing problems (date formats other than `dd/mm/yyyy` or ISO need a new `WHEN` branch in `01_clean_staging.sql`).
4. Re-run with the classifier (`python run_pipeline.py`) once the mappings are complete.
5. Update the titles and attribution text in the Power BI report.

## Linking to a dissertation dataset
If the goal is to connect this to the Stirling Council dissertation, the natural join keys are:
* **Time** - `dim_date[financial_year]` / `year_month` (align the dissertation's period with the payments period);
* **Service area** - map the dissertation's service/department names to `dim_service_area` or `dim_directorate` with a small lookup table (`ref_dissertation_link`) and relate it in the model;
* **Supplier** - `dim_supplier[supplier_entity_key]` if the dissertation names suppliers or providers.
Add the dissertation table to Power BI as another dimension/fact and relate it on one of those keys.
