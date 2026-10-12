"""Generate realistic demo data.

The dashboard has to be reviewable before any real account is linked — both so
the layout can be judged against plausible volume, and so the analytics can be
checked against data whose answers are known. Everything here is seeded from a
fixed constant, so the same history is produced every run.

The patterns are modelled on a real spending profile rather than uniform noise:
semi-monthly payroll, rent on the 1st, near-daily coffee, a delivery habit,
four overlapping streaming services, two subscriptions that quietly raised their
price, and a checking account carrying far more cash than it needs. Those are
the exact situations the insights engine is supposed to catch, so seeded data
doubles as an end-to-end check on it.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import db
from services import recurring, sync_service

SEED = 20260912
MONTHS_OF_HISTORY = 18

# (merchant, category, subcategory, amount, day_of_month, price_bump_after_months)
SUBSCRIPTIONS = [
    ("NETFLIX.COM",                "Subscriptions", "Streaming", 15.49, 4,  (9, 22.99)),
    ("HBO MAX",                    "Subscriptions", "Streaming", 15.99, 7,  None),
    ("DISNEY PLUS",                "Subscriptions", "Streaming", 13.99, 12, None),
    ("HULU",                       "Subscriptions", "Streaming", 17.99, 19, None),
    ("SPOTIFY USA",                "Subscriptions", "Music",     10.99, 9,  (11, 11.99)),
    ("ICLOUD STORAGE",             "Subscriptions", "Software",   2.99, 15, None),
    ("ADOBE CREATIVE CLOUD",       "Subscriptions", "Software",  54.99, 21, None),
    ("NYTIMES DIGITAL",            "Subscriptions", "News",      17.00, 25, None),
    ("OPENAI CHATGPT SUBSCRIPTION","Subscriptions", "Software",  20.00, 17, None),
    ("EQUINOX SF",                 "Health",        "Fitness",  215.00, 2,  None),
    ("1PASSWORD",                  "Subscriptions", "Software",   2.99, 28, None),
]

BILLS = [
    ("RENT PAYMENT SUNSET PROPERTIES", "Housing", "Rent",      3200.00, 1,  0.0),
    ("PG E WEB ONLINE",                "Housing", "Utilities",  118.00, 14, 0.28),
    ("COMCAST XFINITY",               "Housing", "Internet",    89.99, 11, 0.02),
    ("VERIZON WIRELESS",              "Housing", "Phone",       95.00, 23, 0.05),
    ("GEICO AUTO INSURANCE",          "Transportation", "Auto Insurance", 142.00, 6, 0.0),
]

GROCERS = [
    ("TRADER JOE S #123 SAN FRANCISCO CA", 60, 145),
    ("WHOLE FOODS MKT SAN FRANCISCO CA",   45, 180),
    ("SAFEWAY #1234 SAN FRANCISCO CA",     25, 95),
    ("COSTCO WHSE #0443 SOUTH SAN FRANCISCO CA", 140, 320),
]

COFFEE = [
    ("SQ *BLUE BOTTLE COFFEE OAKLAND CA", 5.5, 9.25),
    ("STARBUCKS STORE 10432", 4.75, 8.50),
    ("PHILZ COFFEE SAN FRANCISCO CA", 5.0, 8.0),
]

LUNCH = [
    ("SWEETGREEN SAN FRANCISCO CA", 14, 19),
    ("CHIPOTLE 2455 SAN FRANCISCO CA", 11, 17),
    ("SHAKE SHACK SAN FRANCISCO CA", 13, 22),
    ("TST* NOPA SAN FRANCISCO CA", 28, 68),
    ("SQ *TARTINE BAKERY SAN FRANCISCO CA", 9, 24),
]

DELIVERY = [
    ("DOORDASH*THAI HOUSE", 28, 62),
    ("UBER EATS 8005928996 CA", 26, 58),
    ("GRUBHUB SEAMLESS", 24, 55),
]

SHOPPING = [
    ("AMAZON.COM*2K4LQ1OG3 AMZN.COM/BILL WA", 12, 140, "Shopping", "General"),
    ("AMZN MKTP US*RT4G88H13", 9, 85, "Shopping", "General"),
    ("TARGET 00021456 SAN FRANCISCO CA", 22, 120, "Shopping", "General"),
    ("UNIQLO SAN FRANCISCO CA", 30, 140, "Shopping", "Clothing"),
    ("LULULEMON SAN FRANCISCO CA", 68, 180, "Shopping", "Clothing"),
    ("BEST BUY #1234 SAN FRANCISCO CA", 40, 350, "Shopping", "Electronics"),
    ("SEPHORA SAN FRANCISCO CA", 28, 95, "Shopping", "Personal Care"),
]

TRANSPORT = [
    ("UBER TRIP 8005928996 CA", 12, 44, "Transportation", "Rideshare"),
    ("LYFT RIDE SAN FRANCISCO CA", 11, 38, "Transportation", "Rideshare"),
    ("SHELL OIL 57443210 SAN FRANCISCO CA", 42, 78, "Transportation", "Gas"),
    ("CLIPPER CARD RELOAD", 20, 40, "Transportation", "Transit"),
    ("SFMTA PARKING METER", 3, 18, "Transportation", "Parking"),
]

OTHER_DISCRETIONARY = [
    ("AMC METREON 16 SAN FRANCISCO CA", 19, 52, "Entertainment", "Movies"),
    ("CVS/PHARMACY #9821 SAN FRANCISCO CA", 12, 65, "Health", "Pharmacy"),
    ("WALGREENS #4412 SAN FRANCISCO CA", 9, 48, "Health", "Pharmacy"),
    ("TICKETMASTER EVENT", 65, 240, "Entertainment", "Events"),
    ("BAR CRUDO SAN FRANCISCO CA", 34, 95, "Dining", "Bars"),
    ("ZEITGEIST SF", 22, 70, "Dining", "Bars"),
]

TRAVEL = [
    ("UNITED AIRLINES 0162345678", 240, 680, "Travel", "Flights"),
    ("AIRBNB * HMXQ2R4T5Y", 320, 900, "Travel", "Lodging"),
    ("MARRIOTT HOTELS SAN DIEGO CA", 210, 520, "Travel", "Lodging"),
    ("HERTZ RENT A CAR", 180, 340, "Travel", "Car Rental"),
]

# Local places no keyword list will ever know. They land Uncategorized on
# purpose, so the demo has something in the review queue — which is exactly
# what a real feed looks like the day it is linked.
# (merchant, low, high, months-ago it appears in)
UNRECOGNISED = [
    ("NOPALITO 9TH AVE SAN FRANCISCO CA",      38,  86, (0, 1, 2)),
    ("SAMOVAR TEA SAN FRANCISCO CA",           14,  32, (0, 2)),
    ("MISSION CLIFFS SAN FRANCISCO CA",       109, 109, (0, 1, 2)),
    ("HUCKLEBERRY BICYCLES SAN FRANCISCO CA", 240, 410, (1,)),
    ("SF SPCA VET HOSP",                      160, 260, (2,)),
    ("GOLDEN GATE PARK GOLF",                  26,  42, (1,)),
]

# The demo persona lives in San Francisco, so the budget comparison uses
# California. Flagged as seeded so clearing the demo also clears the choice —
# a real user must never inherit a state they did not pick.
DEMO_STATE = "CA"
DEMO_HOUSEHOLD = 1

HOLDINGS = [
    ("VTI",   "Vanguard Total Stock Market ETF", "etf",    46.0,  291.40, 11_200.00),
    ("VOO",   "Vanguard S&P 500 ETF",            "etf",    22.0,  534.10,  9_400.00),
    ("AAPL",  "Apple Inc.",                      "equity", 58.0,  242.30, 10_100.00),
    ("MSFT",  "Microsoft Corporation",           "equity", 24.0,  431.85,  8_600.00),
    ("NVDA",  "NVIDIA Corporation",              "equity", 70.0,  138.90,  4_300.00),
    ("SCHD",  "Schwab US Dividend Equity ETF",   "etf",    95.0,   27.60,  2_500.00),
    ("TSLA",  "Tesla, Inc.",                     "equity", 18.0,  248.50,  5_800.00),
    ("BTC",   "Bitcoin",                         "cryptocurrency", 0.21, 63_400.00, 9_000.00),
]


def _amt(rng: random.Random, low: float, high: float) -> float:
    return -round(rng.uniform(low, high), 2)


def _month_starts(months: int) -> list[date]:
    today = date.today().replace(day=1)
    out = []
    for i in range(months, -1, -1):
        total = today.month - 1 - i
        year = today.year + total // 12
        out.append(date(year, total % 12 + 1, 1))
    return out


def _safe_day(d: date, day: int) -> date:
    """Clamp a day-of-month to a month that may be shorter."""
    next_month = date(d.year + (d.month // 12), d.month % 12 + 1, 1)
    last_day = (next_month - timedelta(days=1)).day
    return d.replace(day=min(day, last_day))


def generate() -> dict:
    rng = random.Random(SEED)
    today = date.today()

    checking = sync_service.upsert_account(
        provider="manual", provider_account_id="seed-bofa-checking",
        institution="Bank of America", name="Advantage Relationship Checking",
        type="depository", subtype="checking", mask="4417", apy=0.01,
    )
    card = sync_service.upsert_account(
        provider="manual", provider_account_id="seed-chase-card",
        institution="Chase", name="Sapphire Reserve", type="credit",
        subtype="credit_card", mask="9032", credit_limit=28_000.0,
    )
    savings = sync_service.upsert_account(
        provider="manual", provider_account_id="seed-apple-savings",
        institution="Apple", name="Apple Savings", type="depository",
        subtype="savings", mask="3318", apy=4.15,
    )
    brokerage = sync_service.upsert_account(
        provider="manual", provider_account_id="seed-robinhood",
        institution="Robinhood", name="Individual Investing", type="investment",
        subtype="brokerage", mask="7740",
    )

    card_txns: list[dict] = []
    checking_txns: list[dict] = []
    savings_txns: list[dict] = []

    months = _month_starts(MONTHS_OF_HISTORY)
    for month_index, month in enumerate(months):
        in_month = lambda d: d <= today  # noqa: E731 - guard against future rows

        # --- Income: semi-monthly payroll, with a raise partway through -----
        salary = 7350.00 if month_index < 11 else 7980.00
        for day in (15, 30):
            d = _safe_day(month, day)
            if in_month(d):
                checking_txns.append({
                    "date": d.isoformat(), "amount": salary,
                    "description": "ACME ROBOTICS DES:PAYROLL DIRECT DEP ID:XXXXX",
                    "provider_merchant": "Acme Robotics", "raw_category": "income",
                })

        # --- Fixed bills ---------------------------------------------------
        for name, _cat, _sub, base, day, drift in BILLS:
            d = _safe_day(month, day)
            if not in_month(d):
                continue
            amount = base * (1 + rng.uniform(-drift, drift)) if drift else base
            checking_txns.append({
                "date": d.isoformat(), "amount": -round(amount, 2),
                "description": name, "provider_merchant": None, "raw_category": None,
            })

        # --- Subscriptions, on the card ------------------------------------
        for name, _cat, _sub, price, day, bump in SUBSCRIPTIONS:
            d = _safe_day(month, day)
            if not in_month(d):
                continue
            amount = price
            if bump and month_index >= bump[0]:
                amount = bump[1]
            card_txns.append({
                "date": d.isoformat(), "amount": -round(amount, 2),
                "description": name, "provider_merchant": None, "raw_category": None,
            })

        # --- Groceries: roughly weekly -------------------------------------
        for _ in range(rng.randint(4, 7)):
            d = _safe_day(month, rng.randint(1, 28))
            if not in_month(d):
                continue
            name, low, high = rng.choice(GROCERS)
            card_txns.append({"date": d.isoformat(), "amount": _amt(rng, low, high),
                              "description": name, "provider_merchant": None,
                              "raw_category": "groceries"})

        # --- Coffee: near-daily, the small-purchase habit -------------------
        for _ in range(rng.randint(16, 24)):
            d = _safe_day(month, rng.randint(1, 28))
            if not in_month(d):
                continue
            name, low, high = rng.choice(COFFEE)
            card_txns.append({"date": d.isoformat(), "amount": _amt(rng, low, high),
                              "description": name, "provider_merchant": None,
                              "raw_category": "dining"})

        # --- Lunches and dinners out ---------------------------------------
        for _ in range(rng.randint(10, 16)):
            d = _safe_day(month, rng.randint(1, 28))
            if not in_month(d):
                continue
            name, low, high = rng.choice(LUNCH)
            card_txns.append({"date": d.isoformat(), "amount": _amt(rng, low, high),
                              "description": name, "provider_merchant": None,
                              "raw_category": "dining"})

        # --- Delivery: the expensive habit, growing over time ---------------
        delivery_count = rng.randint(5, 8) + (2 if month_index > 11 else 0)
        for _ in range(delivery_count):
            d = _safe_day(month, rng.randint(1, 28))
            if not in_month(d):
                continue
            name, low, high = rng.choice(DELIVERY)
            card_txns.append({"date": d.isoformat(), "amount": _amt(rng, low, high),
                              "description": name, "provider_merchant": None,
                              "raw_category": "dining"})

        # --- Shopping, transport, and everything else ----------------------
        for table, count in ((SHOPPING, rng.randint(5, 10)),
                             (TRANSPORT, rng.randint(7, 13)),
                             (OTHER_DISCRETIONARY, rng.randint(3, 6))):
            for _ in range(count):
                d = _safe_day(month, rng.randint(1, 28))
                if not in_month(d):
                    continue
                name, low, high, _cat, _sub = rng.choice(table)
                card_txns.append({"date": d.isoformat(), "amount": _amt(rng, low, high),
                                  "description": name, "provider_merchant": None,
                                  "raw_category": None})

        # --- Travel, a few times a year ------------------------------------
        if rng.random() < 0.28:
            for _ in range(rng.randint(1, 3)):
                d = _safe_day(month, rng.randint(1, 28))
                if not in_month(d):
                    continue
                name, low, high, _cat, _sub = rng.choice(TRAVEL)
                card_txns.append({"date": d.isoformat(), "amount": _amt(rng, low, high),
                                  "description": name, "provider_merchant": None,
                                  "raw_category": "travel"})

        # --- Fees and interest: the fully-avoidable spending ----------------
        if rng.random() < 0.45:
            d = _safe_day(month, rng.randint(1, 28))
            if in_month(d):
                card_txns.append({
                    "date": d.isoformat(), "amount": -round(rng.uniform(2.5, 14.0), 2),
                    "description": "FOREIGN TRANSACTION FEE", "provider_merchant": None,
                    "raw_category": None})
        if rng.random() < 0.3:
            d = _safe_day(month, 26)
            if in_month(d):
                card_txns.append({
                    "date": d.isoformat(), "amount": -round(rng.uniform(18.0, 64.0), 2),
                    "description": "PURCHASE INTEREST CHARGE", "provider_merchant": None,
                    "raw_category": None})
        if rng.random() < 0.12:
            d = _safe_day(month, 27)
            if in_month(d):
                card_txns.append({
                    "date": d.isoformat(), "amount": -39.00,
                    "description": "LATE FEE", "provider_merchant": None,
                    "raw_category": None})
        if month_index % 12 == 7:
            d = _safe_day(month, 8)
            if in_month(d):
                card_txns.append({
                    "date": d.isoformat(), "amount": -550.00,
                    "description": "ANNUAL MEMBERSHIP FEE", "provider_merchant": None,
                    "raw_category": None})

        # --- Local merchants the categoriser cannot place -----------------
        months_ago = len(months) - 1 - month_index
        for name, low, high, when in UNRECOGNISED:
            if months_ago in when:
                d = _safe_day(month, rng.randint(3, 26))
                if in_month(d):
                    card_txns.append({
                        "date": d.isoformat(), "amount": _amt(rng, low, high),
                        "description": name, "provider_merchant": None,
                        "raw_category": None})

        # --- Transfers: card payoff, house fund, brokerage ------------------
        card_month_total = sum(
            -t["amount"] for t in card_txns if t["date"][:7] == month.strftime("%Y-%m")
        )
        pay_date = _safe_day(month, 27)
        if in_month(pay_date) and card_month_total > 0:
            checking_txns.append({
                "date": pay_date.isoformat(), "amount": -round(card_month_total, 2),
                "description": "CHASE CREDIT CRD AUTOPAY PAYMENT",
                "provider_merchant": None, "raw_category": None})
            card_txns.append({
                "date": pay_date.isoformat(), "amount": round(card_month_total, 2),
                "description": "PAYMENT THANK YOU - MOBILE",
                "provider_merchant": None, "raw_category": None})

        house_fund = 2500.00
        d = _safe_day(month, 16)
        if in_month(d):
            checking_txns.append({
                "date": d.isoformat(), "amount": -house_fund,
                "description": "ONLINE TRANSFER TO APPLE SAVINGS",
                "provider_merchant": None, "raw_category": "transfer"})
            savings_txns.append({
                "date": d.isoformat(), "amount": house_fund,
                "description": "TRANSFER FROM BANK OF AMERICA CHECKING",
                "provider_merchant": None, "raw_category": "transfer"})

        d = _safe_day(month, 18)
        if in_month(d):
            contribution = 600.00
            checking_txns.append({
                "date": d.isoformat(), "amount": -contribution,
                "description": "ROBINHOOD FUNDING ACH",
                "provider_merchant": None, "raw_category": "transfer"})

        # Savings interest, which is also what makes the APY visible.
        d = _safe_day(month, 1)
        if in_month(d) and month_index > 0:
            savings_txns.append({
                "date": d.isoformat(),
                "amount": round(rng.uniform(90, 320), 2),
                "description": "INTEREST PAID", "provider_merchant": "Apple Savings",
                "raw_category": "interest"})

    results = {
        "checking": sync_service.insert_transactions(checking, checking_txns, source="seed"),
        "card": sync_service.insert_transactions(card, card_txns, source="seed"),
        "savings": sync_service.insert_transactions(savings, savings_txns, source="seed"),
    }

    # --- Holdings and balances ---------------------------------------------
    brokerage_value = round(sum(q * p for _s, _n, _t, q, p, _c in HOLDINGS), 2)
    with db.tx() as conn:
        conn.execute("DELETE FROM holdings WHERE account_id = ?", (brokerage,))
        for symbol, name, stype, qty, price, basis in HOLDINGS:
            conn.execute(
                "INSERT INTO holdings (account_id, symbol, name, security_type, quantity,"
                " price, value, cost_basis, as_of) VALUES (?,?,?,?,?,?,?,?,?)",
                (brokerage, symbol, name, stype, qty, price, round(qty * price, 2),
                 basis, today.isoformat()),
            )

    # Balances are derived from the transactions just written, so the ledger and
    # the headline numbers cannot disagree.
    def net(account_id: int) -> float:
        row = db.query_one(
            "SELECT COALESCE(SUM(amount), 0) AS v FROM transactions WHERE account_id = ?",
            (account_id,),
        )
        return row["v"] or 0.0

    # Checking keeps a deliberately large idle balance — that is one of the
    # insights the dashboard is supposed to surface.
    checking_balance = round(14_800.00, 2)
    savings_balance = round(net(savings) + 18_400.00, 2)
    # A card carries a partial balance: the current month is not yet paid off.
    unpaid = round(-net(card), 2)
    card_balance = -abs(unpaid) if unpaid > 0 else 0.0

    db.execute("UPDATE accounts SET balance_current = ?, balance_available = ? WHERE id = ?",
               (checking_balance, checking_balance, checking))
    db.execute("UPDATE accounts SET balance_current = ?, balance_available = ? WHERE id = ?",
               (savings_balance, savings_balance, savings))
    db.execute("UPDATE accounts SET balance_current = ?, balance_available = ? WHERE id = ?",
               (card_balance, 28_000.0 - abs(card_balance), card))
    db.execute("UPDATE accounts SET balance_current = ? WHERE id = ?",
               (brokerage_value, brokerage))

    _seed_snapshots(rng, {"checking": checking, "savings": savings,
                          "card": card, "brokerage": brokerage},
                    {"checking": checking_balance, "savings": savings_balance,
                     "card": card_balance, "brokerage": brokerage_value})

    _seed_budgets()
    _seed_goal(savings)
    _seed_residence()
    derived = recurring.refresh()

    return {"accounts": 4, "transactions": results, "holdings": len(HOLDINGS),
            "recurring": derived}


def _seed_snapshots(rng, ids: dict[str, int], current: dict[str, float]) -> None:
    """Month-end balances walked backwards from today's known balance.

    Reconstructing history from the transactions themselves keeps the net-worth
    trend consistent with the ledger instead of inventing a second story.
    """
    months = _month_starts(MONTHS_OF_HISTORY)
    with db.tx() as conn:
        conn.execute("DELETE FROM balance_snapshots")
        for key, account_id in ids.items():
            balance = current[key]
            points: list[tuple[str, float]] = [(date.today().isoformat(), balance)]
            for month in reversed(months):
                month_end = (date(month.year + (month.month // 12),
                                  month.month % 12 + 1, 1) - timedelta(days=1))
                if month_end >= date.today():
                    continue
                row = conn.execute(
                    "SELECT COALESCE(SUM(amount), 0) AS v FROM transactions "
                    "WHERE account_id = ? AND date > ?",
                    (account_id, month_end.isoformat()),
                ).fetchone()
                after = row["v"] or 0.0
                if key == "brokerage":
                    # No transaction ledger for the brokerage: model it as
                    # contributions plus a noisy upward drift.
                    elapsed = (date.today() - month_end).days / 365.25
                    value = balance / ((1 + 0.11) ** elapsed) * rng.uniform(0.97, 1.03)
                    points.append((month_end.isoformat(), round(value, 2)))
                    continue
                points.append((month_end.isoformat(), round(balance - after, 2)))

            for on, value in points:
                conn.execute(
                    "INSERT INTO balance_snapshots (account_id, date, balance) "
                    "VALUES (?, ?, ?) ON CONFLICT(account_id, date) "
                    "DO UPDATE SET balance = excluded.balance",
                    (account_id, on, value),
                )


def _seed_budgets() -> None:
    budgets = {
        "Groceries": 650.0, "Dining": 700.0, "Transportation": 320.0,
        "Shopping": 400.0, "Subscriptions": 150.0, "Entertainment": 150.0,
        "Health": 280.0,
    }
    with db.tx() as conn:
        for category, limit in budgets.items():
            conn.execute(
                "INSERT INTO budgets (category, monthly_limit) VALUES (?, ?) "
                "ON CONFLICT(category) DO UPDATE SET monthly_limit = excluded.monthly_limit",
                (category, limit),
            )


def _seed_residence() -> None:
    db.set_setting("residence_state", DEMO_STATE)
    db.set_setting("household_size", str(DEMO_HOUSEHOLD))
    db.set_setting("residence_seeded", "1")


def _seed_goal(savings_account_id: int) -> None:
    saved = db.query_one(
        "SELECT balance_current AS v FROM accounts WHERE id = ?", (savings_account_id,)
    )["v"]
    db.execute(
        """
        UPDATE house_goal SET
            target_price = 850000, down_payment_pct = 20, saved_amount = ?,
            monthly_contribution = 2500, savings_apy = 4.15,
            interest_rate = 6.45, loan_term_years = 30, property_tax_rate = 1.18,
            insurance_annual = 2100, hoa_monthly = 0, pmi_rate = 0.55,
            closing_cost_pct = 3.0, gross_annual_income = 191520,
            monthly_debts = 450, credit_score = 771, current_rent = 3200,
            home_appreciation = 3.5, investment_return = 7.0, rent_inflation = 3.0,
            marginal_tax_rate = 32, funding_account_ids = ?, state = 'CA',
            updated_at = datetime('now')
        WHERE id = 1
        """,
        (round(saved, 2), f"[{savings_account_id}]"),
    )


def reseed() -> dict:
    """Wipe everything and regenerate. Only ever used for demo data.

    Deliberately leaves the ``settings`` table alone: it holds the first-run
    marker and the generated encryption key, and dropping the latter would make
    every stored provider token undecryptable.
    """
    db.init_db()
    with db.tx() as conn:
        for table in ("transactions", "holdings", "balance_snapshots",
                      "recurring_series", "accounts", "connections"):
            conn.execute(f"DELETE FROM {table}")
    return generate()
