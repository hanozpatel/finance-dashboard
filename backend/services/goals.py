"""The house-purchase plan: everything the House tab needs in one payload.

This layer reads assumptions from ``house_goal``, resolves the down-payment
balance from real accounts when the user has nominated any, and runs the pure
functions in services/mortgage.py over them.

It also connects the two halves of the app. The Savings tab identifies a monthly
figure that could be cut; this computes how much sooner the down payment is
reached if that figure is redirected into the fund. A spending insight nobody
acts on is trivia — tying it to a date makes it a decision.
"""

from __future__ import annotations

import json
from datetime import date

import db
from services import analytics, insights, mortgage, states

GOAL_FIELDS = [
    "target_price", "down_payment_pct", "saved_amount", "monthly_contribution",
    "savings_apy", "target_date", "interest_rate", "loan_term_years",
    "property_tax_rate", "insurance_annual", "hoa_monthly", "pmi_rate",
    "closing_cost_pct", "gross_annual_income", "monthly_debts", "credit_score",
    "current_rent", "home_appreciation", "investment_return", "rent_inflation",
    "marginal_tax_rate", "funding_account_ids",
    "state", "loan_type", "conforming_limit", "va_first_use",
]


def get_goal() -> dict:
    goal = db.query_one("SELECT * FROM house_goal WHERE id = 1")
    if not goal:
        db.execute("INSERT OR IGNORE INTO house_goal (id) VALUES (1)")
        goal = db.query_one("SELECT * FROM house_goal WHERE id = 1")

    try:
        funding_ids = json.loads(goal.get("funding_account_ids") or "[]")
    except json.JSONDecodeError:
        funding_ids = []
    goal["funding_account_ids"] = funding_ids

    # When accounts are nominated as the down-payment fund, their live balance is
    # the truth and the stored figure is only a fallback. Otherwise a sync would
    # leave the goal quietly stale.
    if funding_ids:
        placeholders = ",".join("?" * len(funding_ids))
        row = db.query_one(
            f"SELECT COALESCE(SUM(balance_current), 0) AS v FROM accounts "
            f"WHERE id IN ({placeholders}) AND is_active = 1",
            tuple(funding_ids),
        )
        goal["saved_amount"] = round(row["v"] or 0.0, 2)
        goal["saved_from_accounts"] = True
    else:
        goal["saved_from_accounts"] = False

    return goal


def update_goal(updates: dict, apply_state_defaults: bool = False) -> dict:
    """Apply a partial update.

    When ``apply_state_defaults`` is set alongside a new ``state``, the fields
    that genuinely vary by state — property tax, insurance, closing costs — are
    filled in from that state's averages. Price, income, and rate are never
    touched: those are the user's own situation, and silently rewriting them on
    a dropdown change would be hostile.
    """
    updates = dict(updates)
    if apply_state_defaults and updates.get("state"):
        for key, value in states.defaults_for(updates["state"]).items():
            updates.setdefault(key, value)

    fields, params = [], []
    for key, value in updates.items():
        if key not in GOAL_FIELDS:
            continue
        if key == "funding_account_ids":
            value = json.dumps(value if isinstance(value, list) else [])
        if key == "va_first_use":
            value = int(bool(value))
        fields.append(f"{key} = ?")
        params.append(value)
    if fields:
        params.append(1)
        db.execute(
            f"UPDATE house_goal SET {', '.join(fields)}, updated_at = datetime('now')"
            f" WHERE id = ?",
            tuple(params),
        )
    return get_goal()


def _breakdown(goal: dict, *, price: float | None = None,
               down_pct: float | None = None, rate: float | None = None,
               term: int | None = None, loan_type: str | None = None) -> dict:
    return mortgage.monthly_payment_breakdown(
        home_price=price if price is not None else goal["target_price"],
        down_payment_pct=down_pct if down_pct is not None else goal["down_payment_pct"],
        interest_rate=rate if rate is not None else goal["interest_rate"],
        loan_term_years=term if term is not None else goal["loan_term_years"],
        property_tax_rate=goal["property_tax_rate"],
        insurance_annual=goal["insurance_annual"],
        hoa_monthly=goal["hoa_monthly"],
        pmi_rate=goal["pmi_rate"],
        loan_type=loan_type or goal.get("loan_type") or "conventional",
        conforming_limit=goal.get("conforming_limit") or mortgage.CONFORMING_LIMIT_2025,
        va_first_use=bool(goal.get("va_first_use", 1)),
    )


def plan(*, horizon_years: int = 7, extra_monthly: float = 0.0) -> dict:
    """The whole plan. One call so the tab cannot render half-consistent state."""
    goal = get_goal()

    payment = _breakdown(goal)
    ratios = mortgage.dti(
        housing_monthly=payment["piti"],
        other_monthly_debts=goal["monthly_debts"],
        gross_annual_income=goal["gross_annual_income"],
    )
    cash = mortgage.cash_needed_at_closing(
        home_price=goal["target_price"],
        down_payment_pct=goal["down_payment_pct"],
        closing_cost_pct=goal["closing_cost_pct"],
    )
    projection = mortgage.savings_projection(
        target=cash["total"],
        saved=goal["saved_amount"],
        monthly_contribution=goal["monthly_contribution"],
        apy=goal["savings_apy"],
    )
    affordability = mortgage.max_affordable_price(
        gross_annual_income=goal["gross_annual_income"],
        monthly_debts=goal["monthly_debts"],
        down_payment_available=goal["saved_amount"],
        down_payment_pct=goal["down_payment_pct"],
        interest_rate=goal["interest_rate"],
        loan_term_years=goal["loan_term_years"],
        property_tax_rate=goal["property_tax_rate"],
        insurance_annual=goal["insurance_annual"],
        hoa_monthly=goal["hoa_monthly"],
        pmi_rate=goal["pmi_rate"],
        closing_cost_pct=goal["closing_cost_pct"],
    )
    schedule = mortgage.amortization_schedule(
        loan=payment["loan_amount"],
        annual_pct=goal["interest_rate"],
        years=goal["loan_term_years"],
        home_value=goal["target_price"],
        pmi_rate=payment["mi_annual_pct"],
        mi_rule=payment["mi_rule"],
        extra_monthly=extra_monthly,
    )
    comparison = mortgage.rent_vs_buy(
        home_price=goal["target_price"],
        down_payment_pct=goal["down_payment_pct"],
        interest_rate=goal["interest_rate"],
        loan_term_years=goal["loan_term_years"],
        property_tax_rate=goal["property_tax_rate"],
        insurance_annual=goal["insurance_annual"],
        hoa_monthly=goal["hoa_monthly"],
        pmi_rate=goal["pmi_rate"],
        closing_cost_pct=goal["closing_cost_pct"],
        current_rent=goal["current_rent"],
        rent_inflation=goal["rent_inflation"],
        home_appreciation=goal["home_appreciation"],
        investment_return=goal["investment_return"],
        marginal_tax_rate=goal["marginal_tax_rate"],
        horizon_years=horizon_years,
    )

    return {
        "goal": goal,
        "payment": payment,
        "dti": ratios,
        "cash_needed": cash,
        "projection": projection,
        "affordability": affordability,
        "schedule_summary": {
            k: v for k, v in schedule.items() if k != "rows"
        },
        "equity_by_year": _equity_by_year(schedule, goal),
        "rent_vs_buy": comparison,
        "scenarios": scenarios(goal),
        "loan_comparison": loan_comparison(goal),
        "state": states.get(goal.get("state")),
        "states": states.all_states(),
        "readiness": readiness(goal, payment, ratios, cash, projection),
        "savings_impact": savings_impact(goal, cash),
        "monthly_vs_rent": round(payment["total_monthly"] - goal["current_rent"], 2),
    }


def _equity_by_year(schedule: dict, goal: dict) -> list[dict]:
    """Year-end equity, appreciating the home rather than holding it flat."""
    out = []
    rows = schedule["rows"]
    for year in range(1, goal["loan_term_years"] + 1):
        idx = year * 12 - 1
        if idx >= len(rows):
            break
        row = rows[idx]
        value = goal["target_price"] * (1 + goal["home_appreciation"] / 100.0) ** year
        out.append({
            "year": year,
            "balance": row["balance"],
            "home_value": round(value, 2),
            "equity": round(value - row["balance"], 2),
            "cumulative_interest": row["cumulative_interest"],
        })
    return out


def scenarios(goal: dict) -> list[dict]:
    """Side-by-side down payment, rate, and term variations.

    Each row reports the monthly cost, the cash required, and when that cash
    arrives at the current savings rate — because a 5%-down option that is
    affordable two years sooner is a genuinely different plan, not just a
    cheaper one.
    """
    out = []
    rate = goal["interest_rate"]
    specs = [
        ("5% down",        {"down_pct": 5}),
        ("10% down",       {"down_pct": 10}),
        ("20% down",       {"down_pct": 20}),
        ("20% down, 15yr", {"down_pct": 20, "term": 15}),
        (f"Rate {rate - 1:.2f}%", {"rate": rate - 1}),
        (f"Rate {rate + 1:.2f}%", {"rate": rate + 1}),
    ]
    for label, kwargs in specs:
        down_pct = kwargs.get("down_pct", goal["down_payment_pct"])
        payment = _breakdown(goal, **kwargs)
        cash = mortgage.cash_needed_at_closing(
            home_price=goal["target_price"],
            down_payment_pct=down_pct,
            closing_cost_pct=goal["closing_cost_pct"],
        )
        projection = mortgage.savings_projection(
            target=cash["total"], saved=goal["saved_amount"],
            monthly_contribution=goal["monthly_contribution"], apy=goal["savings_apy"],
        )
        ratios = mortgage.dti(
            housing_monthly=payment["piti"],
            other_monthly_debts=goal["monthly_debts"],
            gross_annual_income=goal["gross_annual_income"],
        )
        schedule = mortgage.amortization_schedule(
            loan=payment["loan_amount"],
            annual_pct=kwargs.get("rate", goal["interest_rate"]),
            years=kwargs.get("term", goal["loan_term_years"]),
            home_value=goal["target_price"],
            pmi_rate=payment["mi_annual_pct"],
            mi_rule=payment["mi_rule"],
        )
        out.append({
            "label": label,
            "down_payment_pct": down_pct,
            "interest_rate": kwargs.get("rate", goal["interest_rate"]),
            "loan_term_years": kwargs.get("term", goal["loan_term_years"]),
            "monthly": payment["total_monthly"],
            "principal_interest": payment["principal_interest"],
            "pmi": payment["pmi"],
            "cash_needed": cash["total"],
            "months_to_save": projection["months"],
            "ready_date": projection["target_date"],
            "total_interest": schedule["total_interest"],
            "total_pmi": schedule["total_pmi"],
            "back_end_dti": ratios["back_end"],
            "verdict": ratios["verdict"],
        })
    return out


def readiness(goal: dict, payment: dict, ratios: dict, cash: dict,
              projection: dict) -> dict:
    """A short checklist of what stands between here and an accepted offer."""
    checks = []

    saved_pct = (goal["saved_amount"] / cash["total"] * 100) if cash["total"] else 0.0
    checks.append({
        "label": "Down payment and closing costs saved",
        "status": "done" if saved_pct >= 100 else ("on_track" if saved_pct >= 50 else "todo"),
        "detail": (
            f"${goal['saved_amount']:,.0f} of ${cash['total']:,.0f} "
            f"({saved_pct:.0f}%)."
            + ("" if saved_pct >= 100 else
               f" {projection['months']} months to go at ${goal['monthly_contribution']:,.0f}/mo."
               if projection["months"] is not None else " No contribution set.")
        ),
        "progress": round(min(100.0, saved_pct), 1),
    })

    checks.append({
        "label": "Debt-to-income within lender limits",
        "status": {"comfortable": "done", "qualifies": "on_track",
                   "stretched": "warn", "over_limit": "blocked",
                   "unknown": "todo"}[ratios["verdict"]],
        "detail": (
            f"Front-end {ratios['front_end']:.1f}% (target ≤28%), "
            f"back-end {ratios['back_end']:.1f}% (conventional ≤36%, QM ≤43%)."
        ),
        "progress": round(max(0.0, min(100.0, (43 - ratios["back_end"]) / 43 * 100)), 1),
    })

    score = goal["credit_score"]
    checks.append({
        "label": "Credit score",
        "status": "done" if score >= 740 else ("on_track" if score >= 680 else "warn"),
        "detail": (
            f"{score}. 740+ gets the best conventional pricing; "
            f"620 is the usual floor and every 20-point band above it lowers the rate."
        ),
        "progress": round(max(0.0, min(100.0, (score - 600) / 160 * 100)), 1),
    })

    emergency_target = payment["total_monthly"] * 3
    liquid = db.query_one(
        "SELECT COALESCE(SUM(balance_current), 0) AS v FROM accounts "
        "WHERE is_active = 1 AND type = 'depository'"
    )["v"] or 0.0
    reserves = max(0.0, liquid - cash["total"])
    checks.append({
        "label": "Reserves after closing",
        "status": "done" if reserves >= emergency_target else "todo",
        "detail": (
            f"${reserves:,.0f} would remain after closing, against a "
            f"${emergency_target:,.0f} target (3 months of the new payment). "
            f"Lenders want to see reserves, and closing with none is how a "
            f"first repair becomes debt."
        ),
        "progress": round(min(100.0, reserves / emergency_target * 100), 1) if emergency_target else 0.0,
    })

    blocking = [c for c in checks if c["status"] in ("blocked", "warn")]
    return {
        "checks": checks,
        "ready": all(c["status"] == "done" for c in checks),
        "blocking_count": len(blocking),
    }


def savings_impact(goal: dict, cash: dict) -> dict:
    """How much sooner the down payment lands if identified savings are redirected.

    This is the whole point of measuring spending: the Savings tab produces a
    monthly number, and this converts it into months off the timeline.
    """
    try:
        found = insights.generate()
    except Exception as e:
        return {"available": False, "reason": f"{type(e).__name__}: {e}"}

    base = mortgage.savings_projection(
        target=cash["total"], saved=goal["saved_amount"],
        monthly_contribution=goal["monthly_contribution"], apy=goal["savings_apy"],
    )
    out = {"available": True, "base_months": base["months"],
           "base_date": base["target_date"], "options": []}

    for label, extra, note in (
        ("Easy wins only", found["easy_monthly_total"],
         "Cancel-and-move items: no change to how you live."),
        ("Conservative estimate", found["conservative_monthly"],
         "Largest opportunity per category, to avoid double-counting."),
        ("Everything identified", found["monthly_total"],
         "Ceiling if every item were acted on independently."),
    ):
        if extra <= 0:
            continue
        with_extra = mortgage.savings_projection(
            target=cash["total"], saved=goal["saved_amount"],
            monthly_contribution=goal["monthly_contribution"] + extra,
            apy=goal["savings_apy"],
        )
        months_saved = (
            base["months"] - with_extra["months"]
            if base["months"] is not None and with_extra["months"] is not None
            else None
        )
        out["options"].append({
            "label": label,
            "extra_monthly": round(extra, 2),
            "months": with_extra["months"],
            "target_date": with_extra["target_date"],
            "months_saved": months_saved,
            "note": note,
        })
    return out


def net_worth_context() -> dict:
    """Savings-rate context, so the contribution can be judged as a share of income."""
    flow = analytics.cash_flow(6)
    complete = [f for f in flow if f["month"] != date.today().strftime("%Y-%m")]
    if not complete:
        return {"available": False}
    import statistics
    incomes = [f["income"] for f in complete if f["income"] > 0]
    nets = [f["net"] for f in complete]
    return {
        "available": True,
        "median_monthly_income": round(statistics.median(incomes), 2) if incomes else 0.0,
        "median_monthly_net": round(statistics.median(nets), 2),
        "median_savings_rate": round(
            statistics.median([f["savings_rate"] for f in complete
                               if f["savings_rate"] is not None] or [0]), 1
        ),
        "months": len(complete),
    }


def loan_comparison(goal: dict) -> list[dict]:
    """The same house priced under every loan program.

    The comparison people actually need, because the monthly payment ranks the
    programs differently from the lifetime cost. FHA's monthly insurance is
    often *lower* than conventional PMI, while costing far more overall — below
    10% down it never falls away, so it runs for thirty years instead of about
    nine.
    """
    out = []
    for loan_type in mortgage.LOAN_TYPES:
        payment = _breakdown(goal, loan_type=loan_type)
        schedule = mortgage.amortization_schedule(
            loan=payment["loan_amount"],
            annual_pct=goal["interest_rate"],
            years=goal["loan_term_years"],
            home_value=goal["target_price"],
            pmi_rate=payment["mi_annual_pct"],
            mi_rule=payment["mi_rule"],
        )
        ratios = mortgage.dti(
            housing_monthly=payment["piti"],
            other_monthly_debts=goal["monthly_debts"],
            gross_annual_income=goal["gross_annual_income"],
        )
        cash = mortgage.cash_needed_at_closing(
            home_price=goal["target_price"],
            down_payment_pct=goal["down_payment_pct"],
            closing_cost_pct=goal["closing_cost_pct"],
        )
        out.append({
            "loan_type": loan_type,
            "label": {
                "conventional": "Conventional",
                "fha": "FHA",
                "va": "VA",
                "jumbo": "Jumbo",
            }[loan_type],
            "selected": loan_type == (goal.get("loan_type") or "conventional"),
            "monthly": payment["total_monthly"],
            "principal_interest": payment["principal_interest"],
            "mortgage_insurance": payment["pmi"],
            "mi_rule": payment["mi_rule"],
            "loan_amount": payment["loan_amount"],
            "financed_fee": payment["financed_fee"],
            "fee_label": payment["fee_label"],
            "cash_needed": cash["total"],
            "lifetime_interest": schedule["total_interest"],
            "lifetime_mi": schedule["total_pmi"],
            "lifetime_cost": round(
                schedule["total_interest"] + schedule["total_pmi"]
                + payment["financed_fee"], 2),
            "back_end_dti": ratios["back_end"],
            "verdict": ratios["verdict"],
            "warnings": payment["warnings"],
        })
    return out
