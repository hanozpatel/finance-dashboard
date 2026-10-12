"""Mortgage, affordability, and rent-vs-buy math.

Pure functions over plain numbers — no database, no request context — because
this is the part of the app that is either right or worthless, and that makes
it directly testable (tests/test_mortgage.py).

Rates arrive as percentages (6.5 means 6.5%), never as decimals. Every
function that takes a rate converts at its own boundary.
"""

from __future__ import annotations

from datetime import date

# PMI terminates automatically once the loan amortises to 78% of the home's
# original value (Homeowners Protection Act); a borrower may *request* removal
# at 80%. Both are reported so the difference is visible.
PMI_AUTO_TERMINATION_LTV = 0.78
PMI_REQUEST_LTV = 0.80

# Annual maintenance as a share of home value — the conventional 1% rule.
DEFAULT_MAINTENANCE_RATE = 0.01

# State and local tax deduction cap, and the standard deduction a single filer
# is measured against when deciding whether itemising is worth it. Both are
# parameters everywhere they matter; these are only the defaults.
SALT_CAP = 10_000.0
DEFAULT_STANDARD_DEDUCTION = 15_750.0

SELLING_COST_RATE = 0.06  # agent commissions + transfer costs on exit

# 2025 FHFA baseline. County-specific in high-cost areas (up to $1,209,750), and
# it is raised annually — so it is a parameter everywhere, and the UI says which
# year the default came from.
CONFORMING_LIMIT_2025 = 806_500

# FHA annual mortgage insurance premium, 30-year term.
FHA_MIP_ANNUAL_HIGH_LTV = 0.55   # LTV above 95%
FHA_MIP_ANNUAL_LOW_LTV = 0.50    # LTV at or below 95%
FHA_UPFRONT_MIP = 1.75           # of the base loan, financed into it
FHA_MIN_DOWN_PCT = 3.5
# With less than 10% down the premium runs for the life of the loan; at 10% or
# more it stops after 11 years.
FHA_MIP_YEARS_IF_10_PCT_DOWN = 11

# VA funding fee, purchase loans. Financed into the loan by default.
VA_FUNDING_FEE = {
    "first": {0.0: 2.15, 5.0: 1.50, 10.0: 1.25},
    "subsequent": {0.0: 3.30, 5.0: 1.50, 10.0: 1.25},
}

LOAN_TYPES = ("conventional", "fha", "va", "jumbo")


def monthly_rate(annual_pct: float) -> float:
    return annual_pct / 100.0 / 12.0


def payment_factor(annual_pct: float, years: int) -> float:
    """Monthly payment per dollar borrowed, for a fully amortising loan."""
    n = years * 12
    if n <= 0:
        return 0.0
    r = monthly_rate(annual_pct)
    if r == 0:
        return 1.0 / n
    g = (1 + r) ** n
    return r * g / (g - 1)


def monthly_principal_interest(loan: float, annual_pct: float, years: int) -> float:
    """Level principal-and-interest payment."""
    if loan <= 0:
        return 0.0
    return loan * payment_factor(annual_pct, years)


def monthly_payment_breakdown(
    *,
    home_price: float,
    down_payment_pct: float,
    interest_rate: float,
    loan_term_years: int,
    property_tax_rate: float,
    insurance_annual: float,
    hoa_monthly: float = 0.0,
    pmi_rate: float = 0.0,
    loan_type: str = "conventional",
    conforming_limit: float = CONFORMING_LIMIT_2025,
    va_first_use: bool = True,
) -> dict:
    """Full monthly housing cost at origination.

    For a conventional loan, mortgage insurance is charged only while
    loan-to-value exceeds 80% — at origination that means only when the down
    payment is under 20%. FHA and VA behave differently (see ``loan_program``),
    including financing a fee into the loan, which raises principal and interest
    above what the purchase price alone implies.
    """
    program = loan_program(
        loan_type=loan_type,
        home_price=home_price,
        down_payment_pct=down_payment_pct,
        pmi_rate=pmi_rate,
        conforming_limit=conforming_limit,
        va_first_use=va_first_use,
    )
    loan = program["total_loan"]
    pi = monthly_principal_interest(loan, interest_rate, loan_term_years)
    tax = home_price * (property_tax_rate / 100.0) / 12.0
    insurance = insurance_annual / 12.0
    pmi = program["monthly_mi"]

    return {
        "home_price": round(home_price, 2),
        "down_payment": program["down_payment"],
        "loan_amount": round(loan, 2),
        "base_loan": program["base_loan"],
        "financed_fee": program["financed_fee"],
        "fee_label": program["fee_label"],
        "ltv": program["ltv"],
        "loan_type": program["loan_type"],
        "mi_rule": program["mi_rule"],
        "mi_annual_pct": program["annual_mi_pct"],
        "warnings": program["warnings"],
        "principal_interest": round(pi, 2),
        "property_tax": round(tax, 2),
        "insurance": round(insurance, 2),
        "hoa": round(hoa_monthly, 2),
        "pmi": round(pmi, 2),
        "total_monthly": round(pi + tax + insurance + hoa_monthly + pmi, 2),
        # PITI in the lender's sense — what underwriting actually measures.
        "piti": round(pi + tax + insurance + pmi + hoa_monthly, 2),
    }


def amortization_schedule(
    *,
    loan: float,
    annual_pct: float,
    years: int,
    home_value: float,
    pmi_rate: float = 0.0,
    extra_monthly: float = 0.0,
    start: date | None = None,
    mi_rule: str = "ltv78",
) -> dict:
    """Month-by-month amortisation, with mortgage insurance ending per its rule.

    ``mi_rule`` is one of:

    * ``ltv78`` — conventional: terminates automatically at 78% of original value
    * ``never`` — FHA below 10% down: runs for the life of the loan
    * ``months:N`` — FHA at 10% or more down: 11 years
    * ``none`` — VA and jumbo: no mortgage insurance at all

    ``extra_monthly`` is applied to principal on top of the scheduled payment,
    which is what makes the payoff-acceleration comparison meaningful.
    """
    r = monthly_rate(annual_pct)
    base_payment = monthly_principal_interest(loan, annual_pct, years)
    balance = loan
    rows: list[dict] = []
    total_interest = 0.0
    total_pmi = 0.0
    pmi_monthly = loan * (pmi_rate / 100.0) / 12.0
    pmi_ends_month: int | None = None
    pmi_request_month: int | None = None
    start = start or date.today()

    # Hard ceiling at one extra year of payments: with a positive payment the
    # balance strictly decreases, so this only ever catches pathological input.
    max_months = years * 12 + 12

    month = 0
    while balance > 0.005 and month < max_months:
        month += 1
        interest = balance * r
        principal = base_payment - interest + extra_monthly
        if principal <= 0:
            # Payment does not cover interest — negative amortisation. Bail
            # rather than loop forever building a schedule that never ends.
            break
        if principal > balance:
            principal = balance
        ltv = balance / home_value if home_value > 0 else 0.0
        if mi_rule == "none" or pmi_monthly <= 0:
            charging_pmi = False
        elif mi_rule == "never":
            charging_pmi = True
        elif mi_rule.startswith("months:"):
            charging_pmi = month <= int(mi_rule.split(":", 1)[1])
        else:
            charging_pmi = ltv > PMI_AUTO_TERMINATION_LTV
        if charging_pmi:
            total_pmi += pmi_monthly
        elif pmi_monthly > 0 and pmi_ends_month is None:
            pmi_ends_month = month
        if pmi_request_month is None and pmi_monthly > 0 and ltv <= PMI_REQUEST_LTV:
            pmi_request_month = month

        balance -= principal
        total_interest += interest

        rows.append({
            "month": month,
            "year": (month - 1) // 12 + 1,
            "payment": round(interest + principal, 2),
            "interest": round(interest, 2),
            "principal": round(principal, 2),
            "pmi": round(pmi_monthly if charging_pmi else 0.0, 2),
            "balance": round(max(0.0, balance), 2),
            "cumulative_interest": round(total_interest, 2),
            "equity": round(home_value - max(0.0, balance), 2),
        })

    return {
        "rows": rows,
        "months": month,
        "payoff_years": round(month / 12.0, 2),
        "total_interest": round(total_interest, 2),
        "total_pmi": round(total_pmi, 2),
        "total_paid": round(loan + total_interest + total_pmi, 2),
        "pmi_ends_month": pmi_ends_month,
        "pmi_request_month": pmi_request_month,
        "monthly_pi": round(base_payment, 2),
    }


def dti(
    *,
    housing_monthly: float,
    other_monthly_debts: float,
    gross_annual_income: float,
) -> dict:
    """Front- and back-end debt-to-income, with the usual underwriting gates.

    28/36 is the conventional-conforming target, 43% the Qualified Mortgage
    ceiling, and 50% roughly where lenders stop even with compensating factors.
    """
    gross_monthly = gross_annual_income / 12.0
    if gross_monthly <= 0:
        return {"front_end": 0.0, "back_end": 0.0, "gross_monthly": 0.0,
                "verdict": "unknown", "passes_conventional": False,
                "passes_qm": False, "max_housing_at_36": 0.0, "headroom": 0.0}

    front = housing_monthly / gross_monthly * 100
    back = (housing_monthly + other_monthly_debts) / gross_monthly * 100
    max_housing_36 = gross_monthly * 0.36 - other_monthly_debts

    if back <= 36 and front <= 28:
        verdict = "comfortable"
    elif back <= 43:
        verdict = "qualifies"
    elif back <= 50:
        verdict = "stretched"
    else:
        verdict = "over_limit"

    return {
        "gross_monthly": round(gross_monthly, 2),
        "front_end": round(front, 2),
        "back_end": round(back, 2),
        "passes_conventional": front <= 28 and back <= 36,
        "passes_qm": back <= 43,
        "verdict": verdict,
        "max_housing_at_36": round(max(0.0, max_housing_36), 2),
        "headroom": round(max_housing_36 - housing_monthly, 2),
    }


def max_affordable_price(
    *,
    gross_annual_income: float,
    monthly_debts: float,
    down_payment_available: float,
    down_payment_pct: float,
    interest_rate: float,
    loan_term_years: int,
    property_tax_rate: float,
    insurance_annual: float,
    hoa_monthly: float = 0.0,
    pmi_rate: float = 0.0,
    closing_cost_pct: float = 3.0,
    back_end_dti_limit: float = 36.0,
) -> dict:
    """Largest purchase price that clears both DTI and available cash.

    Every monthly cost is linear in price, so this solves in closed form rather
    than bisecting: price x [ (1-d)·k + t/12 + pmi ] + fixed = budget.
    """
    gross_monthly = gross_annual_income / 12.0
    budget = gross_monthly * (back_end_dti_limit / 100.0) - monthly_debts
    if budget <= 0:
        return {"max_price": 0.0, "limited_by": "income",
                "monthly_budget": 0.0, "price_by_income": 0.0,
                "price_by_cash": 0.0, "down_payment": 0.0}

    d = down_payment_pct / 100.0
    k = payment_factor(interest_rate, loan_term_years)
    per_dollar = (1 - d) * k + (property_tax_rate / 100.0) / 12.0
    if d < 0.20:
        per_dollar += (1 - d) * (pmi_rate / 100.0) / 12.0

    fixed = insurance_annual / 12.0 + hoa_monthly
    price_by_income = max(0.0, (budget - fixed) / per_dollar) if per_dollar > 0 else 0.0

    # Cash has to cover the down payment *and* closing costs.
    cash_per_dollar = d + closing_cost_pct / 100.0
    price_by_cash = (down_payment_available / cash_per_dollar) if cash_per_dollar > 0 else 0.0

    max_price = min(price_by_income, price_by_cash)
    return {
        "max_price": round(max_price, 2),
        "price_by_income": round(price_by_income, 2),
        "price_by_cash": round(price_by_cash, 2),
        "limited_by": "cash" if price_by_cash < price_by_income else "income",
        "monthly_budget": round(budget, 2),
        "down_payment": round(max_price * d, 2),
    }


def savings_projection(
    *,
    target: float,
    saved: float,
    monthly_contribution: float,
    apy: float,
) -> dict:
    """Months until the down-payment fund reaches ``target``.

    Closed-form inverse of the future-value-of-an-annuity formula; APY is
    treated as compounding monthly, which is how high-yield savings quote it.
    """
    if saved >= target:
        return {"months": 0, "years": 0.0, "reachable": True,
                "target_date": date.today().isoformat(), "shortfall": 0.0,
                "projected_interest": 0.0}

    i = apy / 100.0 / 12.0
    if monthly_contribution <= 0 and i <= 0:
        return {"months": None, "years": None, "reachable": False,
                "target_date": None, "shortfall": round(target - saved, 2),
                "projected_interest": 0.0}

    if i == 0:
        months = (target - saved) / monthly_contribution
    else:
        # target + C/i = (1+i)^n (saved + C/i)  ->  solve for n
        import math
        c_over_i = monthly_contribution / i
        num = target + c_over_i
        den = saved + c_over_i
        if den <= 0 or num / den <= 0:
            return {"months": None, "years": None, "reachable": False,
                    "target_date": None, "shortfall": round(target - saved, 2),
                    "projected_interest": 0.0}
        months = math.log(num / den) / math.log(1 + i)

    months_i = int(months) + (1 if months % 1 else 0)
    contributed = monthly_contribution * months_i
    interest = max(0.0, target - saved - contributed)

    today = date.today()
    total_month = today.month - 1 + months_i
    target_date = date(today.year + total_month // 12, total_month % 12 + 1, 1)

    return {
        "months": months_i,
        "years": round(months_i / 12.0, 2),
        "reachable": True,
        "target_date": target_date.isoformat(),
        "shortfall": round(target - saved, 2),
        "projected_interest": round(interest, 2),
    }


def cash_needed_at_closing(
    *, home_price: float, down_payment_pct: float, closing_cost_pct: float
) -> dict:
    down = home_price * down_payment_pct / 100.0
    closing = home_price * closing_cost_pct / 100.0
    return {
        "down_payment": round(down, 2),
        "closing_costs": round(closing, 2),
        "total": round(down + closing, 2),
    }


def rent_vs_buy(
    *,
    home_price: float,
    down_payment_pct: float,
    interest_rate: float,
    loan_term_years: int,
    property_tax_rate: float,
    insurance_annual: float,
    hoa_monthly: float,
    pmi_rate: float,
    closing_cost_pct: float,
    current_rent: float,
    rent_inflation: float,
    home_appreciation: float,
    investment_return: float,
    marginal_tax_rate: float,
    horizon_years: int = 7,
    maintenance_rate: float = DEFAULT_MAINTENANCE_RATE,
    standard_deduction: float = DEFAULT_STANDARD_DEDUCTION,
) -> dict:
    """Compare ending net worth after ``horizon_years`` of buying vs renting.

    The renter is assumed to invest the cash a buyer sinks into down payment and
    closing costs, plus any month-to-month difference in housing cost, at
    ``investment_return``. That opportunity cost is the single biggest reason a
    naive "rent is throwing money away" comparison misleads.

    Mortgage interest and property tax are only worth something at tax time to
    the extent they exceed the standard deduction, and property tax counts
    toward that only up to the SALT cap.
    """
    sched = amortization_schedule(
        loan=home_price * (1 - down_payment_pct / 100.0),
        annual_pct=interest_rate,
        years=loan_term_years,
        home_value=home_price,
        pmi_rate=pmi_rate,
    )
    rows = sched["rows"]
    upfront = cash_needed_at_closing(
        home_price=home_price,
        down_payment_pct=down_payment_pct,
        closing_cost_pct=closing_cost_pct,
    )

    r_inv = investment_return / 100.0 / 12.0
    portfolio = upfront["total"]          # renter invests the buyer's upfront cash
    # The buyer's side of the same coin: the tax benefit is cash back, and it
    # compounds at the same rate the renter's portfolio does. Without this the
    # comparison silently penalises buying.
    buyer_portfolio = 0.0
    rent = current_rent
    home_value = home_price
    buyer_out = upfront["total"]
    renter_out = 0.0
    yearly: list[dict] = []

    for year in range(1, horizon_years + 1):
        year_interest = 0.0
        year_tax = home_value * property_tax_rate / 100.0
        year_maint = home_value * maintenance_rate
        year_buy_cost = 0.0

        for m in range((year - 1) * 12, year * 12):
            row = rows[m] if m < len(rows) else None
            interest = row["interest"] if row else 0.0
            principal = row["principal"] if row else 0.0
            pmi = row["pmi"] if row else 0.0
            year_interest += interest

            buy_monthly = (
                interest + principal + pmi
                + year_tax / 12 + insurance_annual / 12
                + hoa_monthly + year_maint / 12
            )
            year_buy_cost += buy_monthly

            # The renter banks the difference (or draws down when rent is higher)
            # and earns a return on the whole pot.
            portfolio = portfolio * (1 + r_inv) + (buy_monthly - rent)
            renter_out += rent
            rent *= (1 + rent_inflation / 100.0) ** (1 / 12)

        itemizable = year_interest + min(year_tax, SALT_CAP)
        tax_benefit = max(0.0, itemizable - standard_deduction) * marginal_tax_rate / 100.0
        buyer_out += year_buy_cost - tax_benefit
        buyer_portfolio = buyer_portfolio * (1 + investment_return / 100.0) + tax_benefit

        home_value *= (1 + home_appreciation / 100.0)
        balance = rows[year * 12 - 1]["balance"] if year * 12 - 1 < len(rows) else 0.0

        buyer_equity = home_value * (1 - SELLING_COST_RATE) - balance
        buyer_total = buyer_equity + buyer_portfolio
        yearly.append({
            "year": year,
            "home_value": round(home_value, 2),
            "loan_balance": round(balance, 2),
            "buyer_equity": round(buyer_equity, 2),
            "buyer_net_worth": round(buyer_total, 2),
            "renter_net_worth": round(portfolio, 2),
            "advantage": round(buyer_total - portfolio, 2),
            "annual_tax_benefit": round(tax_benefit, 2),
            "monthly_rent": round(rent, 2),
            "buyer_monthly_cost": round(year_buy_cost / 12, 2),
        })

    final = yearly[-1] if yearly else {}
    breakeven = next((y["year"] for y in yearly if y["advantage"] > 0), None)

    return {
        "horizon_years": horizon_years,
        "yearly": yearly,
        "buyer_net_worth": final.get("buyer_net_worth", 0.0),
        "renter_net_worth": final.get("renter_net_worth", 0.0),
        "advantage": final.get("advantage", 0.0),
        "verdict": "buy" if final.get("advantage", 0) > 0 else "rent",
        "breakeven_year": breakeven,
        "total_spent_buying": round(buyer_out, 2),
        "total_spent_renting": round(renter_out, 2),
    }


# ---------------------------------------------------------------------------
# Loan programs
#
# Conventional PMI is not the only kind of mortgage insurance, and the
# differences change the answer materially. FHA charges an upfront premium that
# is financed into the loan and — if you put down less than 10% — an annual
# premium that never goes away, so "cheap down payment" costs more over 30 years
# than the monthly figure suggests. VA charges no insurance at all but takes a
# one-off funding fee. Modelling them all as "conventional with a different rate"
# would understate FHA and overstate VA.
# ---------------------------------------------------------------------------


def va_funding_fee_pct(down_payment_pct: float, first_use: bool = True) -> float:
    table = VA_FUNDING_FEE["first" if first_use else "subsequent"]
    if down_payment_pct >= 10:
        return table[10.0]
    if down_payment_pct >= 5:
        return table[5.0]
    return table[0.0]


def fha_annual_mip_pct(ltv: float) -> float:
    return FHA_MIP_ANNUAL_HIGH_LTV if ltv > 95 else FHA_MIP_ANNUAL_LOW_LTV


def loan_program(
    *,
    loan_type: str,
    home_price: float,
    down_payment_pct: float,
    pmi_rate: float = 0.55,
    conforming_limit: float = CONFORMING_LIMIT_2025,
    va_first_use: bool = True,
) -> dict:
    """Resolve a loan program into the numbers the payment math needs.

    Returns the base loan, any fee financed into it, the total borrowed, the
    annual mortgage-insurance rate and when it stops, plus any warnings about
    eligibility. Warnings are returned rather than raised: telling someone their
    down payment is below the FHA minimum is more useful than refusing to
    calculate.
    """
    loan_type = (loan_type or "conventional").lower()
    if loan_type not in LOAN_TYPES:
        loan_type = "conventional"

    down_payment = home_price * down_payment_pct / 100.0
    base_loan = max(0.0, home_price - down_payment)
    ltv = (base_loan / home_price * 100.0) if home_price > 0 else 0.0

    financed_fee = 0.0
    fee_label = None
    annual_mi_pct = 0.0
    mi_rule = "none"
    warnings: list[str] = []

    if loan_type == "conventional":
        if base_loan > conforming_limit:
            warnings.append(
                f"This loan is ${base_loan - conforming_limit:,.0f} above the "
                f"${conforming_limit:,.0f} conforming limit, so it would price as a "
                f"jumbo rather than a conventional loan."
            )
        if ltv > 80:
            annual_mi_pct = pmi_rate
            mi_rule = "ltv78"

    elif loan_type == "fha":
        if down_payment_pct < FHA_MIN_DOWN_PCT:
            warnings.append(
                f"FHA requires at least {FHA_MIN_DOWN_PCT}% down (10% below a 580 "
                f"credit score); this plan puts down {down_payment_pct:.1f}%."
            )
        financed_fee = base_loan * FHA_UPFRONT_MIP / 100.0
        fee_label = f"Upfront MIP ({FHA_UPFRONT_MIP}%)"
        annual_mi_pct = fha_annual_mip_pct(ltv)
        if down_payment_pct >= 10:
            mi_rule = f"months:{FHA_MIP_YEARS_IF_10_PCT_DOWN * 12}"
        else:
            # The part people miss: below 10% down the premium is permanent, and
            # the only way out is refinancing.
            mi_rule = "never"
            warnings.append(
                "With less than 10% down, FHA mortgage insurance lasts the life of "
                "the loan — it does not fall away at 78% like conventional PMI. "
                "Escaping it means refinancing."
            )

    elif loan_type == "va":
        fee_pct = va_funding_fee_pct(down_payment_pct, va_first_use)
        financed_fee = base_loan * fee_pct / 100.0
        fee_label = f"VA funding fee ({fee_pct}%)"
        mi_rule = "none"
        warnings.append(
            "VA loans charge no mortgage insurance at any down payment, which is "
            "usually worth more than the one-off funding fee. Veterans with a "
            "service-connected disability rating are exempt from the fee entirely."
        )

    elif loan_type == "jumbo":
        if base_loan <= conforming_limit:
            warnings.append(
                f"This loan is within the ${conforming_limit:,.0f} conforming limit, "
                f"so a conventional loan would almost certainly price better."
            )
        if down_payment_pct < 10:
            warnings.append(
                "Jumbo lenders typically want at least 10-20% down and stronger "
                "reserves than a conforming loan."
            )
        mi_rule = "none"

    total_loan = base_loan + financed_fee
    return {
        "loan_type": loan_type,
        "down_payment": round(down_payment, 2),
        "base_loan": round(base_loan, 2),
        "financed_fee": round(financed_fee, 2),
        "fee_label": fee_label,
        "total_loan": round(total_loan, 2),
        "ltv": round(ltv, 2),
        "annual_mi_pct": annual_mi_pct,
        "monthly_mi": round(total_loan * annual_mi_pct / 100.0 / 12.0, 2),
        "mi_rule": mi_rule,
        "warnings": warnings,
        "conforming_limit": conforming_limit,
    }
