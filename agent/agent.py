"""The agent loop: the model decides which tool to call, sees the result, and repeats until it can answer."""
import json
from dataclasses import dataclass, field

from .db import SCHEMA_FOR_PROMPT
from .tools import CATEGORIES, TOOL_SPECS, call_tool, categorize_all

SYSTEM_PROMPT = """You are Spend Insights, an assistant that answers questions about one person's bank statement.

You can call tools. Always get numbers from a tool; never guess or invent figures.
- run_sql: read-only SQLite queries on this table:
{schema}
  Categories used: {categories}.
  Amounts are in Indian Rupees (INR) and always positive; use direction to tell money in from money out.
  Dates are ISO strings, so filter with date >= '2026-08-01' style comparisons or strftime().
- find_recurring: monthly fixed-amount charges (subscriptions, rent, memberships).
- flag_unusual: one-off spends far above normal for their category.

The statement covers {start} to {end}. Treat {end} as "today" when the user says things like
"last month" or "last quarter" (calendar months/quarters relative to that date).

Answer in plain, friendly language for a non-technical person. Lead with the number they asked for,
format money like ₹12,450, and keep it short. If the data cannot answer the question, say so."""

MAX_STEPS = 6


@dataclass
class AgentResult:
    answer: str
    steps: list = field(default_factory=list)  # [{"tool": ..., "args": ..., "result": ...}]


class SpendAgent:
    def __init__(self, conn, llm):
        self.conn, self.llm = conn, llm
        if conn.execute("SELECT COUNT(*) FROM transactions WHERE category IS NULL").fetchone()[0]:
            categorize_all(conn, llm)
        start, end = conn.execute("SELECT MIN(date), MAX(date) FROM transactions").fetchone()
        self.system = SYSTEM_PROMPT.format(schema=SCHEMA_FOR_PROMPT, categories=", ".join(CATEGORIES),
                                           start=start, end=end)
        self.history = []  # previous user/assistant turns, so follow-up questions work

    def ask(self, question: str) -> AgentResult:
        messages = [{"role": "system", "content": self.system}, *self.history,
                    {"role": "user", "content": question}]
        steps = []

        for _ in range(MAX_STEPS):
            reply = self.llm.chat(messages, tools=TOOL_SPECS)
            tool_calls = reply.get("tool_calls") or []
            if not tool_calls:
                answer = reply.get("content") or "Sorry, I couldn't work that out."
                self.history += [{"role": "user", "content": question},
                                 {"role": "assistant", "content": answer}]
                return AgentResult(answer, steps)

            messages.append({"role": "assistant", "content": reply.get("content") or "",
                             "tool_calls": tool_calls})
            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = call_tool(self.conn, name, args)
                steps.append({"tool": name, "args": args, "result": result})
                messages.append({"role": "tool", "name": name, "tool_call_id": tc["id"],
                                 "content": json.dumps(result, default=str)[:12000]})

        return AgentResult("I needed too many steps to answer that. Try asking a more specific question.", steps)
