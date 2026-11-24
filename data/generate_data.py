"""Generate a realistic, labelled 6-month Indian bank statement.

Outputs (next to this script):
  transactions.csv  - what a bank export looks like: date, description, debit, credit, balance
  labels.csv        - ground truth for each row: category, is_recurring, is_unusual

The labels are only used by evaluate.py to measure how well the agent does.
The agent itself never sees them.

Usage:  python data/generate_data.py
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)
OUT = Path(__file__).parent
START, END = date(2026, 5, 1), date(2026, 10, 31)
OPENING_BALANCE = 48_250.00

rows = []  # (date, description, debit, credit, category, is_recurring, is_unusual)


def ref():
    return str(random.randint(400000000000, 699999999999))


def upi(name, bank, vpa):
    return f"UPI/DR/{ref()}/{name}/{bank}/{vpa}"


def add(d, desc, amount, category, credit=False, recurring=False, unusual=False):
    amount = round(amount, 2)
    rows.append((d, desc, 0 if credit else amount, amount if credit else 0,
                 category, int(recurring), int(unusual)))


def months():
    d = START
    while d <= END:
        yield d.year, d.month
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def rand_day(y, m):
    first = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return first + timedelta(days=random.randrange((nxt - first).days))


# Day-to-day spending: (category, merchants, (min, max) amount, transactions per month)
EVERYDAY = [
    ("Food & Dining", [("SWIGGY", "YESB", "swiggy@yesbank"), ("ZOMATO", "HDFC", "zomato@hdfcbank"),
                       ("CHAI POINT", "ICIC", "chaipoint@icici"), ("A2B ADYAR ANANDA BHAVAN", "SBIN", "a2b@sbi")],
     (120, 650), 13),
    ("Groceries", [("BIGBASKET", "ICIC", "bigbasket@icici"), ("BLINKIT", "HDFC", "blinkit@hdfcbank"),
                   ("DMART AVENUE SUPERMARTS", "AXIS", "dmart@axisbank"), ("ZEPTO", "YESB", "zepto@ybl")],
     (250, 2400), 7),
    ("Transport", [("UBER INDIA", "HDFC", "uber@hdfcbank"), ("OLA CABS", "ICIC", "olacabs@icici"),
                   ("RAPIDO", "AXIS", "rapido@axisbank"), ("CMRL METRO RECHARGE", "SBIN", "cmrl@sbi")],
     (60, 420), 10),
    ("Shopping", [("AMAZON PAY", "UTIB", "amazon@apl"), ("FLIPKART", "AXIS", "flipkart@axisbank"),
                  ("MYNTRA", "ICIC", "myntra@icici")],
     (350, 3200), 3),
    ("Health", [("APOLLO PHARMACY", "HDFC", "apollo@hdfcbank"), ("MEDPLUS", "SBIN", "medplus@sbi")],
     (150, 900), 1),
    ("Transfers", [("ARJUN S", "SBIN", "arjun.s@okaxis"), ("PRIYA M", "HDFC", "priyam@okhdfcbank"),
                   ("KARTHIK R", "ICIC", "karthikr@oksbi")],
     (150, 1400), 3),
]

# Fixed-amount monthly charges: (description template, amount, day of month, category)
SUBSCRIPTIONS = [
    ("ACH/DR/NETFLIX ENTERTAINMENT/{ref}", 649.00, 12, "Entertainment & Subscriptions"),
    ("ACH/DR/SPOTIFY INDIA/{ref}", 119.00, 20, "Entertainment & Subscriptions"),
    ("ACH/DR/CULTFIT GYM MEMBERSHIP/{ref}", 1499.00, 5, "Health"),
    ("BIL/AIRTEL POSTPAID/{ref}", 599.00, 8, "Bills & Utilities"),
    ("BIL/JIO FIBER BROADBAND/{ref}", 999.00, 15, "Bills & Utilities"),
]

for y, m in months():
    # Income and rent
    add(date(y, m, 1), "NEFT/CR/ACME ANALYTICS PVT LTD/SALARY", 85_000, "Income", credit=True)
    add(date(y, m, 3), f"IMPS/DR/{ref()}/RAMESH KUMAR/HOUSE RENT", 22_000, "Rent", recurring=True)

    for tmpl, amt, day, cat in SUBSCRIPTIONS:
        d = date(y, m, min(day + random.choice([0, 0, 1]), 28))  # autopay sometimes lands a day late
        add(d, tmpl.format(ref=ref()), amt, cat, recurring=True)

    # Electricity is monthly but the amount varies, so it is NOT a fixed subscription
    add(date(y, m, random.randint(16, 22)), f"BIL/TANGEDCO ELECTRICITY/{ref()}",
        random.uniform(900, 2100), "Bills & Utilities")

    for cat, merchants, (lo, hi), per_month in EVERYDAY:
        for _ in range(max(0, per_month + random.randint(-2, 2))):
            name, bank, vpa = random.choice(merchants)
            add(rand_day(y, m), upi(name, bank, vpa), random.uniform(lo, hi), cat)

    if random.random() < 0.6:
        add(rand_day(y, m), f"ATM/CASH WDL/SBI ATM ADYAR/{ref()}", random.choice([2000, 3000, 5000]), "Cash")

# Occasional spends
for d, desc, amt, cat in [
    (date(2026, 6, 14), "POS/IRCTC E-TICKETING/NEW DELHI", 1_845, "Travel"),
    (date(2026, 7, 2), "POS/INDIGO AIRLINES/GURGAON", 4_620, "Travel"),
    (date(2026, 8, 22), "POS/MAKEMYTRIP INDIA/GURGAON", 5_310, "Travel"),
    (date(2026, 9, 28), "POS/IRCTC E-TICKETING/NEW DELHI", 2_150, "Travel"),
    (date(2026, 6, 9), "POS/UDEMY ONLINE COURSES/SAN FRANCISCO", 499, "Education"),
    (date(2026, 9, 3), "POS/COURSERA/MOUNTAIN VIEW", 2_350, "Education"),
    (date(2026, 7, 18), "NEFT/CR/ARJUN S/TRIP SHARE", 3_200, "Transfers"),
]:
    add(d, desc, amt, cat, credit=(cat == "Transfers"))

# Planted unusual spends: far above what this person normally spends in that category
for d, desc, amt, cat in [
    (date(2026, 6, 21), upi("SWIGGY", "YESB", "swiggy@yesbank"), 4_860, "Food & Dining"),
    (date(2026, 7, 27), upi("AMAZON PAY", "UTIB", "amazon@apl"), 18_999, "Shopping"),
    (date(2026, 8, 11), upi("UBER INDIA", "HDFC", "uber@hdfcbank"), 2_380, "Transport"),
    (date(2026, 9, 16), upi("APOLLO PHARMACY", "HDFC", "apollo@hdfcbank"), 6_420, "Health"),
    (date(2026, 10, 9), upi("BIGBASKET", "ICIC", "bigbasket@icici"), 9_750, "Groceries"),
]:
    add(d, desc, amt, cat, unusual=True)

rows.sort(key=lambda r: r[0])
balance = OPENING_BALANCE
with open(OUT / "transactions.csv", "w", newline="") as f1, open(OUT / "labels.csv", "w", newline="") as f2:
    tx, lb = csv.writer(f1), csv.writer(f2)
    tx.writerow(["date", "description", "debit", "credit", "balance"])
    lb.writerow(["row_id", "category", "is_recurring", "is_unusual"])
    for i, (d, desc, debit, credit, cat, rec, unu) in enumerate(rows, start=1):
        balance += credit - debit
        tx.writerow([d.strftime("%d/%m/%Y"), desc, f"{debit:.2f}" if debit else "",
                     f"{credit:.2f}" if credit else "", f"{balance:.2f}"])
        lb.writerow([i, cat, rec, unu])

print(f"Wrote {len(rows)} transactions ({START} to {END}) to {OUT}")
