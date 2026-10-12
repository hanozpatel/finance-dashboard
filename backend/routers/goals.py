"""The house goal and the standalone mortgage calculator."""

from fastapi import APIRouter, Query

from models.schemas import GoalUpdate, MortgageQuote
from services import goals as svc
from services import mortgage, states

router = APIRouter(prefix="/api/goals", tags=["goals"])


@router.get("/house")
def get_house_plan(horizon_years: int = Query(7, ge=1, le=30),
                   extra_monthly: float = Query(0, ge=0)):
    plan = svc.plan(horizon_years=horizon_years, extra_monthly=extra_monthly)
    plan["income_context"] = svc.net_worth_context()
    return plan


@router.get("/states")
def list_states():
    """Per-state defaults, plus the caveats that make them safe to use."""
    return {
        "states": states.all_states(),
        "note": (
            "Effective statewide averages, offered as a starting point. County and "
            "city rates are what actually apply, and within Texas, Illinois, and New "
            "York the spread inside the state exceeds the spread between states. "
            "Replace them with real quotes before making an offer."
        ),
    }


@router.put("/house")
def update_house_goal(body: GoalUpdate, apply_state_defaults: bool = False):
    """Update the plan.

    ``apply_state_defaults`` fills in property tax, insurance, and closing costs
    from the newly chosen state. It is opt-in so that editing one of those fields
    by hand is not undone the next time anything else is saved.
    """
    svc.update_goal(body.model_dump(exclude_none=True),
                    apply_state_defaults=apply_state_defaults)
    return svc.plan()


@router.post("/mortgage")
def mortgage_quote(body: MortgageQuote, schedule: bool = False):
    """Standalone mortgage calculator.

    Independent of the saved goal so a house found on Zillow can be priced
    without overwriting the plan. ``schedule=true`` adds the full amortisation
    table, which is large, so it is opt-in.
    """
    payment = mortgage.monthly_payment_breakdown(
        home_price=body.home_price,
        down_payment_pct=body.down_payment_pct,
        interest_rate=body.interest_rate,
        loan_term_years=body.loan_term_years,
        property_tax_rate=body.property_tax_rate,
        insurance_annual=body.insurance_annual,
        hoa_monthly=body.hoa_monthly,
        pmi_rate=body.pmi_rate,
        loan_type=body.loan_type,
        conforming_limit=body.conforming_limit,
        va_first_use=body.va_first_use,
    )
    amortization = mortgage.amortization_schedule(
        loan=payment["loan_amount"],
        annual_pct=body.interest_rate,
        years=body.loan_term_years,
        home_value=body.home_price,
        pmi_rate=payment["mi_annual_pct"],
        mi_rule=payment["mi_rule"],
        extra_monthly=body.extra_monthly,
    )
    baseline = amortization
    if body.extra_monthly > 0:
        baseline = mortgage.amortization_schedule(
            loan=payment["loan_amount"],
            annual_pct=body.interest_rate,
            years=body.loan_term_years,
            home_value=body.home_price,
            pmi_rate=payment["mi_annual_pct"],
            mi_rule=payment["mi_rule"],
        )

    out = {
        "payment": payment,
        "cash_needed": mortgage.cash_needed_at_closing(
            home_price=body.home_price,
            down_payment_pct=body.down_payment_pct,
            closing_cost_pct=body.closing_cost_pct,
        ),
        "totals": {k: v for k, v in amortization.items() if k != "rows"},
        "yearly": _yearly(amortization["rows"]),
    }
    if body.extra_monthly > 0:
        out["extra_payment_effect"] = {
            "extra_monthly": body.extra_monthly,
            "months_saved": baseline["months"] - amortization["months"],
            "interest_saved": round(
                baseline["total_interest"] - amortization["total_interest"], 2),
            "payoff_years": amortization["payoff_years"],
            "baseline_payoff_years": baseline["payoff_years"],
        }
    if body.gross_annual_income > 0:
        out["dti"] = mortgage.dti(
            housing_monthly=payment["piti"],
            other_monthly_debts=body.monthly_debts,
            gross_annual_income=body.gross_annual_income,
        )
        out["affordability"] = mortgage.max_affordable_price(
            gross_annual_income=body.gross_annual_income,
            monthly_debts=body.monthly_debts,
            down_payment_available=body.home_price * body.down_payment_pct / 100,
            down_payment_pct=body.down_payment_pct,
            interest_rate=body.interest_rate,
            loan_term_years=body.loan_term_years,
            property_tax_rate=body.property_tax_rate,
            insurance_annual=body.insurance_annual,
            hoa_monthly=body.hoa_monthly,
            pmi_rate=body.pmi_rate,
            closing_cost_pct=body.closing_cost_pct,
        )
    if schedule:
        out["schedule"] = amortization["rows"]
    return out


def _yearly(rows: list[dict]) -> list[dict]:
    """Collapse 360 monthly rows into one row per year, for charting."""
    out: list[dict] = []
    for row in rows:
        year = row["year"]
        if not out or out[-1]["year"] != year:
            out.append({"year": year, "interest": 0.0, "principal": 0.0,
                        "pmi": 0.0, "balance": row["balance"]})
        out[-1]["interest"] += row["interest"]
        out[-1]["principal"] += row["principal"]
        out[-1]["pmi"] += row["pmi"]
        out[-1]["balance"] = row["balance"]
    for entry in out:
        for key in ("interest", "principal", "pmi"):
            entry[key] = round(entry[key], 2)
    return out
