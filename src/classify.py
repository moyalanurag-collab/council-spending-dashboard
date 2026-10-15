"""Optional extra: text classification of payment lines.

Question this answers
    "Can a model recover the council's own spend category from the free-text fields
     (supplier name, purpose, service area, directorate)?  And where it confidently
     disagrees with the council, is the council's coding suspicious?"

Method
    * Target  : spend_category (32 classes) from the council's own coding.
    * Features: TF-IDF word n-grams over supplier + purpose + service area + directorate,
                plus character n-grams over the supplier name (robust to spelling variants).
    * Model   : linear classifier trained with SGD (log loss -> class probabilities).
    * Evaluation: 5-fold GroupKFold *by supplier* - every prediction is made by a model that
                has never seen that supplier, so the score reflects genuinely unseen vendors
                and cannot be inflated by memorising supplier names.
    * Output  : ml_predictions table (+ CSVs) with predicted category, confidence and a
                review flag for confident disagreements; docs/classification_report.md.
"""
import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import hstack
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import GroupKFold

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", module="sklearn")

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "council_spending.db"
OUT_DIR = ROOT / "data" / "processed"
REPORT_PATH = ROOT / "docs" / "classification_report.md"

CONFIDENCE_THRESHOLD = 0.80      # a disagreement only goes to the review queue above this confidence
MIN_REVIEW_AMOUNT = 1_000        # ... and above this absolute value (GBP)
RANDOM_STATE = 42

LOAD_SQL = """
SELECT f.payment_id, f.supplier_key, s.supplier_name, s.is_redacted,
       p.purpose, sa.service_area, dr.directorate,
       sc.spend_category, sc.spend_theme, f.amount
FROM fact_payments f
JOIN dim_supplier s       ON s.supplier_key = f.supplier_key
JOIN dim_purpose p        ON p.purpose_key = f.purpose_key
JOIN dim_service_area sa  ON sa.service_area_key = f.service_area_key
JOIN dim_directorate dr   ON dr.directorate_key = f.directorate_key
JOIN dim_spend_category sc ON sc.spend_category_key = f.spend_category_key
"""


def build_features(train: pd.DataFrame, test: pd.DataFrame):
    word = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
    char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True)
    text = lambda d: d["supplier_name"] + " | " + d["purpose"] + " | " + d["service_area"] + " | " + d["directorate"]
    Xtr = hstack([word.fit_transform(text(train)), char.fit_transform(train["supplier_name"])]).tocsr()
    Xte = hstack([word.transform(text(test)), char.transform(test["supplier_name"])]).tocsr()
    return Xtr, Xte


def main() -> None:
    with sqlite3.connect(DB_PATH) as con:
        df = pd.read_sql(LOAD_SQL, con)
    # Redacted payees all share one name -> no signal in the name; keep them but they will lean on purpose/service.
    y = df["spend_category"].to_numpy()
    groups = df["supplier_key"].to_numpy()
    classes = np.unique(y)

    oof_proba = np.zeros((len(df), len(classes)))
    baseline_pred = np.empty(len(df), dtype=object)
    for fold, (tr, te) in enumerate(GroupKFold(n_splits=5).split(df, y, groups), 1):
        Xtr, Xte = build_features(df.iloc[tr], df.iloc[te])
        model = SGDClassifier(loss="log_loss", alpha=2e-5, max_iter=100, tol=1e-4,
                              random_state=RANDOM_STATE, n_jobs=-1)
        model.fit(Xtr, y[tr])
        proba = model.predict_proba(Xte)
        idx = np.searchsorted(classes, model.classes_)
        oof_proba[np.ix_(te, idx)] = proba
        baseline_pred[te] = DummyClassifier(strategy="most_frequent").fit(Xtr, y[tr]).predict(Xte)
        print(f"  fold {fold}: accuracy {accuracy_score(y[te], classes[oof_proba[te].argmax(1)]):.3f}")

    pred = classes[oof_proba.argmax(1)]
    conf = oof_proba.max(1)
    out = df[["payment_id"]].copy()
    out["council_category"] = y
    out["predicted_category"] = pred
    out["confidence"] = conf.round(4)
    theme_of = df.drop_duplicates("spend_category").set_index("spend_category")["spend_theme"]
    out["predicted_theme"] = pd.Series(pred).map(theme_of).to_numpy()
    out["council_theme"] = df["spend_theme"].to_numpy()
    out["category_agrees"] = (pred == y).astype(int)
    out["theme_agrees"] = (out["predicted_theme"] == out["council_theme"]).astype(int)
    out["amount"] = df["amount"].to_numpy()
    out["supplier_name"] = df["supplier_name"].to_numpy()
    out["review_flag"] = ((out["category_agrees"] == 0) & (conf >= CONFIDENCE_THRESHOLD)
                          & (out["amount"].abs() >= MIN_REVIEW_AMOUNT)).astype(int)

    acc = accuracy_score(y, pred)
    f1m = f1_score(y, pred, average="macro")
    f1w = f1_score(y, pred, average="weighted")
    base_acc = accuracy_score(y, baseline_pred)
    theme_acc = out["theme_agrees"].mean()
    reviewed = out[out["review_flag"] == 1]
    print(f"accuracy {acc:.3f} | macro-F1 {f1m:.3f} | theme accuracy {theme_acc:.3f} | baseline {base_acc:.3f}")
    print(f"review queue: {len(reviewed):,} lines, GBP {reviewed['amount'].sum():,.0f}")

    with sqlite3.connect(DB_PATH) as con:
        out.drop(columns=["amount", "supplier_name"]).to_sql("ml_predictions", con, if_exists="replace", index=False)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.drop(columns=["amount", "supplier_name"]).to_csv(OUT_DIR / "ml_predictions.csv", index=False)
    (reviewed.sort_values("amount", key=abs, ascending=False)
        [["payment_id", "supplier_name", "amount", "council_category", "predicted_category", "confidence"]]
        .to_csv(OUT_DIR / "ml_review_queue.csv", index=False))

    # ---- markdown report ------------------------------------------------------------
    rep = pd.DataFrame(classification_report(y, pred, output_dict=True, zero_division=0)).T
    rep = rep.drop(index=["accuracy", "macro avg", "weighted avg"]).sort_values("support", ascending=False)
    rows = "\n".join(f"| {i} | {r.precision:.2f} | {r.recall:.2f} | {r['f1-score']:.2f} | {int(r.support):,} |"
                     for i, r in rep.iterrows())
    top = reviewed.sort_values("amount", key=abs, ascending=False).head(15)
    top_rows = "\n".join(f"| {r.supplier_name[:38]} | {r.amount:,.0f} | {r.council_category} | {r.predicted_category} | {r.confidence:.2f} |"
                         for r in top.itertuples())
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(f"""# Text-classification report (auto-generated by `src/classify.py`)

**Task:** predict the council's `spend_category` ({len(classes)} classes) from supplier name, purpose, service area and directorate.

**Validation:** 5-fold *GroupKFold by supplier* - each line is scored by a model that never saw that supplier.

| Metric | Value |
|---|---|
| Lines classified | {len(df):,} |
| Accuracy (category) | **{acc:.1%}** |
| Macro-F1 (category) | {f1m:.3f} |
| Weighted-F1 (category) | {f1w:.3f} |
| Accuracy (9 spend themes) | **{theme_acc:.1%}** |
| Majority-class baseline accuracy | {base_acc:.1%} |

## Review queue
Lines where the model **disagrees** with the council's category with confidence >= {CONFIDENCE_THRESHOLD:.0%} and |amount| >= GBP {MIN_REVIEW_AMOUNT:,}:
**{len(reviewed):,} lines worth GBP {reviewed['amount'].sum():,.0f} net** ({len(reviewed)/len(df):.1%} of lines).
These are *candidates for miscoding*, not proven errors - a supplier can legitimately supply several categories.
Full list: `data/processed/ml_review_queue.csv`.

Largest 15:

| Supplier | Amount (GBP) | Council category | Model category | Confidence |
|---|---:|---|---|---:|
{top_rows}

## Per-category performance

| Category | Precision | Recall | F1 | Lines |
|---|---:|---:|---:|---:|
{rows}

## Notes and limitations
* The labels are the council's own coding, so the model learns *the council's habits*, including their mistakes. Treat disagreements as an audit lead.
* Redacted payees carry no name signal; they are classified from purpose / service area only.
* Small categories (a handful of lines) are expected to have low recall.
""", encoding="utf-8")
    print(f"wrote {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
