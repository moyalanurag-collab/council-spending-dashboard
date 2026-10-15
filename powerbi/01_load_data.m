// =====================================================================================
// 01_load_data.m  -  Power Query (M) for the Council Spending dashboard
//
// HOW TO USE
//   1. Power BI Desktop > Home > Transform data > Manage Parameters > New Parameter
//        Name: DataFolder   Type: Text   Current value: full path to data\processed\ WITH a trailing backslash
//        e.g.  C:\Users\you\council-spending-dashboard\data\processed\
//   2. For each query below: Home > New Source > Blank Query > Advanced Editor > paste the code, rename the query
//      to the name in the heading (fact_payments, dim_date, ...).
//   3. Create "fnTidyName" FIRST (dim_supplier uses it).
//   4. Close & Apply, then follow powerbi/03_model_and_report_guide.md.
// =====================================================================================


// ---------- fnTidyName  (function query) ---------------------------------------------
// Turns "WEST LONDON NHS TRUST" into "West London NHS Trust" (Text.Proper plus an acronym fix-up list).
let
    Acronyms = [Nhs = "NHS", Uk = "UK", Llp = "LLP", Plc = "PLC", Icb = "ICB", Cic = "CIC", Hmrc = "HMRC",
                Ict = "ICT", Hr = "HR", Pvt = "PVT", Gp = "GP", Llc = "LLC", Cnwl = "CNWL", Mgt = "MGT"],
    fn = (name as nullable text) as nullable text =>
        if name = null then null else
        Text.Combine(
            List.Transform(
                Text.Split(Text.Proper(name), " "),
                (w) => if Record.HasFields(Acronyms, w) then Record.Field(Acronyms, w) else w),
            " ")
in
    fn


// ---------- fact_payments -------------------------------------------------------------
let
    Source   = Csv.Document(File.Contents(DataFolder & "fact_payments.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Promoted, {
        {"payment_id", Int64.Type}, {"date_key", Int64.Type}, {"supplier_key", Int64.Type},
        {"directorate_key", Int64.Type}, {"service_area_key", Int64.Type}, {"spend_category_key", Int64.Type},
        {"purpose_key", Int64.Type}, {"expenditure_type", type text}, {"transaction_number", type text},
        {"source_supplier_id", type text}, {"source_supplier_name", type text}, {"source_period", type text},
        {"source_file", type text}, {"source_row", Int64.Type},
        {"amount", Currency.Type}, {"irrecoverable_vat", Currency.Type},
        {"is_credit_note", Int64.Type}, {"is_below_threshold", Int64.Type}, {"is_possible_duplicate_payment", Int64.Type}
    }, "en-GB")
in
    Typed


// ---------- dim_date  (mark as date table on [date] after loading) -------------------
let
    Source   = Csv.Document(File.Contents(DataFolder & "dim_date.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Promoted, {
        {"date_key", Int64.Type}, {"date", type date}, {"calendar_year", Int64.Type}, {"month_number", Int64.Type},
        {"month_name", type text}, {"year_month", type text}, {"financial_year", type text},
        {"financial_month_number", Int64.Type}, {"financial_quarter", Int64.Type},
        {"day_of_week", type text}, {"is_weekend", Int64.Type}
    }, "en-GB")
in
    Typed


// ---------- dim_supplier -------------------------------------------------------------
let
    Source   = Csv.Document(File.Contents(DataFolder & "dim_supplier.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Promoted, {
        {"supplier_key", Int64.Type}, {"supplier_entity_key", type text}, {"supplier_name", type text},
        {"is_redacted", Int64.Type}, {"supplier_type", type text}, {"name_variants", Int64.Type},
        {"supplier_id_count", Int64.Type}, {"supplier_ids", type text},
        {"first_payment_date", type date}, {"last_payment_date", type date}
    }, "en-GB"),
    // Display name: tidy case for real suppliers, one label for every redacted payee.
    Display  = Table.AddColumn(Typed, "supplier_display",
                    each if [is_redacted] = 1 then "Redacted personal data" else fnTidyName([supplier_name]), type text),
    // Used as a visual-level filter on rankings: "Is named supplier = Yes".
    Named    = Table.AddColumn(Display, "is_named_supplier", each if [is_redacted] = 1 then "No" else "Yes", type text)
in
    Named


// ---------- dim_directorate -----------------------------------------------------------
let
    Source   = Csv.Document(File.Contents(DataFolder & "dim_directorate.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Promoted, {{"directorate_key", Int64.Type}, {"directorate", type text}}, "en-GB")
in
    Typed


// ---------- dim_service_area ----------------------------------------------------------
let
    Source   = Csv.Document(File.Contents(DataFolder & "dim_service_area.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Promoted, {{"service_area_key", Int64.Type}, {"service_area", type text}}, "en-GB")
in
    Typed


// ---------- dim_spend_category --------------------------------------------------------
let
    Source   = Csv.Document(File.Contents(DataFolder & "dim_spend_category.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Promoted, {{"spend_category_key", Int64.Type}, {"spend_category", type text}, {"spend_theme", type text}}, "en-GB")
in
    Typed


// ---------- dim_purpose ---------------------------------------------------------------
let
    Source   = Csv.Document(File.Contents(DataFolder & "dim_purpose.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Promoted, {{"purpose_key", Int64.Type}, {"purpose", type text}}, "en-GB"),
    Proper   = Table.TransformColumns(Typed, {{"purpose", each Text.Proper(_), type text}})
in
    Proper


// ---------- dq_results ----------------------------------------------------------------
let
    Source   = Csv.Document(File.Contents(DataFolder & "dq_results.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Promoted, {
        {"check_id", type text}, {"dimension", type text}, {"check_name", type text},
        {"rows_affected", Int64.Type}, {"rows_total", Int64.Type}, {"pct_affected", type number},
        {"amount_affected", Currency.Type}, {"result", type text}, {"how_handled", type text}
    }, "en-GB")
in
    Typed


// ---------- dq_possible_duplicate_payments -------------------------------------------
let
    Source   = Csv.Document(File.Contents(DataFolder & "dq_possible_duplicate_payments.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Promoted, {
        {"payment_id", Int64.Type}, {"supplier_name", type text}, {"payment_date", type date}, {"amount", Currency.Type},
        {"transaction_number", type text}, {"source_file", type text}, {"source_row", Int64.Type}, {"lines_in_group", Int64.Type}
    }, "en-GB")
in
    Typed


// ---------- dq_supplier_id_conflicts --------------------------------------------------
let
    Source   = Csv.Document(File.Contents(DataFolder & "dq_supplier_id_conflicts.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Promoted, {
        {"source_supplier_id", type text}, {"distinct_suppliers", Int64.Type}, {"names_using_id", type text},
        {"payment_lines", Int64.Type}, {"total_amount", Currency.Type}
    }, "en-GB")
in
    Typed


// ---------- dq_multi_id_suppliers -----------------------------------------------------
let
    Source   = Csv.Document(File.Contents(DataFolder & "dq_multi_id_suppliers.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Promoted, {
        {"supplier_key", Int64.Type}, {"supplier_name", type text}, {"supplier_id_count", Int64.Type},
        {"supplier_ids", type text}, {"total_amount", Currency.Type}
    }, "en-GB")
in
    Typed


// ---------- excluded_rows -------------------------------------------------------------
let
    Source   = Csv.Document(File.Contents(DataFolder & "excluded_rows.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Promoted, {
        {"stg_id", Int64.Type}, {"source_file", type text}, {"source_period", type text}, {"source_row", Int64.Type},
        {"exclusion_reason", type text}, {"amount", Currency.Type}
    }, "en-GB")
in
    Typed


// ---------- ml_predictions  (optional page 5) ----------------------------------------
let
    Source   = Csv.Document(File.Contents(DataFolder & "ml_predictions.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Promoted, {
        {"payment_id", Int64.Type}, {"council_category", type text}, {"predicted_category", type text},
        {"confidence", type number}, {"predicted_theme", type text}, {"council_theme", type text},
        {"category_agrees", Int64.Type}, {"theme_agrees", Int64.Type}, {"review_flag", Int64.Type}
    }, "en-GB")
in
    Typed
