"""Merchant normalisation and categorisation against real-world feed strings.

Every description below is the shape an actual Chase or Bank of America export
uses, including the processor prefixes and trailing transaction ids.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.categorize import normalize_merchant, categorize


def k(desc, merchant=None):
    return normalize_merchant(desc, merchant)[1]


def test_processor_prefixes_are_stripped():
    assert k("SQ *BLUE BOTTLE COFFEE  OAKLAND CA") == "blue bottle coffee"
    assert k("TST* NOPA SAN FRANCISCO CA") == "nopa"
    assert k("PY *SOME VENDOR") == "some vendor"


def test_bank_ceremony_is_stripped():
    assert k("PURCHASE AUTHORIZED ON 09/12 TRADER JOE S #123 SAN FRANCISCO CA") == "trader joe s"
    assert k("CHECKCARD 0910 WHOLE FOODS MKT SAN FRANCISCO CA") == "whole foods mkt"
    assert k("RECURRING PAYMENT AUTHORIZED ON 08/03 NETFLIX.COM") == "netflix"


def test_store_numbers_and_ids_collapse_to_one_key():
    variants = [
        "STARBUCKS STORE 10432",
        "STARBUCKS #567",
        "SQ *STARBUCKS  SEATTLE WA",
        "STARBUCKS 0041",
    ]
    keys = {k(v) for v in variants}
    assert keys == {"starbucks"}, keys


def test_amazon_order_ids_are_discarded():
    assert k("AMAZON.COM*2K4LQ1OG3 AMZN.COM/BILL WA") == "amazon amzn bill"
    # "US" is corporate filler, so the per-order id and the country both go.
    assert k("AMZN MKTP US*RT4G88H13") == "amzn mktp"
    assert k("AMZN MKTP US*9Q8H11XY2") == "amzn mktp"
    # Retail and marketplace stay distinct keys but must categorise the same.
    for desc in ["AMAZON.COM*2K4LQ1OG3 AMZN.COM/BILL WA", "AMZN MKTP US*RT4G88H13"]:
        assert cat(desc)[0] == "Shopping"


def test_trailing_state_code_removed_but_leading_words_survive():
    assert k("IN N OUT BURGER #231 OAKLAND CA") == "in n out burger"
    # A two-letter word that is a state code only drops when it trails.
    assert k("OR ELSE CAFE NY") == "or else cafe"


def test_provider_merchant_name_is_preferred_when_present():
    display, key = normalize_merchant("TST* NOPA 4412 SAN FRANCISCO CA", "Nopa")
    assert key == "nopa" and display == "Nopa"


def test_empty_description_does_not_crash():
    assert normalize_merchant("", None) == ("Unknown", "unknown")
    assert normalize_merchant("   ") == ("Unknown", "unknown")


def test_all_numeric_description_still_yields_a_key():
    _, key = normalize_merchant("123456789")
    assert key != ""


def cat(desc, amount=-10.0, account_type="credit", merchant=None, raw=None):
    display, key = normalize_merchant(desc, merchant)
    return categorize(description=desc, merchant=display, merchant_key=key,
                      raw_category=raw, amount=amount, account_type=account_type,
                      rules=[])


def test_specific_keyword_beats_the_generic_one_it_contains():
    assert cat("UBER EATS 8005928996 CA")[:2] == ("Dining", "Delivery")
    assert cat("UBER TRIP 8005928996 CA")[:2] == ("Transportation", "Rideshare")


def test_word_boundaries_prevent_false_matches():
    # "bar" must not match inside "Barnes".
    assert cat("BARNES & NOBLE #2043")[0] != "Dining"
    # ...but a real bar still lands in Dining.
    assert cat("BAR CRUDO SAN FRANCISCO CA")[:2] == ("Dining", "Bars")
    # "rent" must not match inside "Enterprise Rent".
    assert cat("ENTERPRISE RENT A CAR")[:2] == ("Travel", "Car Rental")


def test_card_payments_are_transfers_not_spending():
    c, s, is_transfer = cat("PAYMENT THANK YOU - MOBILE", amount=500.0)
    assert c == "Transfer" and is_transfer is True
    c2, _, t2 = cat("CHASE CREDIT CRD AUTOPAY", amount=-500.0, account_type="depository")
    assert c2 == "Transfer" and t2 is True


def test_zelle_and_venmo_are_transfers():
    assert cat("ZELLE PAYMENT TO JOHN SMITH", account_type="depository")[2] is True
    assert cat("VENMO PAYMENT 1029384756", account_type="depository")[2] is True


def test_brokerage_contributions_are_transfers_not_expenses():
    c, s, t = cat("ROBINHOOD FUNDING", amount=-1000.0, account_type="depository")
    assert (c, s, t) == ("Transfer", "Investment Contribution", True)


def test_fees_are_isolated_so_they_can_be_surfaced():
    assert cat("ANNUAL MEMBERSHIP FEE")[:2] == ("Fees & Interest", "Annual Fee")
    assert cat("PURCHASE INTEREST CHARGE")[0] == "Fees & Interest"
    assert cat("FOREIGN TRANSACTION FEE")[:2] == ("Fees & Interest", "Foreign Transaction")
    assert cat("ATM FEE", account_type="depository")[:2] == ("Fees & Interest", "ATM")


def test_subscriptions_are_their_own_category():
    for desc in ["NETFLIX.COM", "SPOTIFY USA", "ADOBE CREATIVE CLOUD",
                 "ICLOUD STORAGE", "NYTIMES DIGITAL"]:
        assert cat(desc)[0] == "Subscriptions", desc


def test_provider_hint_used_when_no_keyword_matches():
    c, s, _ = cat("ZZZ OBSCURE VENDOR LLC", raw="groceries")
    assert (c, s) == ("Groceries", "Supermarket")


def test_unmatched_deposit_into_checking_is_income():
    assert cat("SOME UNKNOWN CREDIT", amount=2500.0, account_type="depository")[0] == "Income"


def test_unmatched_card_charge_stays_uncategorized():
    assert cat("ZZZ MYSTERY CHARGE", amount=-42.0, account_type="credit")[0] == "Uncategorized"


def test_payroll_is_income():
    assert cat("ACME CORP DIRECT DEP PPD", amount=6000.0,
               account_type="depository")[:2] == ("Income", "Salary")
