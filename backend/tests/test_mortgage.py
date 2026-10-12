"""Mortgage math checked against independently-known values.

The reference figures come from the standard amortisation formula as published
by lenders, not from this module, so a regression here means the math changed.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import mortgage as m


def test_monthly_pi_matches_published_figure():
    # $500,000 at 6.5% over 30 years is $3,160.34/mo.
    assert round(m.monthly_principal_interest(500_000, 6.5, 30), 2) == 3160.34
    # $300,000 at 7.0% over 30 years is $1,995.91/mo.
    assert round(m.monthly_principal_interest(300_000, 7.0, 30), 2) == 1995.91
    # A 15-year term on the same loan costs more monthly, far less in total.
    assert round(m.monthly_principal_interest(300_000, 7.0, 15), 2) == 2696.48


def test_zero_interest_is_straight_division():
    assert round(m.monthly_principal_interest(300_000, 0.0, 10), 2) == 2500.00


def test_zero_loan_has_no_payment():
    assert m.monthly_principal_interest(0, 6.5, 30) == 0.0


def test_breakdown_adds_up_and_respects_pmi_threshold():
    with_pmi = m.monthly_payment_breakdown(
        home_price=600_000, down_payment_pct=10, interest_rate=6.5,
        loan_term_years=30, property_tax_rate=1.2, insurance_annual=1800,
        hoa_monthly=150, pmi_rate=0.6,
    )
    assert with_pmi["loan_amount"] == 540_000
    assert with_pmi["ltv"] == 90.0
    assert with_pmi["pmi"] == round(540_000 * 0.006 / 12, 2) == 270.0
    parts = (with_pmi["principal_interest"] + with_pmi["property_tax"]
             + with_pmi["insurance"] + with_pmi["hoa"] + with_pmi["pmi"])
    assert round(parts, 2) == with_pmi["total_monthly"]

    # 20% down is exactly at the threshold, so no PMI is charged.
    at_20 = m.monthly_payment_breakdown(
        home_price=600_000, down_payment_pct=20, interest_rate=6.5,
        loan_term_years=30, property_tax_rate=1.2, insurance_annual=1800,
        pmi_rate=0.6,
    )
    assert at_20["pmi"] == 0.0
    assert at_20["ltv"] == 80.0


def test_schedule_pays_the_loan_off_exactly_on_term():
    s = m.amortization_schedule(loan=500_000, annual_pct=6.5, years=30,
                               home_value=625_000)
    assert s["months"] == 360
    assert s["rows"][-1]["balance"] == 0.0
    # Principal repaid must equal the loan.
    assert round(sum(r["principal"] for r in s["rows"]), 0) == 500_000
    # Total interest on this loan is ~$637,700.
    assert 637_000 < s["total_interest"] < 638_500


def test_extra_payments_shorten_the_term_and_cut_interest():
    base = m.amortization_schedule(loan=500_000, annual_pct=6.5, years=30,
                                  home_value=625_000)
    extra = m.amortization_schedule(loan=500_000, annual_pct=6.5, years=30,
                                    home_value=625_000, extra_monthly=500)
    assert extra["months"] < base["months"]
    assert extra["total_interest"] < base["total_interest"]


def test_pmi_drops_off_at_78_percent_ltv():
    # 10% down on a $500k home: PMI runs until the balance hits 78% of value.
    s = m.amortization_schedule(loan=450_000, annual_pct=6.5, years=30,
                               home_value=500_000, pmi_rate=0.6)
    assert s["pmi_ends_month"] is not None
    # Request-at-80% must come no later than automatic-at-78%.
    assert s["pmi_request_month"] <= s["pmi_ends_month"]
    ends = s["pmi_ends_month"]
    assert s["rows"][ends - 2]["pmi"] > 0      # still charged the month before
    assert s["rows"][ends - 1]["pmi"] == 0.0   # gone from here on
    # And the balance really is at/below the threshold by then.
    assert s["rows"][ends - 1]["balance"] <= 500_000 * 0.78


def test_no_pmi_means_no_termination_month():
    s = m.amortization_schedule(loan=400_000, annual_pct=6.5, years=30,
                               home_value=500_000, pmi_rate=0.0)
    assert s["pmi_ends_month"] is None
    assert s["total_pmi"] == 0.0


def test_dti_gates():
    # $180k income, $3,500 housing, $450 other debt.
    d = m.dti(housing_monthly=3500, other_monthly_debts=450,
              gross_annual_income=180_000)
    assert d["gross_monthly"] == 15_000.0
    assert d["front_end"] == round(3500 / 15000 * 100, 2)
    assert d["back_end"] == round(3950 / 15000 * 100, 2)
    assert d["passes_conventional"] is True
    assert d["verdict"] == "comfortable"

    # 6,900 / 15,000 = 46% back-end: past the 43% QM ceiling, short of 50%.
    stretched = m.dti(housing_monthly=6000, other_monthly_debts=900,
                      gross_annual_income=180_000)
    assert stretched["back_end"] == 46.0
    assert stretched["verdict"] == "stretched"
    assert stretched["passes_qm"] is False
    assert stretched["passes_conventional"] is False

    # 43% exactly is still a Qualified Mortgage.
    at_qm = m.dti(housing_monthly=6450, other_monthly_debts=0,
                  gross_annual_income=180_000)
    assert at_qm["back_end"] == 43.0 and at_qm["passes_qm"] is True

    over = m.dti(housing_monthly=8000, other_monthly_debts=500,
                 gross_annual_income=180_000)
    assert over["verdict"] == "over_limit"


def test_dti_zero_income_does_not_divide_by_zero():
    d = m.dti(housing_monthly=3000, other_monthly_debts=0, gross_annual_income=0)
    assert d["front_end"] == 0.0 and d["verdict"] == "unknown"


def test_affordability_is_consistent_with_the_payment_it_implies():
    a = m.max_affordable_price(
        gross_annual_income=180_000, monthly_debts=450,
        down_payment_available=150_000, down_payment_pct=20,
        interest_rate=6.5, loan_term_years=30, property_tax_rate=1.1,
        insurance_annual=1800, hoa_monthly=0, pmi_rate=0.55,
        closing_cost_pct=3.0,
    )
    # Feed the answer back through the payment calculator: the resulting
    # housing cost must sit at the DTI budget it was solved for.
    limiting = min(a["price_by_income"], a["price_by_cash"])
    b = m.monthly_payment_breakdown(
        home_price=a["price_by_income"], down_payment_pct=20,
        interest_rate=6.5, loan_term_years=30, property_tax_rate=1.1,
        insurance_annual=1800, pmi_rate=0.55,
    )
    assert abs(b["total_monthly"] - a["monthly_budget"]) < 1.0
    assert a["max_price"] == round(limiting, 2)
    # $150k of cash at 20% down + 3% closing caps the price at ~$652k.
    assert round(a["price_by_cash"]) == round(150_000 / 0.23)


def test_affordability_reports_which_constraint_binds():
    cash_poor = m.max_affordable_price(
        gross_annual_income=400_000, monthly_debts=0,
        down_payment_available=40_000, down_payment_pct=20,
        interest_rate=6.5, loan_term_years=30, property_tax_rate=1.1,
        insurance_annual=1800,
    )
    assert cash_poor["limited_by"] == "cash"

    income_poor = m.max_affordable_price(
        gross_annual_income=70_000, monthly_debts=800,
        down_payment_available=500_000, down_payment_pct=20,
        interest_rate=6.5, loan_term_years=30, property_tax_rate=1.1,
        insurance_annual=1800,
    )
    assert income_poor["limited_by"] == "income"


def test_affordability_with_no_room_returns_zero():
    a = m.max_affordable_price(
        gross_annual_income=30_000, monthly_debts=2000,
        down_payment_available=10_000, down_payment_pct=20,
        interest_rate=6.5, loan_term_years=30, property_tax_rate=1.1,
        insurance_annual=1800,
    )
    assert a["max_price"] == 0.0 and a["limited_by"] == "income"


def test_savings_projection_round_trips_through_future_value():
    p = m.savings_projection(target=130_000, saved=40_000,
                             monthly_contribution=2500, apy=4.0)
    assert p["reachable"] is True
    n, i, C, S = p["months"], 0.04 / 12, 2500, 40_000
    fv = S * (1 + i) ** n + C * (((1 + i) ** n - 1) / i)
    assert fv >= 130_000                      # target is actually met
    prev = S * (1 + i) ** (n - 1) + C * (((1 + i) ** (n - 1) - 1) / i)
    assert prev < 130_000                     # and not a month later than needed


def test_savings_projection_already_there():
    p = m.savings_projection(target=100_000, saved=120_000,
                             monthly_contribution=0, apy=4.0)
    assert p["months"] == 0 and p["reachable"] is True


def test_savings_projection_unreachable_without_contributions_or_yield():
    p = m.savings_projection(target=100_000, saved=10_000,
                             monthly_contribution=0, apy=0)
    assert p["reachable"] is False and p["months"] is None


def test_zero_apy_is_plain_division():
    p = m.savings_projection(target=50_000, saved=10_000,
                             monthly_contribution=1000, apy=0)
    assert p["months"] == 40


def test_closing_cash():
    c = m.cash_needed_at_closing(home_price=650_000, down_payment_pct=20,
                                 closing_cost_pct=3)
    assert c["down_payment"] == 130_000.0
    assert c["closing_costs"] == 19_500.0
    assert c["total"] == 149_500.0


def test_rent_vs_buy_produces_a_full_horizon_and_a_verdict():
    r = m.rent_vs_buy(
        home_price=650_000, down_payment_pct=20, interest_rate=6.5,
        loan_term_years=30, property_tax_rate=1.1, insurance_annual=1800,
        hoa_monthly=0, pmi_rate=0.55, closing_cost_pct=3,
        current_rent=3200, rent_inflation=3.0, home_appreciation=3.5,
        investment_return=7.0, marginal_tax_rate=32, horizon_years=7,
    )
    assert len(r["yearly"]) == 7
    assert r["verdict"] in ("buy", "rent")
    assert r["yearly"][0]["year"] == 1
    # Loan balance must fall every year.
    balances = [y["loan_balance"] for y in r["yearly"]]
    assert balances == sorted(balances, reverse=True)
    # Rent must rise with inflation.
    assert r["yearly"][-1]["monthly_rent"] > r["yearly"][0]["monthly_rent"]


def test_faster_appreciation_favours_buying():
    kw = dict(
        home_price=650_000, down_payment_pct=20, interest_rate=6.5,
        loan_term_years=30, property_tax_rate=1.1, insurance_annual=1800,
        hoa_monthly=0, pmi_rate=0.55, closing_cost_pct=3,
        current_rent=3200, rent_inflation=3.0, investment_return=7.0,
        marginal_tax_rate=32, horizon_years=10,
    )
    slow = m.rent_vs_buy(home_appreciation=1.0, **kw)
    fast = m.rent_vs_buy(home_appreciation=7.0, **kw)
    assert fast["advantage"] > slow["advantage"]
