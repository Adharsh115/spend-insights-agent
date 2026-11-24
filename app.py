"""Streamlit chat interface for the Spend Insights Agent.

Run:  streamlit run app.py
"""
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from agent import MistralClient, SpendAgent, load_statement
from agent.tools import find_recurring, flag_unusual

SAMPLE = Path(__file__).parent / "data" / "transactions.csv"
EXAMPLES = [
    "How much did I spend on food last month?",
    "What are my biggest spending categories?",
    "Which subscriptions am I paying for every month?",
    "Did I spend anything unusual recently?",
]

st.set_page_config(page_title="Spend Insights Agent", page_icon="💸", layout="wide")
st.title("💸 Spend Insights Agent")
st.caption("Ask questions about your bank statement in plain English.")

# ---------------------------------------------------------------- sidebar: setup
with st.sidebar:
    st.header("Setup")
    api_key = st.text_input("Mistral API key", type="password", value=os.getenv("MISTRAL_API_KEY", ""))
    upload = st.file_uploader("Bank statement CSV", type="csv",
                              help="Columns: date, description, debit, credit, balance")
    st.caption("No file? The bundled 6-month sample statement is used.")
    start = st.button("Load statement", type="primary", width="stretch")

if start:
    if not api_key:
        st.sidebar.error("Enter your Mistral API key first.")
    else:
        with st.spinner("Loading and categorizing transactions..."):
            try:
                conn = load_statement(upload if upload else SAMPLE)
                st.session_state.agent = SpendAgent(conn, MistralClient(api_key))
                st.session_state.chat = []
            except Exception as e:  # show the problem instead of a stack trace
                st.sidebar.error(f"Couldn't load the statement: {e}")

agent = st.session_state.get("agent")
if not agent:
    st.info("Add your Mistral API key in the sidebar and click **Load statement** to begin.")
    st.stop()

conn = agent.conn
df = pd.read_sql("SELECT * FROM transactions", conn)
debits = df[df.direction == "debit"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Transactions", f"{len(df):,}")
c2.metric("Money in", f"₹{df[df.direction == 'credit'].amount.sum():,.0f}")
c3.metric("Money out", f"₹{debits.amount.sum():,.0f}")
c4.metric("Period", f"{df.date.min()} → {df.date.max()}")

chat_tab, recurring_tab, unusual_tab, data_tab = st.tabs(["💬 Chat", "🔁 Recurring", "⚠️ Unusual", "📄 Transactions"])

# ---------------------------------------------------------------- chat
with chat_tab:
    st.write("Try one:")
    cols = st.columns(len(EXAMPLES))
    clicked = next((q for col, q in zip(cols, EXAMPLES) if col.button(q, width="stretch")), None)

    for msg in st.session_state.chat:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("steps"):
                with st.expander(f"How I worked this out ({len(msg['steps'])} tool calls)"):
                    for s in msg["steps"]:
                        st.markdown(f"**{s['tool']}**")
                        if s["args"].get("query"):
                            st.code(s["args"]["query"], language="sql")
                        st.json(s["result"], expanded=False)

    question = st.chat_input("Ask about your spending...") or clicked
    if question:
        st.session_state.chat.append({"role": "user", "content": question})
        with st.spinner("Thinking..."):
            try:
                result = agent.ask(question)
                st.session_state.chat.append({"role": "assistant", "content": result.answer,
                                              "steps": result.steps})
            except Exception as e:
                st.session_state.chat.append({"role": "assistant", "content": f"Something went wrong: {e}"})
        st.rerun()

# ---------------------------------------------------------------- recurring / unusual / data
with recurring_tab:
    rec = pd.DataFrame(find_recurring(conn))
    if rec.empty:
        st.write("No recurring charges found.")
    else:
        st.metric("Recurring charges per month", f"₹{rec.typical_amount.sum():,.0f}")
        st.dataframe(rec, width="stretch", hide_index=True)

with unusual_tab:
    unu = pd.DataFrame(flag_unusual(conn))
    if unu.empty:
        st.write("Nothing unusual found.")
    else:
        st.dataframe(unu, width="stretch", hide_index=True)

with data_tab:
    spend = debits.groupby("category").amount.sum().sort_values(ascending=False)
    st.bar_chart(spend)
    st.dataframe(df, width="stretch", hide_index=True)
