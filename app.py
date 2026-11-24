"""Streamlit interface for the Spend Insights Agent.

Run:  streamlit run app.py
"""
import os
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from agent import MistralClient, SpendAgent, load_statement
from agent.tools import find_recurring, flag_unusual

SAMPLE = Path(__file__).parent / "data" / "transactions.csv"
EXAMPLES = [
    "How much did I spend on food last month?",
    "What are my top 5 spending categories?",
    "Which subscriptions am I paying for every month?",
    "Did I spend anything unusual recently?",
]
TOOL_LABELS = {
    "run_sql": "Queried the transactions",
    "find_recurring": "Checked for recurring charges",
    "flag_unusual": "Checked for unusual spends",
}
ACCENT = "#4F46E5"


def inr(x: float) -> str:
    """Format a number the Indian way: 513200 -> ₹5,13,200."""
    neg, n = x < 0, f"{abs(round(x)):d}"
    if len(n) > 3:
        head, tail = n[:-3], n[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        n = ",".join(([head] if head else []) + groups) + "," + tail
    return ("-₹" if neg else "₹") + n


def friendly_error(e: Exception) -> str:
    msg = str(e)
    if "429" in msg:
        return ("Mistral is rate-limiting this key. New keys can take a few minutes to activate, "
                "and the free plan allows only a few requests per minute. Wait a minute and try again.")
    if "401" in msg:
        return "Mistral rejected the API key. Check that it was copied correctly."
    return f"Something went wrong: {msg}"


st.set_page_config(page_title="Spend Insights", page_icon="💸", layout="wide")
st.markdown(
    """<style>
    .block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1200px;}
    [data-testid="stMetricValue"] {font-size: 1.6rem;}
    .hero-sub {color: #6B7280; font-size: 1.05rem; margin-top: -0.6rem;}
    </style>""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("## 💸 Spend Insights")
    st.caption("An AI agent for your bank statement")
    st.divider()

    api_key = st.text_input("Mistral API key", type="password",
                            value=os.getenv("MISTRAL_API_KEY", ""),
                            help="Free key from console.mistral.ai")
    upload = st.file_uploader("Bank statement (CSV)", type="csv",
                              help="Columns: date, description, debit, credit, balance")
    if not upload:
        st.caption("No file? A 6-month sample statement is used.")

    if st.button("Load statement", type="primary", width="stretch"):
        if not api_key:
            st.error("Enter your Mistral API key first.")
        else:
            with st.spinner("Reading and categorizing transactions..."):
                try:
                    conn = load_statement(upload if upload else SAMPLE)
                    st.session_state.agent = SpendAgent(conn, MistralClient(api_key))
                    st.session_state.chat = []
                    st.session_state.source = upload.name if upload else "Sample statement"
                except Exception as e:  # show a readable message, not a stack trace
                    st.error(friendly_error(e))

    if st.session_state.get("agent"):
        st.success(f"Loaded: {st.session_state.source}")
        if st.button("Clear chat", width="stretch"):
            st.session_state.chat = []
            st.rerun()

    st.divider()
    st.caption("Your file is processed on this computer. Merchant names, your questions and "
               "query results are sent to Mistral to generate answers.")

agent = st.session_state.get("agent")

# ---------------------------------------------------------------- welcome screen
if not agent:
    st.title("Ask your bank statement anything")
    st.markdown('<p class="hero-sub">Plain-English answers about your spending, worked out by an '
                'AI agent that writes and runs its own queries.</p>', unsafe_allow_html=True)
    st.write("")
    cards = [
        ("💬", "Ask in plain English", "“How much did I spend on travel last quarter?” "
                                       "The agent writes the SQL and explains the answer."),
        ("🔁", "Find subscriptions", "Spots fixed monthly charges like rent, streaming "
                                    "and memberships, and totals what they cost you."),
        ("⚠️", "Catch unusual spends", "Flags one-off payments far above what you "
                                      "normally spend in that category."),
    ]
    for col, (icon, title, text) in zip(st.columns(3), cards):
        with col.container(border=True):
            st.markdown(f"### {icon}")
            st.markdown(f"**{title}**")
            st.caption(text)
    st.write("")
    st.info("**To start:** add your Mistral API key in the sidebar, optionally upload a CSV, "
            "then click **Load statement**.")
    st.stop()

# ---------------------------------------------------------------- data
conn = agent.conn
df = pd.read_sql("SELECT * FROM transactions", conn, parse_dates=["date"])
debits = df[df.direction == "debit"]
money_in = df.loc[df.direction == "credit", "amount"].sum()
money_out = debits.amount.sum()
period = f"{df.date.min():%b %Y} – {df.date.max():%b %Y}"

st.title("Your spending at a glance")
st.markdown(f'<p class="hero-sub">{st.session_state.source} · {period}</p>', unsafe_allow_html=True)

k1, k2, k3, k4 = st.columns(4)
for col, label, value in [
    (k1, "Transactions", f"{len(df):,}"),
    (k2, "Money in", inr(money_in)),
    (k3, "Money out", inr(money_out)),
    (k4, "Net saved", inr(money_in - money_out)),
]:
    with col.container(border=True):
        st.metric(label, value)

ask_tab, spend_tab, subs_tab, unusual_tab, tx_tab = st.tabs(
    ["💬 Ask", "📊 Spending", "🔁 Subscriptions", "⚠️ Unusual", "📄 Transactions"])


# ---------------------------------------------------------------- ask
def show_steps(steps):
    with st.expander(f"How I worked this out · {len(steps)} step{'s' if len(steps) != 1 else ''}"):
        for i, s in enumerate(steps, 1):
            st.markdown(f"**{i}. {TOOL_LABELS.get(s['tool'], s['tool'])}**")
            if s["args"].get("query"):
                st.code(s["args"]["query"], language="sql")
            result = s["result"]
            if isinstance(result, dict) and "error" in result:
                st.warning(result["error"])
            elif isinstance(result, dict) and "rows" in result:
                st.dataframe(pd.DataFrame(result["rows"], columns=result["columns"]),
                             hide_index=True, width="stretch")
            elif isinstance(result, list) and result:
                st.dataframe(pd.DataFrame(result), hide_index=True, width="stretch")
            else:
                st.caption("No rows returned.")


with ask_tab:
    chat = st.session_state.chat
    clicked = None
    if not chat:
        st.markdown("##### Try asking")
        grid = st.columns(2)
        for i, q in enumerate(EXAMPLES):
            if grid[i % 2].button(q, key=f"ex{i}", width="stretch"):
                clicked = q

    for msg in chat:
        with st.chat_message(msg["role"], avatar="🧑" if msg["role"] == "user" else "💸"):
            st.markdown(msg["content"])
            if msg.get("steps"):
                show_steps(msg["steps"])

    question = st.chat_input("Ask about your spending...") or clicked
    if question:
        chat.append({"role": "user", "content": question})
        with st.spinner("Working it out..."):
            try:
                result = agent.ask(question)
                chat.append({"role": "assistant", "content": result.answer, "steps": result.steps})
            except Exception as e:
                chat.append({"role": "assistant", "content": friendly_error(e)})
        st.rerun()

# ---------------------------------------------------------------- spending
with spend_tab:
    left, right = st.columns(2, gap="large")

    by_cat = debits.groupby("category", as_index=False).amount.sum().sort_values("amount", ascending=False)
    with left.container(border=True):
        st.markdown("**Where the money went**")
        st.altair_chart(
            alt.Chart(by_cat).mark_bar(color=ACCENT, cornerRadiusEnd=4).encode(
                x=alt.X("amount:Q", title="Spent (₹)", axis=alt.Axis(format=",.0f")),
                y=alt.Y("category:N", sort="-x", title=None, axis=alt.Axis(labelLimit=220)),
                tooltip=[alt.Tooltip("category:N", title="Category"),
                         alt.Tooltip("amount:Q", title="Spent (₹)", format=",.0f")],
            ).properties(height=380),
            width="stretch",
        )

    monthly = (debits.assign(month=debits.date.dt.to_period("M").dt.to_timestamp())
               .groupby("month", as_index=False).amount.sum())
    with right.container(border=True):
        st.markdown("**Money out by month**")
        st.altair_chart(
            alt.Chart(monthly).mark_bar(color=ACCENT, cornerRadiusEnd=4, size=36).encode(
                x=alt.X("month:T", title=None, axis=alt.Axis(format="%b %Y", tickCount="month")),
                y=alt.Y("amount:Q", title="Spent (₹)", axis=alt.Axis(format=",.0f")),
                tooltip=[alt.Tooltip("month:T", title="Month", format="%B %Y"),
                         alt.Tooltip("amount:Q", title="Spent (₹)", format=",.0f")],
            ).properties(height=380),
            width="stretch",
        )

    top = (debits.groupby(["merchant", "category"], as_index=False)
           .agg(spent=("amount", "sum"), payments=("amount", "size"))
           .sort_values("spent", ascending=False).head(8))
    with st.container(border=True):
        st.markdown("**Top merchants**")
        st.dataframe(
            top, hide_index=True, width="stretch",
            column_config={
                "merchant": "Merchant", "category": "Category", "payments": "Payments",
                "spent": st.column_config.ProgressColumn(
                    "Spent (₹)", format="%.0f", min_value=0, max_value=float(top.spent.max())),
            },
        )

# ---------------------------------------------------------------- subscriptions
with subs_tab:
    rec = pd.DataFrame(find_recurring(conn))
    if not rec.empty:
        rec["last_charged"] = pd.to_datetime(rec.last_charged)
    if rec.empty:
        st.info("No recurring charges found.")
    else:
        monthly_total = rec.typical_amount.sum()
        c1, c2, c3 = st.columns(3)
        for col, label, value in [(c1, "Recurring charges", str(len(rec))),
                                  (c2, "Per month", inr(monthly_total)),
                                  (c3, "Per year", inr(monthly_total * 12))]:
            with col.container(border=True):
                st.metric(label, value)
        st.dataframe(
            rec[["merchant", "category", "typical_amount", "usual_day_of_month", "months_seen", "last_charged"]],
            hide_index=True, width="stretch",
            column_config={
                "merchant": "Merchant", "category": "Category",
                "typical_amount": st.column_config.NumberColumn("Monthly (₹)", format="localized"),
                "usual_day_of_month": st.column_config.NumberColumn("Usual day", format="%d"),
                "months_seen": "Months seen",
                "last_charged": st.column_config.DateColumn("Last charged", format="DD MMM YYYY"),
            },
        )
        st.caption("A charge counts as recurring when the same amount (within 5%) is paid to the same "
                   "merchant around the same day of the month, for at least 3 months.")

# ---------------------------------------------------------------- unusual
with unusual_tab:
    unu = pd.DataFrame(flag_unusual(conn))
    if not unu.empty:
        unu["date"] = pd.to_datetime(unu.date)
        unu["category_median"] = unu.category_median.round()
    if unu.empty:
        st.success("Nothing unusual found.")
    else:
        st.markdown(f"**{len(unu)} spends** stand out from your normal pattern.")
        st.dataframe(
            unu[["date", "merchant", "category", "amount", "category_median", "times_usual"]],
            hide_index=True, width="stretch",
            column_config={
                "date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
                "merchant": "Merchant", "category": "Category",
                "amount": st.column_config.NumberColumn("Amount (₹)", format="localized"),
                "category_median": st.column_config.NumberColumn("Typical in category (₹)", format="localized"),
                "times_usual": st.column_config.NumberColumn("Times usual", format="%.1f×"),
            },
        )
        st.caption("Flagged when a payment is at least 3× the typical (median) spend for its category "
                   "and above ₹1,500. Recurring charges such as rent are not flagged.")

# ---------------------------------------------------------------- transactions
with tx_tab:
    f1, f2, f3 = st.columns([2, 2, 1])
    search = f1.text_input("Search", placeholder="Merchant or description")
    cats = f2.multiselect("Category", sorted(df.category.dropna().unique()))
    kind = f3.selectbox("Type", ["All", "Money out", "Money in"])

    view = df
    if search:
        view = view[view.merchant.str.contains(search, case=False)
                    | view.description.str.contains(search, case=False)]
    if cats:
        view = view[view.category.isin(cats)]
    if kind != "All":
        view = view[view.direction == ("debit" if kind == "Money out" else "credit")]

    st.caption(f"{len(view):,} of {len(df):,} transactions")
    view = view.assign(amount=view.amount.round(),
                       direction=view.direction.map({"debit": "Money out", "credit": "Money in"}))
    st.dataframe(
        view.sort_values("date", ascending=False)[
            ["date", "merchant", "category", "amount", "direction", "description"]],
        hide_index=True, width="stretch", height=460,
        column_config={
            "date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
            "merchant": "Merchant", "category": "Category",
            "amount": st.column_config.NumberColumn("Amount (₹)", format="localized"),
            "direction": "Type", "description": "Bank narration",
        },
    )
