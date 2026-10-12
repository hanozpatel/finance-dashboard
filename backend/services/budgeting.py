"""One month of spending, per category, against your budget and your state.

The Budget tab reads everything from here. Each category carries three numbers
that mean different things, and the page is only useful if they are kept apart:

* **budget** — what you decided to spend. Yours; editable.
* **spent** — what you did spend, from the ledger.
* **state** — what a household your size in your state spends on average,
  from BEA. A reference, not a target.

The current month is still running, so comparing its spend-to-date against a
full month's average would make every category look under budget until the
30th. For the current month the comparison uses a **projection**: what you
have spent so far, plus your typical rate for the days that are left.

Straight-line pace (spend so far × days in month ÷ days elapsed) was the first
version, and real data showed why it is wrong for most categories: spending is
lumpy. One big grocery run on the 3rd extrapolated to a $2,100 month against a
typical $900. Spent-plus-typical never falls below what has already gone out,
and it does not explode on a single early purchase. Straight-line pace is kept
only for categories with no history to lean on.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import db
from services import benchmarks
from services.analytics import SPEND_WHERE, add_months

# Never budget lines: moving your own money, and money coming in.
_EXCLUDED = {"Transfer", "Income"}

HISTORY_MONTHS = 12


def _month_bounds(month: str) -> tuple[date, date]:
    first = datetime.strptime(month + "-01", "%Y-%m-%d").date()
    return first, add_months(first, 1) - timedelta(days=1)


def overview(month: str | None = None, history: int = HISTORY_MONTHS) -> dict:
    today = date.today()
    month = month or today.strftime("%Y-%m")
    first, last = _month_bounds(month)

    is_current = first <= today <= last
    days_in_month = (last - first).days + 1
    elapsed = (today - first).days + 1 if is_current else days_in_month
    is_future = first > today

    settings = benchmarks.settings()
    state = benchmarks.monthly(settings["state"], settings["household_size"])
    meta = benchmarks.metadata()

    window_start = add_months(first, -(history - 1))
    months = [add_months(window_start, i).strftime("%Y-%m") for i in range(history)]

    spend: dict[str, dict[str, float]] = {}
    for r in db.query(
        f"SELECT substr(t.date, 1, 7) AS month, t.category AS category, "
        f"       -SUM(t.amount) AS spend "
        f"FROM transactions t WHERE {SPEND_WHERE} AND t.date BETWEEN ? AND ? "
        f"GROUP BY month, t.category",
        (window_start.isoformat(), last.isoformat()),
    ):
        spend.setdefault(r["category"], {})[r["month"]] = round(r["spend"], 2)

    budgets = {r["category"]: r["monthly_limit"] for r in db.query("SELECT * FROM budgets")}

    # A row for every category you spent in or budgeted for. A state figure
    # alone does not earn one: a household with no education spending does not
    # need to be told, every month, that it spent 100% less than average.
    names = (set(budgets) | set(spend)) - _EXCLUDED

    # "Your typical month" averages only complete months, so a half-finished
    # current month does not drag it down.
    complete = [m for m in months if m < today.strftime("%Y-%m")]

    remaining_days = max(0, days_in_month - elapsed) if is_current else 0

    rows = []
    for category in names:
        by_month = spend.get(category, {})
        spent = by_month.get(month, 0.0)

        typical = (round(sum(by_month.get(m, 0.0) for m in complete) / len(complete), 2)
                   if complete else None)

        projected = None
        if is_current:
            if typical and typical > 0:
                projected = round(spent + typical * remaining_days / days_in_month, 2)
            elif elapsed:
                projected = round(spent / elapsed * days_in_month, 2)
        # What is compared against budget and state: the projection for a
        # running month, the actual for a finished one.
        basis = projected if projected is not None else spent
        # Refunds and reimbursements can push a month's net below zero. That is
        # a real number worth showing, but "−234% of the state average" is not.
        net_credit = basis < 0

        state_monthly = state.get(category)
        budget = budgets.get(category)
        rows.append({
            "category": category,
            "budget": budget,
            "spent": spent,
            "projected": projected,
            "typical": typical,
            "state": state_monthly,
            "comparable": state_monthly is not None,
            "not_comparable_reason": (None if state_monthly is not None
                                      else meta["not_comparable"].get(category)),
            "net_credit": net_credit,
            "vs_state_pct": (round((basis / state_monthly - 1) * 100, 1)
                             if state_monthly and not net_credit else None),
            "vs_budget_pct": (round(basis / budget * 100, 1)
                              if budget and not net_credit else None),
            "over_budget": bool(budget) and basis > budget,
            "history": [{"month": m, "spent": by_month.get(m, 0.0)} for m in months],
        })

    # Comparable categories first, largest state figure first, so the rows a
    # reader can judge against something come before the ones they cannot.
    rows.sort(key=lambda r: (not r["comparable"], -(r["state"] or 0), -r["spent"]))

    comparable = [r for r in rows if r["comparable"]]
    return {
        "month": month,
        "is_current": is_current,
        "is_future": is_future,
        "elapsed_days": min(elapsed, days_in_month) if not is_future else 0,
        "days_in_month": days_in_month,
        "months": months,
        "settings": settings,
        "source": {
            "name": meta["source"],
            "url": meta["source_url"],
            "year": meta["year"],
            "lines": meta["lines"],
        },
        "categories": rows,
        "totals": {
            "spent": round(sum(r["spent"] for r in comparable), 2),
            "projected": (round(sum(r["projected"] or 0 for r in comparable), 2)
                          if is_current else None),
            "state": round(sum(r["state"] for r in comparable), 2),
            "budget": round(sum(r["budget"] or 0 for r in rows), 2),
            "budgeted_categories": sum(1 for r in rows if r["budget"]),
        },
    }


def fill_from_state(round_to: float = 10.0) -> dict:
    """Give every comparable category without a budget the state average.

    Only empty budgets are filled: a number you chose yourself is never
    overwritten by an average. Rounded, because "$372.83 for groceries" is a
    statistic, not a budget anyone would write down.
    """
    settings = benchmarks.settings()
    state = benchmarks.monthly(settings["state"], settings["household_size"])
    existing = {r["category"] for r in db.query("SELECT category FROM budgets")}

    filled = []
    for category, amount in state.items():
        if category in existing:
            continue
        limit = max(round_to, round(amount / round_to) * round_to)
        db.execute(
            "INSERT INTO budgets (category, monthly_limit) VALUES (?, ?)",
            (category, limit),
        )
        filled.append({"category": category, "monthly_limit": limit})
    return {"filled": filled, "skipped": sorted(existing & set(state))}
