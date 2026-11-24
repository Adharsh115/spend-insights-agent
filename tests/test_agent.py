"""Offline tests: a fake LLM stands in for Mistral, so no API key is needed.

Run:  python -m pytest -q
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import SpendAgent, load_statement  # noqa: E402
from agent.db import extract_merchant  # noqa: E402
from agent.tools import find_recurring, flag_unusual, run_sql  # noqa: E402

TX, LABELS = ROOT / "data/transactions.csv", ROOT / "data/labels.csv"
TRUE_CAT = {}
_conn = load_statement(TX)
for (i, m), cat in zip(_conn.execute("SELECT id, merchant FROM transactions"),
                       pd.read_csv(LABELS).category):
    TRUE_CAT[m] = cat


class FakeLLM:
    """Categorizes from the true labels, then answers with one scripted SQL tool call."""

    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools=None, json_mode=False, temperature=0.1):
        if json_mode:  # categorization request
            items = json.loads(messages[0]["content"].split("Transactions:\n", 1)[1])
            return {"content": json.dumps({"results": [
                {"key": it["key"], "category": TRUE_CAT[it["merchant"]]} for it in items]})}
        self.calls += 1
        if messages[-1]["role"] == "user":
            return {"content": "", "tool_calls": [{"id": "c1", "function": {
                "name": "run_sql",
                "arguments": json.dumps({"query": "SELECT ROUND(SUM(amount)) FROM transactions "
                                                  "WHERE category='Food & Dining' AND date LIKE '2026-10%'"})}}]}
        total = json.loads(messages[-1]["content"])["rows"][0][0]
        return {"content": f"You spent ₹{total:,.0f} on food in October."}


@pytest.fixture
def conn():
    c = load_statement(TX)
    SpendAgent(c, FakeLLM())  # runs categorization
    return c


def test_merchant_extraction():
    assert extract_merchant("UPI/DR/123456789012/SWIGGY/YESB/swiggy@yesbank") == "SWIGGY"
    assert extract_merchant("NEFT/CR/ACME ANALYTICS PVT LTD/SALARY") == "ACME ANALYTICS PVT LTD"
    assert extract_merchant("POS/INDIGO AIRLINES/GURGAON") == "INDIGO AIRLINES"


def test_categorization_fills_every_row(conn):
    assert conn.execute("SELECT COUNT(*) FROM transactions WHERE category IS NULL").fetchone()[0] == 0


def test_sql_is_read_only(conn):
    assert "error" in run_sql(conn, "DELETE FROM transactions")
    assert "error" in run_sql(conn, "SELECT 1; DROP TABLE transactions")
    # passes the text check but SQLite's authorizer still blocks the write
    assert "error" in run_sql(conn, "WITH x AS (SELECT 1) DELETE FROM transactions")
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] > 0


def test_detectors_match_labels(conn):
    labels = pd.read_csv(LABELS)
    rec = {r["merchant"] for r in find_recurring(conn)}
    assert rec == {"RAMESH KUMAR", "NETFLIX ENTERTAINMENT", "SPOTIFY INDIA", "CULTFIT GYM MEMBERSHIP",
                   "AIRTEL POSTPAID", "JIO FIBER BROADBAND"}
    assert {u["id"] for u in flag_unusual(conn)} == set(labels[labels.is_unusual == 1].row_id)


def test_agent_loop_uses_tool_then_answers(conn):
    llm = FakeLLM()
    agent = SpendAgent(conn, llm)
    result = agent.ask("How much did I spend on food last month?")
    assert result.steps[0]["tool"] == "run_sql"
    assert result.answer.startswith("You spent ₹") and llm.calls == 2
