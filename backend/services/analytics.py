"""Spending, income, and net-worth aggregations.

One definition of "spend", used by every query in the app so no two tabs can
disagree:

    spend = -SUM(amount)  over  is_transfer = 0 AND excluded = 0
                                AND category != 'Income'

Three consequences worth being explicit about. Transfers are excluded, so
paying the Chase card from BofA checking is not counted as spending twice.
Refunds are *netted*, not ignored — a positive non-income amount reduces the
category it came from, which is what makes "you spent $340 at Nordstrom" true
after a return. And income is measured separately rather than as negative
spend, so the savings rate is a real ratio.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import db

SPEND_WHERE = "t.is_transfer = 0 AND t.excluded = 0 AND t.category != 'Income'"
INCOME_WHERE = "t.is_transfer = 0 AND t.excluded = 0 AND t.category = 'Income'"


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, n: int) -> date:
    total = d.month - 1 + n
    return date(d.year + total // 12, total % 12 + 1, 1)


def default_range(months: int = 1) -> tuple[str, str]:
    """The current month by default, or the trailing ``months`` months."""
    today = date.today()
    start = add_months(month_start(today), -(months - 1))
    return start.isoformat(), today.isoformat()


# --------------------------------------------------------------------------
# Balances and net worth
# --------------------------------------------------------------------------

def net_worth() -> dict:
    rows = db.query(
        "SELECT type, subtype, SUM(balance_current) AS total, COUNT(*) AS n "
        "FROM accounts WHERE is_active = 1 GROUP BY type, subtype"
    )
    assets = sum(r["total"] for r in rows if r["total"] > 0)
    liabilities = sum(r["total"] for r in rows if r["total"] < 0)
    by_type: dict[str, float] = {}
    for r in rows:
        by_type[r["type"]] = round(by_type.get(r["type"], 0.0) + r["total"], 2)

    cash = db.query_one(
        "SELECT COALESCE(SUM(balance_current), 0) AS v FROM accounts "
        "WHERE is_active = 1 AND type = 'depository'"
    )["v"]
    invested = db.query_one(
        "SELECT COALESCE(SUM(balance_current), 0) AS v FROM accounts "
        "WHERE is_active = 1 AND type = 'investment'"
    )["v"]

    return {
        "net_worth": round(assets + liabilities, 2),
        "assets": round(assets, 2),
        "liabilities": round(abs(liabilities), 2),
        "cash": round(cash, 2),
        "invested": round(invested, 2),
        "by_type": by_type,
    }


def net_worth_trend(months: int = 12) -> list[dict]:
    """Month-end net worth from balance snapshots.

    Uses the last snapshot in each month per account, so a month with several
    syncs is not double-counted.
    """
    since = add_months(month_start(date.today()), -(months - 1)).isoformat()
    rows = db.query(
        """
        WITH monthly AS (
            SELECT account_id,
                   strftime('%Y-%m', date) AS month,
                   MAX(date)               AS last_date
            FROM balance_snapshots
            WHERE date >= ?
            GROUP BY account_id, month
        )
        SELECT m.month,
               SUM(CASE WHEN s.balance > 0 THEN s.balance ELSE 0 END) AS assets,
               SUM(CASE WHEN s.balance < 0 THEN s.balance ELSE 0 END) AS liabilities,
               SUM(s.balance) AS net_worth
        FROM monthly m
        JOIN balance_snapshots s
          ON s.account_id = m.account_id AND s.date = m.last_date
        GROUP BY m.month
        ORDER BY m.month
        """,
        (since,),
    )
    return [
        {
            "month": r["month"],
            "assets": round(r["assets"] or 0, 2),
            "liabilities": round(abs(r["liabilities"] or 0), 2),
            "net_worth": round(r["net_worth"] or 0, 2),
        }
        for r in rows
    ]


# --------------------------------------------------------------------------
# Cash flow
# --------------------------------------------------------------------------

def cash_flow(months: int = 12) -> list[dict]:
    since = add_months(month_start(date.today()), -(months - 1)).isoformat()
    rows = db.query(
        f"""
        SELECT strftime('%Y-%m', t.date) AS month,
               COALESCE(SUM(CASE WHEN {INCOME_WHERE} THEN t.amount END), 0) AS income,
               COALESCE(-SUM(CASE WHEN {SPEND_WHERE} THEN t.amount END), 0) AS spend
        FROM transactions t
        WHERE t.date >= ?
        GROUP BY month
        ORDER BY month
        """,
        (since,),
    )
    out = []
    for r in rows:
        income, spend = round(r["income"], 2), round(r["spend"], 2)
        out.append({
            "month": r["month"],
            "income": income,
            "spend": spend,
            "net": round(income - spend, 2),
            "savings_rate": round((income - spend) / income * 100, 1) if income > 0 else None,
        })
    return out


def comparison_window(start: str, end: str) -> tuple[str, str, str]:
    """The period to compare against, and a label describing it honestly.

    For a month-to-date range this is the *same days of the previous month*,
    not the immediately preceding N days. The naive trailing window straddles
    the month boundary and so excludes rent, which lands on the 1st: on the 12th
    of the month that reports a ~465% increase in spending that is purely an
    artefact of where the window was cut.
    """
    s_date = datetime.fromisoformat(start).date()
    e_date = datetime.fromisoformat(end).date()

    is_month_to_date = (
        s_date.day == 1 and (s_date.year, s_date.month) == (e_date.year, e_date.month)
    )
    if is_month_to_date:
        prev_start = add_months(s_date, -1)
        last_day_of_prev = (s_date - timedelta(days=1)).day
        prev_end = prev_start.replace(day=min(e_date.day, last_day_of_prev))
        label = f"{prev_start.strftime('%b')} 1–{prev_end.day} last month"
        return prev_start.isoformat(), prev_end.isoformat(), label

    span = (e_date - s_date).days + 1
    prev_end = s_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    return prev_start.isoformat(), prev_end.isoformat(), f"the previous {span} days"


def summary(start: str, end: str) -> dict:
    """Headline numbers for a period, against a like-for-like previous period."""
    def totals(s: str, e: str) -> tuple[float, float, int]:
        r = db.query_one(
            f"""
            SELECT COALESCE(-SUM(CASE WHEN {SPEND_WHERE} THEN t.amount END), 0)  AS spend,
                   COALESCE(SUM(CASE WHEN {INCOME_WHERE} THEN t.amount END), 0)  AS income,
                   COUNT(CASE WHEN {SPEND_WHERE} THEN 1 END)                     AS n
            FROM transactions t WHERE t.date BETWEEN ? AND ?
            """,
            (s, e),
        )
        return r["spend"] or 0.0, r["income"] or 0.0, r["n"] or 0

    s_date, e_date = datetime.fromisoformat(start).date(), datetime.fromisoformat(end).date()
    span = (e_date - s_date).days + 1
    prev_start, prev_end, prev_label = comparison_window(start, end)

    spend, income, n = totals(start, end)
    p_spend, p_income, _ = totals(prev_start, prev_end)

    return {
        "start": start,
        "end": end,
        "days": span,
        "spend": round(spend, 2),
        "income": round(income, 2),
        "net": round(income - spend, 2),
        "transactions": n,
        "daily_average": round(spend / span, 2) if span else 0.0,
        "savings_rate": round((income - spend) / income * 100, 1) if income > 0 else None,
        "prev_start": prev_start,
        "prev_end": prev_end,
        "prev_label": prev_label,
        "prev_spend": round(p_spend, 2),
        "prev_income": round(p_income, 2),
        "spend_change_pct": round((spend - p_spend) / p_spend * 100, 1) if p_spend > 0 else None,
    }


# --------------------------------------------------------------------------
# Breakdowns
# --------------------------------------------------------------------------

def by_category(start: str, end: str, compare: bool = True) -> list[dict]:
    rows = db.query(
        f"SELECT t.category AS category, -SUM(t.amount) AS spend, COUNT(*) AS n "
        f"FROM transactions t WHERE {SPEND_WHERE} AND t.date BETWEEN ? AND ? "
        f"GROUP BY t.category HAVING spend > 0 ORDER BY spend DESC",
        (start, end),
    )
    total = sum(r["spend"] for r in rows) or 1.0

    prior: dict[str, float] = {}
    if compare:
        # Same window as summary(), so the per-category deltas and the headline
        # delta can never disagree about what "vs prior" means.
        p_start, p_end, _ = comparison_window(start, end)
        prior = {
            r["category"]: r["spend"]
            for r in db.query(
                f"SELECT t.category AS category, -SUM(t.amount) AS spend "
                f"FROM transactions t WHERE {SPEND_WHERE} AND t.date BETWEEN ? AND ? "
                f"GROUP BY t.category",
                (p_start, p_end),
            )
        }

    out = []
    for r in rows:
        prev = prior.get(r["category"])
        out.append({
            "category": r["category"],
            "spend": round(r["spend"], 2),
            "transactions": r["n"],
            "share": round(r["spend"] / total * 100, 1),
            "prev_spend": round(prev, 2) if prev is not None else None,
            "change": round(r["spend"] - prev, 2) if prev is not None else None,
            "change_pct": round((r["spend"] - prev) / prev * 100, 1) if prev else None,
        })
    return out


def by_subcategory(start: str, end: str, category: str | None = None) -> list[dict]:
    sql = (
        f"SELECT t.category, COALESCE(t.subcategory, 'Other') AS subcategory, "
        f"       -SUM(t.amount) AS spend, COUNT(*) AS n "
        f"FROM transactions t WHERE {SPEND_WHERE} AND t.date BETWEEN ? AND ? "
    )
    params: list = [start, end]
    if category:
        sql += "AND t.category = ? "
        params.append(category)
    sql += "GROUP BY t.category, subcategory HAVING spend > 0 ORDER BY spend DESC"
    return [
        {**r, "spend": round(r["spend"], 2)} for r in db.query(sql, tuple(params))
    ]


def by_merchant(start: str, end: str, limit: int = 25, category: str | None = None) -> list[dict]:
    sql = (
        f"SELECT t.merchant_key, "
        f"       MAX(t.merchant) AS merchant, "
        f"       MAX(t.category) AS category, "
        f"       -SUM(t.amount)  AS spend, "
        f"       COUNT(*)        AS n, "
        f"       -AVG(t.amount)  AS avg_amount, "
        f"       MAX(t.date)     AS last_date "
        f"FROM transactions t WHERE {SPEND_WHERE} AND t.date BETWEEN ? AND ? "
    )
    params: list = [start, end]
    if category:
        sql += "AND t.category = ? "
        params.append(category)
    sql += "GROUP BY t.merchant_key HAVING spend > 0 ORDER BY spend DESC LIMIT ?"
    params.append(limit)
    return [
        {
            "merchant_key": r["merchant_key"],
            "merchant": r["merchant"] or r["merchant_key"],
            "category": r["category"],
            "spend": round(r["spend"], 2),
            "transactions": r["n"],
            "avg_amount": round(r["avg_amount"], 2),
            "last_date": r["last_date"],
        }
        for r in db.query(sql, tuple(params))
    ]


# The categorical palette has eight slots and hues are never cycled, so the
# fold-in bucket has to fit inside them: seven named categories plus "Other".
MAX_TREND_CATEGORIES = 7


def category_trend(months: int = 6, top: int = MAX_TREND_CATEGORIES) -> dict:
    """Monthly spend per category, limited to the biggest categories overall.

    A stacked chart with 17 categories is unreadable, so everything outside the
    top N is folded into "Other" rather than dropped — the column totals still
    equal total spend.

    ``top`` is clamped to seven: with "Other" that fills the eight-hue palette
    exactly. An eighth named category would force a ninth series, and a ninth
    hue is indistinguishable from one already on screen.
    """
    top = min(top, MAX_TREND_CATEGORIES)
    since = add_months(month_start(date.today()), -(months - 1)).isoformat()
    top_cats = [
        r["category"]
        for r in db.query(
            f"SELECT t.category AS category, -SUM(t.amount) AS spend FROM transactions t "
            f"WHERE {SPEND_WHERE} AND t.date >= ? GROUP BY t.category "
            f"HAVING spend > 0 ORDER BY spend DESC LIMIT ?",
            (since, top),
        )
    ]
    rows = db.query(
        f"SELECT strftime('%Y-%m', t.date) AS month, t.category AS category, "
        f"       -SUM(t.amount) AS spend FROM transactions t "
        f"WHERE {SPEND_WHERE} AND t.date >= ? GROUP BY month, t.category ORDER BY month",
        (since,),
    )
    months_list = sorted({r["month"] for r in rows})
    series: dict[str, dict[str, float]] = {c: {} for c in top_cats + ["Other"]}
    for r in rows:
        bucket = r["category"] if r["category"] in series else "Other"
        series[bucket][r["month"]] = round(
            series[bucket].get(r["month"], 0.0) + r["spend"], 2
        )
    return {
        "months": months_list,
        "categories": [
            {"category": c, "values": [round(series[c].get(m, 0.0), 2) for m in months_list]}
            for c in series
            if any(series[c].values())
        ],
    }


def daily_spend(start: str, end: str) -> list[dict]:
    rows = db.query(
        f"SELECT t.date AS date, -SUM(t.amount) AS spend FROM transactions t "
        f"WHERE {SPEND_WHERE} AND t.date BETWEEN ? AND ? GROUP BY t.date ORDER BY t.date",
        (start, end),
    )
    return [{"date": r["date"], "spend": round(r["spend"], 2)} for r in rows]


def category_baselines(months: int = 6) -> dict[str, dict]:
    """Per-category median monthly spend over complete past months.

    The current month is excluded: comparing a half-finished month against full
    ones reports a fake improvement on the 10th of every month.
    """
    this_month = month_start(date.today())
    start = add_months(this_month, -months).isoformat()
    end = (this_month - timedelta(days=1)).isoformat()
    rows = db.query(
        f"SELECT t.category AS category, strftime('%Y-%m', t.date) AS month, "
        f"       -SUM(t.amount) AS spend FROM transactions t "
        f"WHERE {SPEND_WHERE} AND t.date BETWEEN ? AND ? "
        f"GROUP BY t.category, month",
        (start, end),
    )
    buckets: dict[str, list[float]] = {}
    for r in rows:
        buckets.setdefault(r["category"], []).append(r["spend"])

    import statistics
    out = {}
    for cat, values in buckets.items():
        out[cat] = {
            "median": round(statistics.median(values), 2),
            "mean": round(statistics.fmean(values), 2),
            "max": round(max(values), 2),
            "min": round(min(values), 2),
            "months": len(values),
        }
    return out


def budget_status(month: str | None = None) -> list[dict]:
    """Each budget against actual spend for the month, prorated to today."""
    month = month or date.today().strftime("%Y-%m")
    first = datetime.strptime(month + "-01", "%Y-%m-%d").date()
    last = add_months(first, 1) - timedelta(days=1)
    today = date.today()
    elapsed = min((today - first).days + 1, (last - first).days + 1) if today >= first else 0
    days_in_month = (last - first).days + 1

    actual = {
        r["category"]: r["spend"]
        for r in db.query(
            f"SELECT t.category AS category, -SUM(t.amount) AS spend FROM transactions t "
            f"WHERE {SPEND_WHERE} AND t.date BETWEEN ? AND ? GROUP BY t.category",
            (first.isoformat(), last.isoformat()),
        )
    }
    out = []
    for b in db.query("SELECT * FROM budgets ORDER BY category"):
        spent = round(actual.get(b["category"], 0.0), 2)
        limit = b["monthly_limit"]
        pace = round(spent / elapsed * days_in_month, 2) if elapsed else 0.0
        out.append({
            "category": b["category"],
            "limit": limit,
            "spent": spent,
            "remaining": round(limit - spent, 2),
            "used_pct": round(spent / limit * 100, 1) if limit else None,
            "projected": pace,
            "on_track": pace <= limit,
        })
    return out
