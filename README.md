# Spend Insights Agent

An LLM agent that answers plain-English questions about a bank statement.
Ask *"How much did I spend on travel last quarter?"* and it writes and runs the SQL itself,
then explains the answer in plain language.

<!-- Add a screenshot or GIF of the app here: ![demo](docs/demo.gif) -->

## What it does

- **Categorizes transactions** with an LLM (Mistral), turning raw narrations like
  `UPI/DR/4182.../SWIGGY/YESB/swiggy@yesbank` into categories like *Food & Dining*.
- **Answers questions** by choosing between three tools:
  - `run_sql`: read-only SQL on the statement (totals, trends, top merchants)
  - `find_recurring`: monthly fixed-amount charges such as subscriptions and rent
  - `flag_unusual`: one-off spends far above normal for their category
- **Shows its working**: every answer can be expanded to see which tools were called and the exact SQL.
- **Stays safe with generated SQL**: queries are checked to be a single `SELECT`, and SQLite's
  authorizer blocks any write even if a query slips past the check.

## How it works

```
User question
     │
     ▼
 Mistral (tool calling) ──► picks a tool ──► run_sql / find_recurring / flag_unusual
     ▲                                              │
     └────────────── tool result (JSON) ◄───────────┘
     │
     ▼  (repeats up to 6 steps, then)
Plain-English answer
```

The loop lives in `agent/agent.py` and calls the Mistral REST API directly, with no agent
framework, so the whole flow is about 60 lines.

| File | Purpose |
|---|---|
| `agent/db.py` | Loads the CSV into SQLite and extracts clean merchant names |
| `agent/tools.py` | Categorizer, read-only SQL, recurring and unusual detectors |
| `agent/agent.py` | The tool-calling loop |
| `agent/llm.py` | Small Mistral API client with retries |
| `app.py` | Streamlit chat interface |
| `evaluate.py` | Scores the agent against ground-truth labels |
| `data/generate_data.py` | Builds the labelled sample statement |

## Run it

```bash
pip install -r requirements.txt
export MISTRAL_API_KEY=your_key_here      # Windows: set MISTRAL_API_KEY=your_key_here
streamlit run app.py
```

Get a free key at [console.mistral.ai](https://console.mistral.ai). You can also paste it
into the app's sidebar. Upload your own statement as a CSV with columns
`date, description, debit, credit, balance`, or use the bundled sample.

## Sample data and evaluation

`data/transactions.csv` is a **synthetic** 6-month Indian bank statement (289 transactions)
with salary, rent, UPI food and grocery spends, subscriptions, travel and five deliberately
planted unusual spends. `data/labels.csv` holds the correct answer for every row, so the
agent can be measured:

```bash
python evaluate.py
```

| Check | Result |
|---|---|
| Recurring charge detection | 100% precision, 100% recall |
| Unusual spend detection | 100% precision, 100% recall |
| LLM categorization accuracy | *run `evaluate.py` with your key and fill in* |

Run the offline tests (a fake LLM is used, so no key is needed): `python -m pytest -q`

## Ideas to extend

- Month-on-month budget alerts per category
- Parse PDF statements directly
- Let the user correct a category and remember it for that merchant
