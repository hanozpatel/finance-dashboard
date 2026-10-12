"""Plaid's conventions against this app's, which are opposite in two places.

These are the two mistakes that would be invisible in the UI until a total came
out backwards: Plaid signs an outflow positive, and reports a card balance as a
positive amount owed. Both are flipped in ``plaid_service``, so both are pinned
here — no network involved, because the normalisers are pure.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import categorize, plaid_service  # noqa: E402


def test_outflow_becomes_negative_and_inflow_positive():
    spend = plaid_service.normalize_transaction({
        "transaction_id": "t1", "account_id": "a1", "amount": 42.50,
        "date": "2026-09-01", "name": "PHILZ COFFEE", "pending": False,
    })
    assert spend["amount"] == -42.50

    deposit = plaid_service.normalize_transaction({
        "transaction_id": "t2", "account_id": "a1", "amount": -2400.00,
        "date": "2026-09-01", "name": "PAYROLL", "pending": False,
    })
    assert deposit["amount"] == 2400.00


def test_credit_card_balance_is_stored_as_a_liability():
    card = plaid_service.normalize_account({
        "account_id": "a1", "type": "credit", "subtype": "credit card",
        "name": "Chase Sapphire",
        "balance": {},
        "balances": {"current": 1250.00, "available": 8750.00, "limit": 10000.00,
                     "iso_currency_code": "USD"},
    }, "Chase")
    assert card["type"] == "credit"
    assert card["balance_current"] == -1250.00
    assert card["credit_limit"] == 10000.00


def test_credit_limit_is_derived_when_the_bank_omits_it():
    card = plaid_service.normalize_account({
        "account_id": "a2", "type": "credit", "subtype": "credit card",
        "name": "Card",
        "balances": {"current": 300.00, "available": 700.00, "limit": None},
    }, "Chase")
    # Owed plus remaining credit is the limit.
    assert card["credit_limit"] == 1000.00


def test_cash_and_brokerage_balances_pass_through_positive():
    checking = plaid_service.normalize_account({
        "account_id": "a3", "type": "depository", "subtype": "checking",
        "name": "Adv Plus Banking",
        "balances": {"current": 5400.25, "available": 5390.00},
    }, "Bank of America")
    assert checking["type"] == "depository"
    assert checking["balance_current"] == 5400.25

    brokerage = plaid_service.normalize_account({
        "account_id": "a4", "type": "brokerage", "subtype": "brokerage",
        "name": "Individual",
        "balances": {"current": 18250.10},
    }, "Robinhood")
    # The legacy "brokerage" type must still land in the investment bucket, or
    # the holdings would attach to an account the Investments tab never reads.
    assert brokerage["type"] == "investment"
    assert brokerage["balance_current"] == 18250.10


def test_personal_finance_category_survives_the_round_trip():
    """Plaid's taxonomy has to actually match the map that consumes it."""
    txn = plaid_service.normalize_transaction({
        "transaction_id": "t3", "account_id": "a1", "amount": 18.00,
        "date": "2026-09-02", "name": "SOME CAFE",
        "personal_finance_category": {"primary": "FOOD_AND_DRINK"},
    })
    assert txn["raw_category"] == "Food And Drink"

    key = txn["raw_category"].strip().lower().replace(" ", "_")
    assert categorize.PROVIDER_CATEGORY_MAP[key] == ("Dining", "Restaurants")


def test_every_plaid_primary_category_is_mapped():
    """An unmapped primary silently becomes Uncategorized, so none may be."""
    primaries = [
        "INCOME", "TRANSFER_IN", "TRANSFER_OUT", "LOAN_PAYMENTS", "BANK_FEES",
        "ENTERTAINMENT", "FOOD_AND_DRINK", "GENERAL_MERCHANDISE",
        "HOME_IMPROVEMENT", "MEDICAL", "PERSONAL_CARE", "GENERAL_SERVICES",
        "GOVERNMENT_AND_NON_PROFIT", "TRANSPORTATION", "TRAVEL",
        "RENT_AND_UTILITIES",
    ]
    for primary in primaries:
        txn = plaid_service.normalize_transaction({
            "transaction_id": f"t-{primary}", "account_id": "a1", "amount": 1.0,
            "date": "2026-09-02", "name": "X",
            "personal_finance_category": {"primary": primary},
        })
        key = txn["raw_category"].strip().lower().replace(" ", "_")
        assert key in categorize.PROVIDER_CATEGORY_MAP, f"{primary} is unmapped"


def test_link_kinds_request_only_what_they_need():
    assert plaid_service.LINK_KINDS["bank"]["products"] == ["transactions"]
    assert plaid_service.LINK_KINDS["investments"]["products"] == ["investments"]
