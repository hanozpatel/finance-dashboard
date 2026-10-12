"""Loan programs and per-state defaults.

The FHA cases matter most. Its monthly insurance is often *lower* than
conventional PMI while costing far more over the life of the loan, because
below 10% down it never terminates. A model that treated it as "conventional
with a different rate" would recommend it for exactly the wrong reason.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from services import mortgage as m  # noqa: E402
from services import states  # noqa: E402


# --- states ----------------------------------------------------------------

def test_every_state_and_dc_is_present_and_plausible():
    all_states = states.all_states()
    assert len(all_states) == 51  # 50 states + DC
    codes = {s["code"] for s in all_states}
    for expected in ("CA", "NY", "TX", "FL", "DC", "HI", "AK"):
        assert expected in codes
    for s in all_states:
        assert 0.1 < s["property_tax_rate"] < 3.0, s["code"]
        assert 500 < s["insurance_annual"] < 12_000, s["code"]
        assert 1.5 <= s["closing_cost_pct"] <= 6.0, s["code"]
        assert 100_000 < s["median_home_price"] < 1_500_000, s["code"]


def test_the_known_extremes_are_the_right_way_round():
    assert states.get("NJ")["property_tax_rate"] > states.get("CA")["property_tax_rate"]
    assert states.get("HI")["property_tax_rate"] == min(
        s["property_tax_rate"] for s in states.all_states())
    assert states.get("NJ")["property_tax_rate"] == max(
        s["property_tax_rate"] for s in states.all_states())
    # Florida insurance is the headline problem it is in real life.
    assert states.get("FL")["insurance_annual"] > 4_000


def test_lookup_is_case_insensitive_and_safe():
    assert states.get("ca")["code"] == "CA"
    assert states.get(" ny ")["code"] == "NY"
    assert states.get("ZZ") is None
    assert states.get(None) is None
    assert states.defaults_for("ZZ") == {}


def test_state_defaults_touch_only_what_varies_by_state():
    d = states.defaults_for("TX")
    # Price, income, rate and down payment are the buyer's situation, not the
    # state's, and must never be overwritten by picking a state.
    assert set(d) == {"property_tax_rate", "insurance_annual", "closing_cost_pct"}


def test_property_tax_actually_moves_the_payment():
    def monthly(state_code):
        s = states.get(state_code)
        return m.monthly_payment_breakdown(
            home_price=800_000, down_payment_pct=20, interest_rate=6.5,
            loan_term_years=30, property_tax_rate=s["property_tax_rate"],
            insurance_annual=s["insurance_annual"],
        )["total_monthly"]

    # New Jersey against Hawaii on the same house: over $1,200/mo apart.
    assert monthly("NJ") - monthly("HI") > 1_200


# --- loan programs ---------------------------------------------------------

def test_conventional_is_unchanged_by_the_program_layer():
    """The default path must produce exactly what it always did."""
    b = m.monthly_payment_breakdown(
        home_price=500_000, down_payment_pct=20, interest_rate=6.5,
        loan_term_years=30, property_tax_rate=1.1, insurance_annual=1800,
    )
    assert b["loan_amount"] == 400_000
    assert b["principal_interest"] == 2528.27
    assert b["financed_fee"] == 0.0
    assert b["pmi"] == 0.0


def test_fha_finances_its_upfront_premium_into_the_loan():
    b = m.monthly_payment_breakdown(
        home_price=400_000, down_payment_pct=3.5, interest_rate=6.5,
        loan_term_years=30, property_tax_rate=1.1, insurance_annual=1800,
        loan_type="fha",
    )
    base = 400_000 * (1 - 0.035)
    assert b["base_loan"] == round(base, 2)
    assert b["financed_fee"] == round(base * 0.0175, 2)
    # You borrow more than the price minus the down payment.
    assert b["loan_amount"] > base
    assert b["fee_label"].startswith("Upfront MIP")


def test_fha_below_10_percent_down_never_sheds_its_insurance():
    b = m.monthly_payment_breakdown(
        home_price=400_000, down_payment_pct=3.5, interest_rate=6.5,
        loan_term_years=30, property_tax_rate=1.1, insurance_annual=1800,
        loan_type="fha",
    )
    assert b["mi_rule"] == "never"
    assert any("life of the loan" in w for w in b["warnings"])

    s = m.amortization_schedule(
        loan=b["loan_amount"], annual_pct=6.5, years=30, home_value=400_000,
        pmi_rate=b["mi_annual_pct"], mi_rule="never",
    )
    assert s["pmi_ends_month"] is None
    # Charged in the final month, thirty years in.
    assert s["rows"][-1]["pmi"] > 0


def test_fha_at_10_percent_down_stops_after_eleven_years():
    b = m.monthly_payment_breakdown(
        home_price=400_000, down_payment_pct=10, interest_rate=6.5,
        loan_term_years=30, property_tax_rate=1.1, insurance_annual=1800,
        loan_type="fha",
    )
    assert b["mi_rule"] == "months:132"
    s = m.amortization_schedule(
        loan=b["loan_amount"], annual_pct=6.5, years=30, home_value=400_000,
        pmi_rate=b["mi_annual_pct"], mi_rule=b["mi_rule"],
    )
    assert s["rows"][131]["pmi"] > 0     # month 132, the last one charged
    assert s["rows"][132]["pmi"] == 0.0  # month 133, gone


def test_fha_costs_more_over_the_loan_despite_a_lower_monthly_premium():
    """The trap the comparison exists to expose."""
    kw = dict(home_price=600_000, interest_rate=6.5, loan_term_years=30,
              property_tax_rate=1.1, insurance_annual=1800, down_payment_pct=5)
    conv = m.monthly_payment_breakdown(pmi_rate=0.55, loan_type="conventional", **kw)
    fha = m.monthly_payment_breakdown(loan_type="fha", **kw)

    assert fha["pmi"] < conv["pmi"]          # cheaper every month...

    def lifetime(b):
        return m.amortization_schedule(
            loan=b["loan_amount"], annual_pct=6.5, years=30, home_value=600_000,
            pmi_rate=b["mi_annual_pct"], mi_rule=b["mi_rule"],
        )["total_pmi"]

    assert lifetime(fha) > lifetime(conv) * 2   # ...and far dearer in total


def test_va_charges_a_funding_fee_and_no_insurance_ever():
    b = m.monthly_payment_breakdown(
        home_price=500_000, down_payment_pct=0, interest_rate=6.5,
        loan_term_years=30, property_tax_rate=1.1, insurance_annual=1800,
        loan_type="va",
    )
    assert b["pmi"] == 0.0
    assert b["mi_rule"] == "none"
    assert b["financed_fee"] == round(500_000 * 0.0215, 2)
    assert b["down_payment"] == 0.0


def test_va_funding_fee_falls_with_a_larger_down_payment():
    assert m.va_funding_fee_pct(0) == 2.15
    assert m.va_funding_fee_pct(5) == 1.50
    assert m.va_funding_fee_pct(20) == 1.25
    # A repeat borrower pays more only in the zero-down band.
    assert m.va_funding_fee_pct(0, first_use=False) == 3.30
    assert m.va_funding_fee_pct(10, first_use=False) == 1.25


def test_jumbo_is_flagged_when_it_is_not_actually_jumbo():
    b = m.monthly_payment_breakdown(
        home_price=400_000, down_payment_pct=20, interest_rate=6.5,
        loan_term_years=30, property_tax_rate=1.1, insurance_annual=1800,
        loan_type="jumbo",
    )
    assert any("conforming limit" in w for w in b["warnings"])


def test_conventional_above_the_conforming_limit_is_flagged():
    b = m.monthly_payment_breakdown(
        home_price=2_000_000, down_payment_pct=20, interest_rate=6.5,
        loan_term_years=30, property_tax_rate=1.1, insurance_annual=1800,
        loan_type="conventional",
    )
    assert any("jumbo" in w for w in b["warnings"])


def test_fha_below_its_minimum_down_payment_is_flagged_not_refused():
    b = m.monthly_payment_breakdown(
        home_price=400_000, down_payment_pct=1, interest_rate=6.5,
        loan_term_years=30, property_tax_rate=1.1, insurance_annual=1800,
        loan_type="fha",
    )
    # Still calculates — telling someone why is more useful than refusing.
    assert b["total_monthly"] > 0
    assert any("3.5% down" in w for w in b["warnings"])


def test_an_unknown_loan_type_falls_back_to_conventional():
    p = m.loan_program(loan_type="nonsense", home_price=400_000, down_payment_pct=20)
    assert p["loan_type"] == "conventional"


@pytest.mark.parametrize("loan_type", m.LOAN_TYPES)
def test_every_program_produces_a_coherent_payment(loan_type):
    b = m.monthly_payment_breakdown(
        home_price=650_000, down_payment_pct=10, interest_rate=6.5,
        loan_term_years=30, property_tax_rate=1.1, insurance_annual=1800,
        hoa_monthly=150, pmi_rate=0.55, loan_type=loan_type,
    )
    parts = (b["principal_interest"] + b["property_tax"] + b["insurance"]
             + b["hoa"] + b["pmi"])
    assert abs(parts - b["total_monthly"]) < 0.02
    assert b["loan_amount"] == round(b["base_loan"] + b["financed_fee"], 2)
    assert 0 <= b["ltv"] <= 100
