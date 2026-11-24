"""The agent's tools: categorize, query with SQL, find recurring charges, flag unusual spends."""
import json
import re
import sqlite3
import statistics

CATEGORIES = [
    "Food & Dining", "Groceries", "Transport", "Shopping", "Travel", "Health", "Education",
    "Bills & Utilities", "Entertainment & Subscriptions", "Rent", "Income", "Transfers", "Cash", "Other",
]


# ---------------------------------------------------------------- categorization
def categorize_all(conn: sqlite3.Connection, llm, batch_size: int = 40) -> int:
    """Ask the LLM to categorize every uncategorized merchant. Returns rows updated.

    Categorizing per unique merchant (not per row) keeps it to one or two API calls
    for a typical statement, and guarantees the same merchant always gets the same label.
    """
    pending = conn.execute(
        """SELECT merchant, direction, MIN(description), COUNT(*)
           FROM transactions WHERE category IS NULL
           GROUP BY merchant, direction"""
    ).fetchall()
    updated = 0
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        items = [{"key": i, "merchant": m, "direction": d, "example": ex}
                 for i, (m, d, ex, _) in enumerate(batch)]
        prompt = (
            "Categorize each bank transaction merchant for an Indian personal bank account.\n"
            f"Allowed categories: {', '.join(CATEGORIES)}.\n"
            "Rules: salary credits are Income; payments to individuals are Transfers unless the "
            "narration says rent; ATM withdrawals are Cash; fixed streaming/music/app plans are "
            "Entertainment & Subscriptions; gyms and pharmacies are Health.\n"
            'Reply with JSON only: {"results": [{"key": <key>, "category": "<category>"}, ...]}\n\n'
            f"Transactions:\n{json.dumps(items, indent=1)}"
        )
        reply = llm.chat([{"role": "user", "content": prompt}], json_mode=True, temperature=0)
        try:
            results = json.loads(reply["content"])["results"]
        except (json.JSONDecodeError, KeyError, TypeError):
            results = []
        labels = {r.get("key"): r.get("category") for r in results if isinstance(r, dict)}

        for i, (merchant, direction, _, count) in enumerate(batch):
            cat = labels.get(i)
            if cat not in CATEGORIES:
                cat = "Other"
            conn.execute("UPDATE transactions SET category=? WHERE merchant=? AND direction=? AND category IS NULL",
                         (cat, merchant, direction))
            updated += count
    conn.commit()
    return updated


# ---------------------------------------------------------------- read-only SQL
_READ_ONLY_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
_RECURSIVE = getattr(sqlite3, "SQLITE_RECURSIVE", None)
if _RECURSIVE is not None:
    _READ_ONLY_ACTIONS.add(_RECURSIVE)


def validate_sql(query: str) -> str:
    """Reject anything that is not a single SELECT/WITH statement. Returns the cleaned query."""
    q = query.strip().rstrip(";").strip()
    if not re.match(r"(?is)^(select|with)\b", q):
        raise ValueError("Only SELECT queries are allowed.")
    if ";" in q:
        raise ValueError("Only one statement is allowed.")
    return q


def run_sql(conn: sqlite3.Connection, query: str, max_rows: int = 50) -> dict:
    """Run a validated, read-only query and return columns + rows."""
    try:
        q = validate_sql(query)
    except ValueError as e:
        return {"error": str(e)}

    # Second layer of safety: SQLite itself refuses any write while this is set
    conn.set_authorizer(lambda action, *a: sqlite3.SQLITE_OK if action in _READ_ONLY_ACTIONS
                        else sqlite3.SQLITE_DENY)
    try:
        cur = conn.execute(q)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchmany(max_rows + 1)
    except sqlite3.Error as e:
        return {"error": f"SQL error: {e}"}
    finally:
        conn.set_authorizer(None)

    truncated = len(rows) > max_rows
    return {"columns": cols, "rows": [list(r) for r in rows[:max_rows]], "truncated": truncated}


# ---------------------------------------------------------------- recurring charges
def find_recurring(conn: sqlite3.Connection, min_months: int = 3, tolerance: float = 0.05) -> list:
    """Find fixed-amount charges that repeat about once a month (subscriptions, rent, EMIs).

    A merchant counts as recurring when it is paid in at least `min_months` different months,
    roughly once per month, always within `tolerance` of the same amount, and around the
    same day of the month.
    """
    rows = conn.execute(
        "SELECT merchant, date, amount, category FROM transactions WHERE direction='debit' ORDER BY date"
    ).fetchall()
    by_merchant = {}
    for merchant, d, amount, cat in rows:
        by_merchant.setdefault(merchant, []).append((d, amount, cat))

    found = []
    for merchant, txns in by_merchant.items():
        months = {d[:7] for d, _, _ in txns}
        if len(months) < min_months or len(txns) > len(months) + 1:
            continue
        amounts = [a for _, a, _ in txns]
        typical = statistics.median(amounts)
        if any(abs(a - typical) > tolerance * typical for a in amounts):
            continue
        days = [int(d[8:10]) for d, _, _ in txns]
        if max(days) - min(days) > 6:
            continue
        found.append({
            "merchant": merchant,
            "category": txns[0][2],
            "typical_amount": round(typical, 2),
            "months_seen": len(months),
            "usual_day_of_month": int(statistics.median(days)),
            "last_charged": txns[-1][0],
        })
    return sorted(found, key=lambda r: -r["typical_amount"])


# ---------------------------------------------------------------- unusual spends
def flag_unusual(conn: sqlite3.Connection, multiple: float = 3.0, min_amount: float = 1500,
                 min_history: int = 5) -> list:
    """Flag one-off debits far above this person's normal spend in that category.

    Recurring charges are excluded (a ₹22,000 rent is big, but expected). A spend is flagged
    when it is at least `multiple` times the category's median and above `min_amount`.
    """
    recurring = {r["merchant"] for r in find_recurring(conn)}
    rows = conn.execute(
        "SELECT id, date, merchant, amount, category FROM transactions "
        "WHERE direction='debit' AND category IS NOT NULL"
    ).fetchall()
    by_cat = {}
    for row in rows:
        if row[2] not in recurring:
            by_cat.setdefault(row[4], []).append(row)

    flagged = []
    for cat, txns in by_cat.items():
        if len(txns) < min_history:
            continue
        median = statistics.median(t[3] for t in txns)
        for tid, d, merchant, amount, _ in txns:
            if amount >= multiple * median and amount >= min_amount:
                flagged.append({
                    "id": tid, "date": d, "merchant": merchant, "amount": amount, "category": cat,
                    "category_median": round(median, 2), "times_usual": round(amount / median, 1),
                })
    return sorted(flagged, key=lambda r: r["date"])


# ---------------------------------------------------------------- specs for the LLM
TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "run_sql",
        "description": "Run a read-only SQLite SELECT query on the transactions table and get the rows back. "
                       "Use for totals, averages, comparisons, top merchants, monthly trends and lookups.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "A single SQLite SELECT statement."}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "find_recurring",
        "description": "List fixed-amount charges that repeat monthly, such as subscriptions, rent and memberships.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "flag_unusual",
        "description": "List one-off spends that are far higher than usual for their category.",
        "parameters": {"type": "object", "properties": {}}}},
]


def call_tool(conn, name: str, args: dict):
    if name == "run_sql":
        return run_sql(conn, args.get("query", ""))
    if name == "find_recurring":
        return find_recurring(conn)
    if name == "flag_unusual":
        return flag_unusual(conn)
    return {"error": f"Unknown tool: {name}"}
