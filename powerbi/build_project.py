"""Generate the Power BI Project (PBIP) for the dashboard: semantic model (TMDL) + report (PBIR).

    python powerbi/build_project.py                       # DataFolder = <repo>/data/processed/
    python powerbi/build_project.py --data-folder "D:\\x\\data\\processed\\"

Open the result with Power BI Desktop:  File > Open > powerbi/council-spending.pbip, then Home > Refresh.
(To move the project to another machine, change the DataFolder parameter: Home > Transform data > Edit parameters.)

Single source of truth: the tables, relationships, measures and report pages are all defined in this file;
powerbi/02_measures.dax is regenerated from the same measure list so the docs can never drift.
"""
import argparse
import json
import shutil
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBI = ROOT / "powerbi"
MODEL = PBI / "council-spending.SemanticModel"
REPORT = PBI / "council-spending.Report"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"

GBP = "£#,0;-£#,0"
PCT = "0.0%"
INT = "#,0"

# ------------------------------------------------------------------------------------
# 1. Tables:  name -> list of (column, type, options)       type: int | text | num | date
#    options: h=hidden, f=format string, sort=sortByColumn, key=isKey
# ------------------------------------------------------------------------------------
TABLES = {
    "fact_payments": [
        ("payment_id", "int", dict(h=1)), ("date_key", "int", dict(h=1)), ("supplier_key", "int", dict(h=1)),
        ("directorate_key", "int", dict(h=1)), ("service_area_key", "int", dict(h=1)),
        ("spend_category_key", "int", dict(h=1)), ("purpose_key", "int", dict(h=1)),
        ("expenditure_type", "text", {}), ("transaction_number", "text", {}), ("source_supplier_id", "text", {}),
        ("source_supplier_name", "text", {}), ("source_period", "text", {}), ("source_file", "text", dict(h=1)),
        ("source_row", "int", dict(h=1)), ("amount", "num", dict(f=GBP)), ("irrecoverable_vat", "num", dict(f=GBP)),
        ("is_credit_note", "int", {}), ("is_below_threshold", "int", {}), ("is_possible_duplicate_payment", "int", {}),
    ],
    "dim_date": [
        ("date_key", "int", dict(h=1)), ("date", "date", dict(f="dd mmm yyyy", key=1)), ("calendar_year", "int", {}),
        ("month_number", "int", dict(h=1)), ("month_name", "text", dict(sort="month_number")),
        ("year_month", "text", {}), ("financial_year", "text", {}), ("financial_month_number", "int", dict(h=1)),
        ("financial_quarter", "int", {}), ("day_of_week", "text", {}), ("is_weekend", "int", {}),
    ],
    "dim_supplier": [
        ("supplier_key", "int", dict(h=1)), ("supplier_entity_key", "text", dict(h=1)), ("supplier_name", "text", {}),
        ("is_redacted", "int", {}), ("supplier_type", "text", {}), ("name_variants", "int", {}),
        ("supplier_id_count", "int", {}), ("supplier_ids", "text", {}),
        ("first_payment_date", "date", dict(f="dd mmm yyyy")), ("last_payment_date", "date", dict(f="dd mmm yyyy")),
        ("supplier_display", "text", {}), ("is_named_supplier", "text", {}),
    ],
    "dim_directorate": [("directorate_key", "int", dict(h=1)), ("directorate", "text", {})],
    "dim_service_area": [("service_area_key", "int", dict(h=1)), ("service_area", "text", {})],
    "dim_spend_category": [("spend_category_key", "int", dict(h=1)), ("spend_category", "text", {}), ("spend_theme", "text", {})],
    "dim_purpose": [("purpose_key", "int", dict(h=1)), ("purpose", "text", {})],
    "dq_results": [
        ("check_id", "text", {}), ("dimension", "text", {}), ("check_name", "text", {}), ("rows_affected", "int", dict(f=INT)),
        ("rows_total", "int", dict(f=INT)), ("pct_affected", "num", dict(f="0.00")), ("amount_affected", "num", dict(f=GBP)),
        ("result", "text", {}), ("how_handled", "text", {}),
    ],
    "dq_possible_duplicate_payments": [
        ("payment_id", "int", dict(h=1)), ("supplier_name", "text", {}), ("payment_date", "date", dict(f="dd mmm yyyy")),
        ("amount", "num", dict(f=GBP)), ("transaction_number", "text", {}), ("source_file", "text", {}),
        ("source_row", "int", {}), ("lines_in_group", "int", {}),
    ],
    "dq_supplier_id_conflicts": [
        ("source_supplier_id", "text", {}), ("distinct_suppliers", "int", {}), ("names_using_id", "text", {}),
        ("payment_lines", "int", {}), ("total_amount", "num", dict(f=GBP)),
    ],
    "dq_multi_id_suppliers": [
        ("supplier_key", "int", dict(h=1)), ("supplier_name", "text", {}), ("supplier_id_count", "int", {}),
        ("supplier_ids", "text", {}), ("total_amount", "num", dict(f=GBP)),
    ],
    "excluded_rows": [
        ("stg_id", "int", dict(h=1)), ("source_file", "text", {}), ("source_period", "text", {}), ("source_row", "int", {}),
        ("exclusion_reason", "text", {}), ("amount", "num", dict(f=GBP)),
    ],
    "ml_predictions": [
        ("payment_id", "int", dict(h=1)), ("council_category", "text", {}), ("predicted_category", "text", {}),
        ("confidence", "num", dict(f="0.00")), ("predicted_theme", "text", {}), ("council_theme", "text", {}),
        ("category_agrees", "int", {}), ("theme_agrees", "int", {}), ("review_flag", "int", {}),
    ],
}
M_TYPE = {"int": "Int64.Type", "text": "type text", "num": "type number", "date": "type date"}
TOM_TYPE = {"int": "int64", "text": "string", "num": "double", "date": "dateTime"}

# ------------------------------------------------------------------------------------
# 2. Measures: (name, DAX, format, display folder)
# ------------------------------------------------------------------------------------
MEASURES = [
    # ---- Core
    ("Net Spend", "SUM ( fact_payments[amount] )", GBP, "Core"),
    ("Gross Spend", "CALCULATE ( [Net Spend], fact_payments[amount] > 0 )", GBP, "Core"),
    ("Credit Notes", "CALCULATE ( [Net Spend], fact_payments[amount] < 0 )", GBP, "Core"),
    ("Payment Lines", "COUNTROWS ( fact_payments )", INT, "Core"),
    ("Average Payment", "DIVIDE ( [Net Spend], [Payment Lines] )", GBP, "Core"),
    ("Net Spend (Named Suppliers)", "CALCULATE ( [Net Spend], dim_supplier[is_redacted] = 0 )", GBP, "Core"),
    ("Named Suppliers", "CALCULATE ( DISTINCTCOUNT ( fact_payments[supplier_key] ), dim_supplier[is_redacted] = 0 )", INT, "Core"),
    ("Redacted Share %", "DIVIDE ( CALCULATE ( [Net Spend], dim_supplier[is_redacted] = 1 ), [Net Spend] )", PCT, "Core"),
    # ---- Time (financial year = April - March)
    ("Net Spend PM", "CALCULATE ( [Net Spend], DATEADD ( dim_date[date], -1, MONTH ) )", GBP, "Time"),
    ("MoM Change", "[Net Spend] - [Net Spend PM]", GBP, "Time"),
    ("MoM Change %", "DIVIDE ( [MoM Change], [Net Spend PM] )", PCT, "Time"),
    ("Net Spend FYTD",
     "VAR _fy = MAX ( dim_date[financial_year] ) VAR _max = MAX ( dim_date[date] ) "
     "RETURN CALCULATE ( [Net Spend], FILTER ( ALL ( dim_date ), dim_date[financial_year] = _fy && dim_date[date] <= _max ) )", GBP, "Time"),
    ("Rolling 3M Net Spend", "CALCULATE ( [Net Spend], DATESINPERIOD ( dim_date[date], MAX ( dim_date[date] ), -3, MONTH ) )", GBP, "Time"),
    # ---- Suppliers
    ("Supplier Rank",
     "IF ( HASONEVALUE ( dim_supplier[supplier_display] ), "
     "RANKX ( ALLSELECTED ( dim_supplier[supplier_display], dim_supplier[supplier_type] ), [Net Spend (Named Suppliers)], , DESC, DENSE ) )", "0", "Suppliers"),
    ("Share of Total %",
     "DIVIDE ( [Net Spend (Named Suppliers)], CALCULATE ( [Net Spend (Named Suppliers)], ALLSELECTED ( dim_supplier ) ) )", PCT, "Suppliers"),
    ("Cumulative Share %",
     "VAR _cur = [Net Spend (Named Suppliers)] VAR _all = ALLSELECTED ( dim_supplier[supplier_display] ) "
     "VAR _total = SUMX ( _all, [Net Spend (Named Suppliers)] ) "
     "RETURN DIVIDE ( SUMX ( FILTER ( _all, [Net Spend (Named Suppliers)] >= _cur ), [Net Spend (Named Suppliers)] ), _total )", PCT, "Suppliers"),
    ("Top 10 Suppliers Share %",
     "VAR _top10 = TOPN ( 10, ALLSELECTED ( dim_supplier[supplier_display] ), [Net Spend (Named Suppliers)], DESC ) "
     "RETURN DIVIDE ( SUMX ( _top10, [Net Spend (Named Suppliers)] ), CALCULATE ( [Net Spend (Named Suppliers)], ALLSELECTED ( dim_supplier ) ) )", PCT, "Suppliers"),
    ("Net Spend (Top 15 Suppliers)", "IF ( [Supplier Rank] <= 15, [Net Spend (Named Suppliers)] )", GBP, "Suppliers"),
    ("Cumulative Share % (Top 15)", "IF ( [Supplier Rank] <= 15, [Cumulative Share %] )", PCT, "Suppliers"),
    ("Named Payment Lines", "CALCULATE ( COUNTROWS ( fact_payments ), dim_supplier[is_redacted] = 0 )", INT, "Suppliers"),
    ("New Suppliers",
     "CALCULATE ( DISTINCTCOUNT ( dim_supplier[supplier_key] ), USERELATIONSHIP ( dim_supplier[first_payment_date], dim_date[date] ), dim_supplier[is_redacted] = 0 )",
     INT, "Suppliers"),
    ("One-Month Suppliers",
     "VAR _s = ADDCOLUMNS ( CALCULATETABLE ( VALUES ( dim_supplier[supplier_key] ), dim_supplier[is_redacted] = 0 ), "
     "\"@months\", CALCULATE ( COUNTROWS ( SUMMARIZE ( fact_payments, dim_date[year_month] ) ) ) ) RETURN COUNTROWS ( FILTER ( _s, [@months] = 1 ) ) + 0", INT, "Suppliers"),
    # ---- Data quality
    ("DQ Checks Passed", "COUNTROWS ( FILTER ( dq_results, dq_results[result] = \"PASS\" ) ) + 0", INT, "Data quality"),
    ("DQ Checks Warning", "COUNTROWS ( FILTER ( dq_results, dq_results[result] = \"WARN\" ) ) + 0", INT, "Data quality"),
    ("DQ Checks Failed", "COUNTROWS ( FILTER ( dq_results, dq_results[result] = \"FAIL\" ) ) + 0", INT, "Data quality"),
    ("DQ Pass Rate %", "DIVIDE ( [DQ Checks Passed], [DQ Checks Passed] + [DQ Checks Warning] + [DQ Checks Failed] )", PCT, "Data quality"),
    ("Rows Excluded", "COUNTROWS ( excluded_rows )", INT, "Data quality"),
    ("Possible Duplicate Payment Value", "CALCULATE ( [Net Spend], fact_payments[is_possible_duplicate_payment] = 1 )", GBP, "Data quality"),
    ("Credit Note Count", "CALCULATE ( [Payment Lines], fact_payments[is_credit_note] = 1 )", INT, "Data quality"),
    ("DQ Share Affected", "DIVIDE ( SUM ( dq_results[pct_affected] ), 100 )", "0.00%", "Data quality"),
    ("Reconciliation Status",
     "VAR _fail = [DQ Checks Failed] RETURN IF ( _fail = 0, \"Reconciled\", _fail & \" failed\" )", None, "Data quality"),
    # ---- Classification (optional page)
    ("ML Lines", "COUNTROWS ( ml_predictions )", INT, "Classification"),
    ("Model Theme Agreement %", "AVERAGE ( ml_predictions[theme_agrees] )", PCT, "Classification"),
    ("Model Category Agreement %", "AVERAGE ( ml_predictions[category_agrees] )", PCT, "Classification"),
    ("Lines For Coding Review", "SUM ( ml_predictions[review_flag] )", INT, "Classification"),
    ("Value For Coding Review", "CALCULATE ( [Net Spend], ml_predictions[review_flag] = 1 )", GBP, "Classification"),
]

# ------------------------------------------------------------------------------------
# 3. Relationships: (from table.column [many], to table.column [one], options)
# ------------------------------------------------------------------------------------
RELATIONSHIPS = [
    ("fact_payments.date_key", "dim_date.date_key", {}),
    ("fact_payments.supplier_key", "dim_supplier.supplier_key", {}),
    ("fact_payments.directorate_key", "dim_directorate.directorate_key", {}),
    ("fact_payments.service_area_key", "dim_service_area.service_area_key", {}),
    ("fact_payments.spend_category_key", "dim_spend_category.spend_category_key", {}),
    ("fact_payments.purpose_key", "dim_purpose.purpose_key", {}),
    ("dim_supplier.first_payment_date", "dim_date.date", dict(inactive=1)),
    ("ml_predictions.payment_id", "fact_payments.payment_id", dict(one_to_one=1)),
]

FN_TIDY_NAME = '''let
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
    fn'''


# ====================================================================================
# helpers
# ====================================================================================
def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def wjson(path: Path, obj) -> None:
    write(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def q(name: str) -> str:
    """TMDL identifier quoting."""
    return f"'{name}'" if any(c in name for c in " -()%&.,/") else name


T = "\t"


# ====================================================================================
# semantic model
# ====================================================================================
def table_m(table: str, cols, data_folder_expr="DataFolder") -> str:
    types = ", ".join(f'{{"{c}", {M_TYPE[t]}}}' for c, t, _ in cols if not (table == "dim_supplier" and c in ("supplier_display", "is_named_supplier")))
    steps = [
        f'Source = Csv.Document(File.Contents({data_folder_expr} & "{table}.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv])',
        "Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true])",
        f'Typed = Table.TransformColumnTypes(Promoted, {{{types}}}, "en-GB")',
    ]
    last = "Typed"
    if table == "dim_supplier":
        steps += [
            'Display = Table.AddColumn(Typed, "supplier_display", each if [is_redacted] = 1 then "Redacted personal data" else fnTidyName([supplier_name]), type text)',
            'Named = Table.AddColumn(Display, "is_named_supplier", each if [is_redacted] = 1 then "No" else "Yes", type text)',
        ]
        last = "Named"
    if table == "dim_purpose":
        steps.append('Proper = Table.TransformColumns(Typed, {{"purpose", each Text.Proper(_), type text}})')
        last = "Proper"
    body = ",\n".join(f"{T*5}{s}" for s in steps)
    return f"{T*4}let\n{body}\n{T*4}in\n{T*5}{last}"


def table_tmdl(name: str, cols) -> str:
    out = [f"table {q(name)}"]
    if name == "dim_date":
        out.append(f"{T}dataCategory: Time")
    out.append("")
    for c, t, o in cols:
        out.append(f"{T}column {q(c)}")
        out.append(f"{T*2}dataType: {TOM_TYPE[t]}")
        if o.get("f"):
            out.append(f"{T*2}formatString: {o['f']}")
        elif t == "int":
            out.append(f"{T*2}formatString: 0")
        if o.get("h"):
            out.append(f"{T*2}isHidden")
        if o.get("key"):
            out.append(f"{T*2}isKey")
        out.append(f"{T*2}summarizeBy: none")
        out.append(f"{T*2}sourceColumn: {c}")
        if o.get("sort"):
            out.append(f"{T*2}sortByColumn: {q(o['sort'])}")
        out.append("")
    out.append(f"{T}partition {q(name)} = m")
    out.append(f"{T*2}mode: import")
    out.append(f"{T*2}source =")
    out.append(table_m(name, cols))
    out.append("")
    return "\n".join(out)


def measures_table_tmdl() -> str:
    out = ["table _Measures", f"{T}lineageTag: {uuid.uuid5(uuid.NAMESPACE_URL, '_Measures')}", ""]
    for name, dax, fmt, folder in MEASURES:
        out.append(f"{T}measure {q(name)} = {dax}")
        if fmt:
            out.append(f"{T*2}formatString: {fmt}")
        out.append(f"{T*2}displayFolder: {folder}")
        out.append("")
    out += [f"{T}column Hidden", f"{T*2}dataType: int64", f"{T*2}isHidden", f"{T*2}summarizeBy: none", f"{T*2}sourceColumn: Hidden", "",
            f"{T}partition _Measures = m", f"{T*2}mode: import", f"{T*2}source =",
            f"{T*4}let", f"{T*5}Source = #table(type table [Hidden = Int64.Type], {{}})", f"{T*4}in", f"{T*5}Source", ""]
    return "\n".join(out)


def relationships_tmdl() -> str:
    out = []
    for frm, to, o in RELATIONSHIPS:
        out.append(f"relationship {uuid.uuid5(uuid.NAMESPACE_URL, frm + '>' + to)}")
        if o.get("inactive"):
            out.append(f"{T}isActive: false")
        if o.get("one_to_one"):
            out.append(f"{T}fromCardinality: one")
            out.append(f"{T}crossFilteringBehavior: bothDirections")
        ft, fc = frm.split(".")
        tt, tc = to.split(".")
        out.append(f"{T}fromColumn: {q(ft)}.{q(fc)}")
        out.append(f"{T}toColumn: {q(tt)}.{q(tc)}")
        out.append("")
    return "\n".join(out)


def build_model(data_folder: str) -> None:
    if MODEL.exists():
        shutil.rmtree(MODEL)
    write(MODEL / "definition.pbism", json.dumps({"version": "4.2", "settings": {}}, indent=2) + "\n")
    wjson(MODEL / ".pbi" / "editorSettings.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/editorSettings/1.0.0/schema.json",
        "parallelQueryLoading": True, "autodetectRelationships": False})
    write(MODEL / "definition" / "database.tmdl", "database\n\tcompatibilityLevel: 1601\n")
    tables = list(TABLES) + ["_Measures"]
    model = ["model Model", f"{T}culture: en-GB", f"{T}defaultPowerBIDataSourceVersion: powerBI_V3",
             f"{T}discourageImplicitMeasures", f"{T}sourceQueryCulture: en-GB", ""]
    model += [f"ref table {q(t)}" for t in tables] + ["", "ref expression DataFolder", "ref expression fnTidyName", ""]
    write(MODEL / "definition" / "model.tmdl", "\n".join(model))
    folder_val = data_folder.replace('"', '""')
    exprs = [
        f'expression DataFolder = "{folder_val}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]',
        f"{T}lineageTag: {uuid.uuid5(uuid.NAMESPACE_URL, 'DataFolder')}", "",
        "expression fnTidyName =", *[f"{T*2}{ln}" for ln in FN_TIDY_NAME.splitlines()], f"{T}lineageTag: {uuid.uuid5(uuid.NAMESPACE_URL, 'fnTidyName')}", "",
    ]
    write(MODEL / "definition" / "expressions.tmdl", "\n".join(exprs))
    for name, cols in TABLES.items():
        write(MODEL / "definition" / "tables" / f"{name}.tmdl", table_tmdl(name, cols))
    write(MODEL / "definition" / "tables" / "_Measures.tmdl", measures_table_tmdl())
    write(MODEL / "definition" / "relationships.tmdl", relationships_tmdl())


# ====================================================================================
# report (PBIR)
# ====================================================================================
def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def s(text):  # string literal
    return lit("'" + text.replace("'", "''") + "'")


TRUE, FALSE = lit("true"), lit("false")


def col(entity, prop):
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def mea(prop, entity="_Measures"):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def proj(field, entity, prop, active=True, display=None):
    d = {"field": field, "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}
    if active:
        d["active"] = True
    if display:
        d["displayName"] = display
    return d


def C(entity, prop, display=None):
    return proj(col(entity, prop), entity, prop, display=display), col(entity, prop)


def M(prop, display=None):
    return proj(mea(prop), "_Measures", prop, display=display), mea(prop)


class Page:
    def __init__(self, name, title):
        self.name, self.title, self.visuals = name, title, []

    def next_id(self):
        return uuid.uuid5(uuid.NAMESPACE_URL, f"council-spending/{self.name}/{len(self.visuals)}").hex[:20]

    def add(self, vtype, x, y, w, h, roles, *, title=None, sort=None, objects=None, container=None, filters=None,
            sync=None, name=None):
        """roles: {role: [(projection, field), ...]}   sort: (field, 'Descending'|'Ascending')"""
        vid = name or self.next_id()
        qs = {r: {"projections": [p for p, _ in items]} for r, items in roles.items()}
        visual = {"visualType": vtype, "query": {"queryState": qs}, "drillFilterOtherVisuals": True}
        if sort:
            visual["query"]["sortDefinition"] = {"sort": [{"field": sort[0], "direction": sort[1]}], "isDefaultSort": True}
        if objects:
            visual["objects"] = objects
        vco = dict(container or {})
        if title:
            vco["title"] = [{"properties": {"show": TRUE, "text": s(title)}}]
        if vco:
            visual["visualContainerObjects"] = vco
        if sync:
            visual["syncGroup"] = {"groupName": sync, "fieldChanges": True, "filterChanges": True}
        v = {"$schema": f"{SCHEMA}/visualContainer/2.12.0/schema.json", "name": vid,
             "position": {"x": x, "y": y, "z": len(self.visuals) * 10, "height": h, "width": w, "tabOrder": len(self.visuals) * 10},
             "visual": visual}
        if filters:
            v["filterConfig"] = {"filters": filters}
        self.visuals.append(v)

    def textbox(self, x, y, w, h, text, size="11pt", bold=False, color="#444444"):
        run = {"value": text, "textStyle": {"fontSize": size, "color": color, **({"fontWeight": "bold"} if bold else {})}}
        self.visuals.append({
            "$schema": f"{SCHEMA}/visualContainer/2.12.0/schema.json", "name": self.next_id(),
            "position": {"x": x, "y": y, "z": len(self.visuals) * 10, "height": h, "width": w, "tabOrder": len(self.visuals) * 10},
            "visual": {"visualType": "textbox",
                       "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [run]}]}}]},
                       "visualContainerObjects": {"background": [{"properties": {"show": FALSE}}], "border": [{"properties": {"show": FALSE}}]}},
        })


CARD_UNITS = {"money": ("1000000D", "1L"), "count": ("1D", "0L"), "pct": ("1D", "1L"), "auto": (None, None), "text": (None, None)}


def card(page, x, y, w, h, measure, title, kind="auto", **kw):
    props = {"fontSize": lit("12D" if kind == "text" else "22D")}
    units, prec = CARD_UNITS[kind]
    if units:
        props["labelDisplayUnits"], props["labelPrecision"] = lit(units), lit(prec)
    page.add("card", x, y, w, h, {"Values": [M(measure)]}, title=title,
             objects={"labels": [{"properties": props}], "categoryLabels": [{"properties": {"show": FALSE}}]}, **kw)


def slicer(page, x, y, w, h, entity, prop, title, dropdown=True, sync=None):
    objs = {"data": [{"properties": {"mode": s("Dropdown")}}]} if dropdown else {}
    page.add("slicer", x, y, w, h, {"Values": [C(entity, prop)]}, title=title, objects=objs or None, sync=sync)


def header(page, subtitle):
    page.textbox(20, 2, 900, 44, "Hounslow council payments over £500", "18pt", True, "#2F5D8A")
    page.textbox(20, 40, 1240, 26, subtitle, "9pt", False, "#666666")
    page.textbox(20, 692, 1240, 26, "Source: London Borough of Hounslow, Invoices over £500, data.gov.uk. Open Government Licence v3.0. "
                 "Apr 2025 - May 2026. Payments over £500 only - not total council expenditure.", "7pt", False, "#888888")


def labels(units="1000000D", precision="1L"):
    return {"labels": [{"properties": {"show": TRUE, "labelDisplayUnits": lit(units), "labelPrecision": lit(precision)}}]}


def in_filter(entity, prop, values, numeric=False):
    vals = [[{"Literal": {"Value": (f"{v}L" if numeric else "'" + v + "'")}}] for v in values]
    return {"name": uuid.uuid5(uuid.NAMESPACE_URL, f"filter/{entity}/{prop}").hex[:20], "field": col(entity, prop), "type": "Categorical",
            "filter": {"Version": 2, "From": [{"Name": "t", "Entity": entity, "Type": 0}],
                       "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": prop}}],
                                                       "Values": vals}}}]}}


CARD_KIND = {"Net Spend": "money", "Gross Spend": "money", "Credit Notes": "money", "Value For Coding Review": "money",
             "Payment Lines": "count", "Named Suppliers": "count", "One-Month Suppliers": "count", "Rows Excluded": "count",
             "DQ Checks Passed": "count", "DQ Checks Warning": "count", "DQ Checks Failed": "count", "Lines For Coding Review": "count",
             "Top 10 Suppliers Share %": "pct", "Redacted Share %": "pct", "DQ Pass Rate %": "pct",
             "Model Theme Agreement %": "pct", "Model Category Agreement %": "pct", "Reconciliation Status": "text"}


def build_pages():
    FY = "fy"
    pages = []

    # ---- Page 1: Overview ---------------------------------------------------------
    p = Page("overview", "Overview"); pages.append(p)
    header(p, "Overview: where the money goes, month by month. Use the slicers to filter every visual on the page.")
    slicer(p, 20, 64, 200, 56, "dim_date", "financial_year", "Financial year", sync=FY)
    slicer(p, 230, 64, 200, 56, "dim_date", "year_month", "Month")
    slicer(p, 440, 64, 200, 56, "fact_payments", "expenditure_type", "Expenditure type")
    slicer(p, 650, 64, 400, 56, "dim_directorate", "directorate", "Directorate")
    for i, (m, t) in enumerate([("Net Spend", "Net spend"), ("Gross Spend", "Gross spend"), ("Credit Notes", "Credit notes"),
                                ("Payment Lines", "Payment lines"), ("Named Suppliers", "Named suppliers"), ("Average Payment", "Average payment")]):
        card(p, 20 + i * 207, 128, 195, 84, m, t, kind=CARD_KIND.get(m, "auto"))
    p.add("columnChart", 20, 224, 760, 232,
          {"Category": [C("dim_date", "year_month")], "Series": [C("dim_spend_category", "spend_theme")], "Y": [M("Net Spend")]},
          title="Monthly net spend by theme",
          objects={"legend": [{"properties": {"show": TRUE, "position": s("Bottom"), "showTitle": FALSE}}]})
    p.add("clusteredBarChart", 795, 224, 465, 464,
          {"Category": [C("dim_directorate", "directorate")], "Y": [M("Net Spend")]},
          title="Net spend by directorate", sort=(mea("Net Spend"), "Descending"), objects=labels())
    p.add("clusteredBarChart", 20, 466, 375, 222,
          {"Category": [C("dim_spend_category", "spend_theme")], "Y": [M("Net Spend")]},
          title="Net spend by theme", sort=(mea("Net Spend"), "Descending"), objects=labels())
    p.add("clusteredColumnChart", 405, 466, 375, 222,
          {"Category": [C("dim_date", "year_month")], "Y": [M("MoM Change %")]},
          title="Month-on-month change in net spend", objects=labels("1D", "0L"))

    # ---- Page 2: Suppliers --------------------------------------------------------
    p = Page("suppliers", "Suppliers"); pages.append(p)
    header(p, "Suppliers: concentration, tail spend and churn. Redacted (personal-data) payees are excluded from every ranking on this page.")
    slicer(p, 20, 64, 200, 56, "dim_date", "financial_year", "Financial year", sync=FY)
    slicer(p, 230, 64, 260, 56, "dim_supplier", "supplier_type", "Supplier type")
    for i, (m, t) in enumerate([("Top 10 Suppliers Share %", "Top 10 suppliers' share"), ("Named Suppliers", "Named suppliers"),
                                ("One-Month Suppliers", "Paid in one month only"), ("Redacted Share %", "Redacted payees' share"),
                                ("Average Payment", "Average payment")]):
        card(p, 20 + i * 248, 128, 236, 84, m, t, kind=CARD_KIND.get(m, "auto"))
    p.add("lineClusteredColumnComboChart", 20, 224, 720, 258,
          {"Category": [C("dim_supplier", "supplier_display")], "Y": [M("Net Spend (Top 15 Suppliers)")], "Y2": [M("Cumulative Share % (Top 15)")]},
          title="Top 15 suppliers: net spend and cumulative share of named-supplier spend",
          sort=(mea("Net Spend (Top 15 Suppliers)"), "Descending"))
    p.add("clusteredBarChart", 755, 224, 505, 258,
          {"Category": [C("dim_supplier", "supplier_type")], "Y": [M("Net Spend")]},
          title="Net spend by supplier type (name-based heuristic)", sort=(mea("Net Spend"), "Descending"), objects=labels())
    p.add("tableEx", 20, 492, 740, 196,
          {"Values": [M("Supplier Rank", "Rank"), C("dim_supplier", "supplier_display", "Supplier"), C("dim_supplier", "supplier_type", "Type"),
                      M("Net Spend (Named Suppliers)", "Net spend"), M("Share of Total %", "Share"), M("Named Payment Lines", "Lines")]},
          title="Named suppliers ranked by net spend", sort=(mea("Net Spend (Named Suppliers)"), "Descending"))
    p.add("clusteredColumnChart", 775, 492, 485, 196,
          {"Category": [C("dim_date", "year_month")], "Y": [M("New Suppliers")]},
          title="New suppliers by first-payment month (Apr 2025 = baseline)", objects=labels("1D", "0L"))

    # ---- Page 3: Categories & directorates ---------------------------------------
    p = Page("categories", "Categories"); pages.append(p)
    header(p, "Categories and directorates: who spends what, and on what.")
    slicer(p, 20, 64, 200, 56, "dim_date", "financial_year", "Financial year", sync=FY)
    slicer(p, 230, 64, 220, 56, "fact_payments", "expenditure_type", "Expenditure type")
    slicer(p, 460, 64, 400, 56, "dim_directorate", "directorate", "Directorate")
    p.add("pivotTable", 20, 130, 760, 300,
          {"Rows": [C("dim_directorate", "directorate")], "Columns": [C("dim_spend_category", "spend_theme")], "Values": [M("Net Spend")]},
          title="Net spend: directorate x theme")
    p.add("treemap", 795, 130, 465, 300,
          {"Group": [C("dim_spend_category", "spend_category")], "Values": [M("Net Spend")]}, title="Net spend by spend category")
    p.add("clusteredBarChart", 20, 442, 420, 246,
          {"Category": [C("dim_service_area", "service_area")], "Y": [M("Net Spend")]},
          title="Net spend by service area", sort=(mea("Net Spend"), "Descending"), objects=labels())
    p.add("clusteredColumnChart", 450, 442, 330, 246,
          {"Category": [C("dim_date", "financial_year")], "Series": [C("fact_payments", "expenditure_type")], "Y": [M("Net Spend")]},
          title="Capital vs revenue vs HRA by financial year", objects={"legend": [{"properties": {"show": TRUE, "position": s("Bottom"), "showTitle": FALSE}}]})
    p.add("tableEx", 795, 442, 465, 246,
          {"Values": [C("dim_purpose", "purpose", "Purpose"), M("Net Spend", "Net spend"), M("Payment Lines", "Lines")]},
          title="Purpose of payment", sort=(mea("Net Spend"), "Descending"))

    # ---- Page 4: Data quality -----------------------------------------------------
    p = Page("data_quality", "Data quality"); pages.append(p)
    header(p, "Data quality: 22 automated checks. Rows are never dropped silently: staged rows = loaded rows + excluded rows, and the GBP totals reconcile.")
    for i, (m, t) in enumerate([("DQ Checks Passed", "Checks passed"), ("DQ Checks Warning", "Warnings"), ("DQ Checks Failed", "Failures"),
                                ("DQ Pass Rate %", "Pass rate (excl. info)"), ("Rows Excluded", "Rows excluded"),
                                ("Reconciliation Status", "Reconciliation")]):
        card(p, 20 + i * 207, 66, 195, 80, m, t, kind=CARD_KIND.get(m, "auto"))
    cf = lambda res, colr: {"Condition": {"Comparison": {"ComparisonKind": 0, "Left": col("dq_results", "result"), "Right": {"Literal": {"Value": f"'{res}'"}}}},
                            "Value": {"Literal": {"Value": f"'{colr}'"}}}
    result_cf = [{"properties": {"fontColor": {"solid": {"color": {"expr": {"Conditional": {"Cases": [
        cf("PASS", "#4C9F70"), cf("WARN", "#B8860B"), cf("FAIL", "#B5484C"), cf("INFO", "#7A7A7A")]}}}}}},
        "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": "dq_results.result"}}]
    p.add("tableEx", 20, 156, 870, 330,
          {"Values": [C("dq_results", "check_id", "ID"), C("dq_results", "dimension", "Dimension"), C("dq_results", "check_name", "Check"),
                      C("dq_results", "rows_affected", "Rows"), C("dq_results", "pct_affected", "% affected"),
                      C("dq_results", "result", "Result"), C("dq_results", "how_handled", "How handled")]},
          title="Data-quality scorecard", sort=(col("dq_results", "check_id"), "Ascending"), objects={"values": result_cf})
    p.add("clusteredBarChart", 905, 156, 355, 330,
          {"Category": [C("dq_results", "check_id")], "Y": [M("DQ Share Affected")]},
          title="% of rows or suppliers affected (warnings and failures)",
          sort=(mea("DQ Share Affected"), "Descending"), objects=labels("1D", "2L"), filters=[in_filter("dq_results", "result", ["WARN", "FAIL"])])
    p.add("tableEx", 20, 496, 410, 192,
          {"Values": [C("dq_possible_duplicate_payments", "supplier_name", "Supplier"), C("dq_possible_duplicate_payments", "payment_date", "Date"),
                      C("dq_possible_duplicate_payments", "amount", "Amount")]},
          title="Possible duplicate payments (review list)", sort=(col("dq_possible_duplicate_payments", "amount"), "Descending"))
    p.add("tableEx", 440, 496, 410, 192,
          {"Values": [C("dq_supplier_id_conflicts", "source_supplier_id", "Supplier ID"), C("dq_supplier_id_conflicts", "names_using_id", "Names using this ID"),
                      C("dq_supplier_id_conflicts", "total_amount", "Amount")]},
          title="Supplier IDs used by different suppliers", sort=(col("dq_supplier_id_conflicts", "total_amount"), "Descending"))
    p.add("tableEx", 860, 496, 400, 192,
          {"Values": [C("dq_multi_id_suppliers", "supplier_name", "Supplier"), C("dq_multi_id_suppliers", "supplier_ids", "Supplier IDs"),
                      C("dq_multi_id_suppliers", "total_amount", "Amount")]},
          title="Suppliers held under several IDs", sort=(col("dq_multi_id_suppliers", "total_amount"), "Descending"))

    # ---- Page 5: Classification ---------------------------------------------------
    p = Page("classification", "Classification"); pages.append(p)
    header(p, "Optional extra: a text-classification model (supplier-grouped cross-validation) vs the council's own coding. Disagreements are audit leads, not proven errors.")
    for i, (m, t) in enumerate([("Model Theme Agreement %", "Theme agreement"), ("Model Category Agreement %", "Category agreement"),
                                ("Lines For Coding Review", "Lines for coding review"), ("Value For Coding Review", "Net value for review")]):
        card(p, 20 + i * 310, 66, 295, 80, m, t, kind=CARD_KIND.get(m, "auto"))
    p.add("pivotTable", 20, 156, 800, 330,
          {"Rows": [C("ml_predictions", "council_theme")], "Columns": [C("ml_predictions", "predicted_theme")], "Values": [M("ML Lines")]},
          title="Council theme (rows) vs model theme (columns): the diagonal is agreement")
    p.add("tableEx", 835, 156, 425, 330,
          {"Values": [C("dim_supplier", "supplier_display", "Supplier"), M("Net Spend", "Net spend"),
                      C("ml_predictions", "council_category", "Council category"), C("ml_predictions", "predicted_category", "Model category")]},
          title="Coding review queue (confident disagreements, over £1,000)", sort=(mea("Net Spend"), "Descending"),
          filters=[in_filter("ml_predictions", "review_flag", [1], numeric=True)])
    p.add("clusteredBarChart", 20, 496, 800, 192,
          {"Category": [C("ml_predictions", "council_theme")], "Y": [M("Model Theme Agreement %")]},
          title="Model agreement with the council's coding, by theme", objects=labels("1D", "0L"),
          sort=(mea("Model Theme Agreement %"), "Descending"))
    p.textbox(835, 496, 425, 192,
              "How to read this page: the model is trained on the council's own coding, so it learns the council's habits. "
              "Where it confidently disagrees on a large payment, the line is worth asking the council about - it may be a coding error, "
              "or the supplier may legitimately supply several categories.", "10pt", False, "#444444")
    return pages


def build_report() -> None:
    if REPORT.exists():
        shutil.rmtree(REPORT)
    wjson(REPORT / "definition.pbir", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": "../council-spending.SemanticModel"}}})
    d = REPORT / "definition"
    wjson(d / "version.json", {"$schema": f"{SCHEMA}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    ver = {"visual": "2.12.0", "page": "2.1.0", "report": "3.3.0"}
    wjson(d / "report.json", {
        "$schema": f"{SCHEMA}/report/3.3.0/schema.json",
        "themeCollection": {"customTheme": {"name": "CouncilSpending.json", "reportVersionAtImport": ver, "type": "RegisteredResources"}},
        "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources",
                              "items": [{"name": "CouncilSpending.json", "path": "CouncilSpending.json", "type": "CustomTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "defaultFilterActionIsDataFilter": True}})
    (REPORT / "StaticResources" / "RegisteredResources").mkdir(parents=True, exist_ok=True)
    shutil.copy(PBI / "theme.json", REPORT / "StaticResources" / "RegisteredResources" / "CouncilSpending.json")
    pages = build_pages()
    wjson(d / "pages" / "pages.json", {"$schema": f"{SCHEMA}/pagesMetadata/1.1.0/schema.json",
                                       "pageOrder": [pg.name for pg in pages], "activePageName": pages[0].name})
    for pg in pages:
        wjson(d / "pages" / pg.name / "page.json", {"$schema": f"{SCHEMA}/page/2.1.0/schema.json", "name": pg.name,
                                                   "displayName": pg.title, "displayOption": "FitToPage", "height": 720, "width": 1280})
        for v in pg.visuals:
            wjson(d / "pages" / pg.name / "visuals" / v["name"] / "visual.json", v)
    wjson(PBI / "council-spending.pbip", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
                                          "version": "1.0", "artifacts": [{"report": {"path": "council-spending.Report"}}],
                                          "settings": {"enableAutoRecovery": True}})
    write(PBI / ".gitignore", "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")


def write_dax_doc() -> None:
    lines = ["// =====================================================================================",
             "// 02_measures.dax  -  AUTO-GENERATED by powerbi/build_project.py (do not edit by hand).",
             "// These measures are already inside council-spending.pbip; this file is for reading / manual builds.",
             "// They live on the hidden helper table _Measures.", "// ====================================================================================="]
    folder = None
    for name, dax, fmt, f in MEASURES:
        if f != folder:
            lines += ["", f"// ---------- {f} ----------"]
            folder = f
        lines.append(f"{name} =\n    {dax}\n")
    write(PBI / "02_measures.dax", "\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-folder", default=str(ROOT / "data" / "processed") + "\\")
    a = ap.parse_args()
    df = a.data_folder if a.data_folder.endswith(("\\", "/")) else a.data_folder + "\\"
    build_model(df)
    build_report()
    write_dax_doc()
    nvis = sum(len(p.visuals) for p in build_pages())
    print(f"Built {PBI / 'council-spending.pbip'}  ({len(TABLES)+1} tables, {len(MEASURES)} measures, 5 pages, {nvis} visuals)")
    print(f"DataFolder = {df}")


if __name__ == "__main__":
    main()
