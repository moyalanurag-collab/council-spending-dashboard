"""Run sql/05_analysis_queries.sql, draw preview charts (docs/images/) and write docs/findings.md.

Every number in findings.md is computed here, so the write-up can never drift from the data.
"""
import re
import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "council_spending.db"
SQL_PATH = ROOT / "sql" / "05_analysis_queries.sql"
IMG_DIR = ROOT / "docs" / "images"
OUT_MD = ROOT / "docs" / "findings.md"

PALETTE = ["#2F5D8A", "#E07B39", "#4C9F70", "#B5484C", "#8A6BB0", "#C9A227", "#3C9DB0", "#7A7A7A", "#D98BA5"]
INK, GRID = "#222222", "#E6E6E6"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "axes.edgecolor": GRID, "axes.labelcolor": INK, "xtick.color": INK,
    "ytick.color": INK, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "axes.axisbelow": True, "figure.dpi": 130,
})
gbp_m = FuncFormatter(lambda v, _: f"£{v/1e6:,.0f}m")


def load_queries() -> dict[str, str]:
    text = SQL_PATH.read_text(encoding="utf-8")
    parts = re.split(r"^-- name: (\w+)\s*$", text, flags=re.M)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


def md_table(df: pd.DataFrame, fmt: dict[str, str] | None = None) -> str:
    fmt = fmt or {}
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---:" if pd.api.types.is_numeric_dtype(df[c]) else "---" for c in cols) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(("" if pd.isna(r[c]) else format(r[c], fmt[c]) if c in fmt else str(r[c])) for c in cols) + " |")
    return "\n".join(lines)


def main() -> None:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        q = {name: pd.read_sql(sql, con) for name, sql in load_queries().items()}
        dq = pd.read_sql("SELECT * FROM dq_results", con)
        ml = pd.read_sql("SELECT review_flag, category_agrees, theme_agrees FROM ml_predictions", con) \
            if con.execute("SELECT name FROM sqlite_master WHERE name='ml_predictions'").fetchone() else None

    k = q["kpis"].iloc[0]

    # ---- chart 1: monthly spend stacked by theme -----------------------------------
    piv = q["monthly_by_theme"].pivot(index="year_month", columns="spend_theme", values="net_spend").fillna(0)
    piv = piv[piv.sum().sort_values(ascending=False).index]
    fig, ax = plt.subplots(figsize=(10, 4.8))
    bottom = pd.Series(0.0, index=piv.index)
    for i, col in enumerate(piv.columns):
        ax.bar(piv.index, piv[col].clip(lower=0), bottom=bottom, label=col, color=PALETTE[i % len(PALETTE)], width=0.75)
        bottom += piv[col].clip(lower=0)
    ax.yaxis.set_major_formatter(gbp_m)
    ax.set_title("Monthly payments over £500 by spend theme", loc="left", fontsize=12, color=INK)
    ax.tick_params(axis="x", rotation=45)
    ax.legend(frameon=False, fontsize=7.5, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.22))
    fig.tight_layout(); fig.savefig(IMG_DIR / "monthly_spend_by_theme.png"); plt.close(fig)

    # ---- chart 2: top suppliers ----------------------------------------------------
    top = q["top_suppliers"].head(10).iloc[::-1]
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.barh(top["supplier_name"].str.title().str.slice(0, 40), top["net_spend"], color=PALETTE[0])
    for y, v in enumerate(top["net_spend"]):
        ax.text(v, y, f" £{v/1e6:,.1f}m", va="center", fontsize=8, color=INK)
    ax.xaxis.set_major_formatter(gbp_m); ax.grid(axis="y", visible=False)
    ax.set_title("Top 10 named suppliers by net spend", loc="left", fontsize=12, color=INK)
    fig.tight_layout(); fig.savefig(IMG_DIR / "top_suppliers.png"); plt.close(fig)

    # ---- chart 3: spend by theme ---------------------------------------------------
    th = q["monthly_by_theme"].groupby("spend_theme")["net_spend"].sum().sort_values()
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.barh(th.index, th.values, color=PALETTE[2])
    for y, v in enumerate(th.values):
        ax.text(v, y, f" £{v/1e6:,.1f}m ({100*v/th.sum():.0f}%)", va="center", fontsize=8, color=INK)
    ax.xaxis.set_major_formatter(gbp_m); ax.grid(axis="y", visible=False); ax.set_xlim(0, th.max() * 1.25)
    ax.set_title("Net spend by theme", loc="left", fontsize=12, color=INK)
    fig.tight_layout(); fig.savefig(IMG_DIR / "spend_by_theme.png"); plt.close(fig)

    # ---- chart 4: data-quality scorecard -------------------------------------------
    flagged = dq[dq["result"].isin(["WARN", "FAIL"])].sort_values("pct_affected", ascending=True)
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.barh(flagged["check_id"] + "  " + flagged["check_name"].str.slice(0, 62), flagged["pct_affected"].fillna(0), color=PALETTE[1])
    for y, v in enumerate(flagged["pct_affected"].fillna(0)):
        ax.text(v, y, f" {v:.2f}%", va="center", fontsize=8, color=INK)
    ax.grid(axis="y", visible=False); ax.set_xlim(0, max(flagged["pct_affected"].max() * 1.2, 1))
    ax.set_title("Data-quality checks that raised a warning (% of rows or suppliers affected)", loc="left", fontsize=11, color=INK)
    fig.tight_layout(); fig.savefig(IMG_DIR / "data_quality_warnings.png"); plt.close(fig)

    # ---- findings.md ---------------------------------------------------------------
    c = q["supplier_concentration"].iloc[0]
    o = q["one_off_suppliers"].iloc[0]
    st = q["by_supplier_type"]
    mom = q["monthly_mom"]
    peak, trough = mom.loc[mom["net_spend"].idxmax()], mom.loc[mom["net_spend"].idxmin()]
    redacted = dq.loc[dq.check_id == "DQ21"].iloc[0]
    ml_text = ""
    if ml is not None:
        ml_text = (f"\n## Optional extra: text classification\n"
                   f"A supplier-grouped cross-validated classifier recovers the council's spend category for "
                   f"**{ml['category_agrees'].mean():.0%}** of lines and its spend *theme* for **{ml['theme_agrees'].mean():.0%}** "
                   f"(majority-class baseline is far lower). It flags **{int(ml['review_flag'].sum()):,}** lines for coding review. "
                   f"Details: [classification_report.md](classification_report.md).\n")

    OUT_MD.write_text(f"""# Findings (auto-generated by `src/findings.py`)

Period: **{k.first_payment} to {k.last_payment}** | Source: London Borough of Hounslow, *Invoices over £500* (Open Government Licence v3.0).

## Headline numbers
| KPI | Value |
|---|---:|
| Net spend (after credit notes) | £{k.net_spend:,.0f} |
| Gross spend (positive payments) | £{k.gross_spend:,.0f} |
| Credit notes / refunds | -£{abs(k.credit_notes):,.0f} |
| Payment lines | {k.payment_lines:,.0f} |
| Distinct named suppliers | {k.suppliers:,.0f} |
| Average payment line | £{k.avg_payment:,.0f} |

![Monthly spend by theme](images/monthly_spend_by_theme.png)

Highest month: **{peak.year_month}** (£{peak.net_spend:,.0f}); lowest: **{trough.year_month}** (£{trough.net_spend:,.0f}).

## Spend by theme
![Spend by theme](images/spend_by_theme.png)

## Supplier concentration
* Top 10 named suppliers receive **{c.top10_share_pct:.1f}%** of named-supplier spend.
* **{c.suppliers_for_50pct:,.0f}** suppliers account for 50% of spend and **{c.suppliers_for_80pct:,.0f}** for 80% (out of {c.suppliers_with_positive_spend:,.0f} with positive spend) - a long tail.
* Herfindahl-Hirschman index: **{c.hhi:,.0f}** (below 1,500 = unconcentrated).
* **{o.one_month_pct:.0f}%** of named suppliers were paid in only one month of the period, together worth £{o.one_month_spend:,.0f} ({o.one_month_spend_pct:.1f}% of spend) - a tail-spend / procurement-consolidation question.

![Top suppliers](images/top_suppliers.png)

### Top 15 suppliers
{md_table(q["top_suppliers"], {"net_spend": ",.0f", "lines": ",.0f", "share_pct": ".2f", "cumulative_share_pct": ".2f"})}

### Spend by supplier type (name-based heuristic)
{md_table(st, {"suppliers": ",.0f", "net_spend": ",.0f", "share_pct": ".1f"})}

## Spend by directorate
{md_table(q["by_directorate"].head(12), {"net_spend": ",.0f", "lines": ",.0f"})}

## Month-on-month
{md_table(mom, {"net_spend": ",.0f", "lines": ",.0f", "mom_change": ",.0f", "mom_change_pct": ".1f", "rolling_3m_avg": ",.0f"})}

## Ten largest single payments
{md_table(q["largest_payments"], {"amount": ",.0f"})}

## Statistical outliers (z-score > 4 within spend category)
{md_table(q["round_sum_outliers"].head(10), {"amount": ",.0f", "z_score": ".1f"})}

## Data quality
{int((dq.result == "PASS").sum())} checks passed, {int((dq.result == "WARN").sum())} raised warnings, {int((dq.result == "FAIL").sum())} failed, {int((dq.result == "INFO").sum())} are profile items.
Payments to redacted (personal-data) payees: **{redacted.rows_affected:,.0f} lines / £{redacted.amount_affected:,.0f}** - they cannot be analysed by supplier and are excluded from rankings.

![Data quality](images/data_quality_warnings.png)

{md_table(dq[["check_id", "dimension", "check_name", "rows_affected", "pct_affected", "result"]], {"rows_affected": ",.0f", "pct_affected": ".2f"})}
{ml_text}""", encoding="utf-8")
    print(f"wrote {OUT_MD.relative_to(ROOT)} and 4 charts in docs/images/")


if __name__ == "__main__":
    main()
