"""Measure how well the agent does against the ground-truth labels in data/labels.csv.

Run:  python evaluate.py
Needs MISTRAL_API_KEY for the categorization score; the recurring and unusual
detectors are also checked using the true categories, which needs no key.
"""
import os
import sys

import pandas as pd

from agent.db import load_statement
from agent.tools import categorize_all, find_recurring, flag_unusual

TX, LABELS = "data/transactions.csv", "data/labels.csv"


def precision_recall(predicted: set, actual: set):
    tp = len(predicted & actual)
    p = tp / len(predicted) if predicted else 0.0
    r = tp / len(actual) if actual else 0.0
    return p, r


def detector_scores(conn, labels):
    true_rec_ids = set(labels[labels.is_recurring == 1].row_id)
    rec_merchants = {r["merchant"] for r in find_recurring(conn)}
    pred_rec_ids = {i for (i,) in conn.execute(
        f"SELECT id FROM transactions WHERE merchant IN ({','.join('?' * len(rec_merchants))})",
        tuple(rec_merchants))} if rec_merchants else set()
    true_unu = set(labels[labels.is_unusual == 1].row_id)
    pred_unu = {u["id"] for u in flag_unusual(conn)}
    return precision_recall(pred_rec_ids, true_rec_ids), precision_recall(pred_unu, true_unu)


def show(name, pr):
    print(f"  {name:<22} precision {pr[0]:.0%}   recall {pr[1]:.0%}")


labels = pd.read_csv(LABELS)

print("Detectors with the true categories (no API key needed):")
conn = load_statement(TX)
conn.executemany("UPDATE transactions SET category=? WHERE id=?",
                 [(c, int(i)) for i, c in zip(labels.row_id, labels.category)])
rec, unu = detector_scores(conn, labels)
show("Recurring charges", rec)
show("Unusual spends", unu)

if not os.getenv("MISTRAL_API_KEY"):
    print("\nSet MISTRAL_API_KEY to also score LLM categorization.")
    sys.exit(0)

from agent.llm import MistralClient  # noqa: E402

print("\nEnd to end with LLM categorization:")
conn = load_statement(TX)
categorize_all(conn, MistralClient())
pred = pd.read_sql("SELECT id, merchant, category FROM transactions", conn).merge(
    labels, left_on="id", right_on="row_id", suffixes=("_pred", "_true"))
acc = (pred.category_pred == pred.category_true).mean()
print(f"  Categorization accuracy: {acc:.1%} ({(pred.category_pred == pred.category_true).sum()}"
      f"/{len(pred)} transactions)")
rec, unu = detector_scores(conn, labels)
show("Recurring charges", rec)
show("Unusual spends", unu)

wrong = pred[pred.category_pred != pred.category_true][["merchant", "category_pred", "category_true"]]
if not wrong.empty:
    print("\nMislabelled merchants:")
    print(wrong.drop_duplicates().to_string(index=False))
