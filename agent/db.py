"""Load a bank-statement CSV into SQLite with a clean, query-friendly schema."""
import re
import sqlite3
from pathlib import Path

import pandas as pd

SCHEMA = """
CREATE TABLE transactions (
    id          INTEGER PRIMARY KEY,   -- row number in the original statement
    date        TEXT NOT NULL,         -- ISO format YYYY-MM-DD
    description TEXT NOT NULL,         -- raw bank narration
    merchant    TEXT NOT NULL,         -- cleaned merchant / payee name
    amount      REAL NOT NULL,         -- always positive
    direction   TEXT NOT NULL,         -- 'debit' (money out) or 'credit' (money in)
    balance     REAL,
    category    TEXT                   -- filled in by the categorizer
);
"""

SCHEMA_FOR_PROMPT = SCHEMA.strip()


def extract_merchant(desc: str) -> str:
    """Pull a readable merchant name out of a raw bank narration.

    UPI/DR/<ref>/SWIGGY/YESB/swiggy@yesbank  -> SWIGGY
    IMPS/DR/<ref>/RAMESH KUMAR/HOUSE RENT    -> RAMESH KUMAR
    NEFT/CR/ACME ANALYTICS PVT LTD/SALARY    -> ACME ANALYTICS PVT LTD
    ACH/DR/NETFLIX ENTERTAINMENT/<ref>       -> NETFLIX ENTERTAINMENT
    POS/INDIGO AIRLINES/GURGAON              -> INDIGO AIRLINES
    """
    parts = [p.strip() for p in desc.split("/")]
    kind = parts[0].upper()
    try:
        if kind in ("UPI", "IMPS"):
            return parts[3]
        if kind in ("NEFT", "ACH"):
            return parts[2]
        if kind in ("POS", "BIL"):
            return parts[1]
        if kind == "ATM":
            return "ATM CASH WITHDRAWAL"
    except IndexError:
        pass
    # Unknown format: drop long reference numbers and keep the rest
    return re.sub(r"\b\d{6,}\b", "", desc).strip(" /") or desc


def load_statement(csv_path, db_path=":memory:") -> sqlite3.Connection:
    """Read a statement CSV (date, description, debit, credit, balance) into SQLite."""
    df = pd.read_csv(csv_path)
    df.columns = [c.strip().lower() for c in df.columns]
    missing = {"date", "description", "debit", "credit"} - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")

    df["debit"] = pd.to_numeric(df["debit"], errors="coerce").fillna(0)
    df["credit"] = pd.to_numeric(df["credit"], errors="coerce").fillna(0)
    out = pd.DataFrame({
        "id": range(1, len(df) + 1),
        "date": pd.to_datetime(df["date"], dayfirst=True).dt.strftime("%Y-%m-%d"),
        "description": df["description"].astype(str),
        "merchant": df["description"].astype(str).map(extract_merchant),
        "amount": (df["debit"] + df["credit"]).round(2),
        "direction": ["credit" if c > 0 else "debit" for c in df["credit"]],
        "balance": pd.to_numeric(df.get("balance"), errors="coerce"),
        "category": None,
    })

    if db_path != ":memory:":
        Path(db_path).unlink(missing_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.executescript(SCHEMA)
    out.to_sql("transactions", conn, if_exists="append", index=False)
    conn.commit()
    return conn
