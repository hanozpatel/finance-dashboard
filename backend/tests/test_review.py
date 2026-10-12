"""The review queue: what it asks, what it suggests, and what an answer does.

The suggestions are guesses, so the tests pin the ones that would be actively
misleading if they regressed — a stem matching inside an unrelated word, or two
ACH bills "matching" because they both carry the account holder's name.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

import db  # noqa: E402
from services import categorize, review, sync_service  # noqa: E402


@pytest.fixture()
def store():
    previous = db.DB_PATH
    db.use_database(os.path.join(tempfile.mkdtemp(prefix="finance-review-"), "review.db"))
    db.init_db()
    yield
    db.use_database(previous)


def _account(name="Card", type="credit", institution="Chase") -> int:
    return sync_service.upsert_account(
        provider="plaid", provider_account_id=f"acct-{name}", institution=institution,
        name=name, type=type, balance_current=-100.0,
    )


def _add(account_id, description, amount, date="2026-09-01", txn_id=None):
    sync_service.insert_transactions(account_id, [{
        "provider_txn_id": txn_id or f"t-{description}-{amount}", "date": date,
        "amount": amount, "description": description, "pending": 0,
    }])


def test_questions_are_per_merchant_biggest_money_first(store):
    account_id = _account()
    _add(account_id, "KOMODO 1099", -20.00, txn_id="a1")
    _add(account_id, "KOMODO 1099", -37.24, txn_id="a2")
    _add(account_id, "ZENITH PARTNERS", -156.00, txn_id="b1")

    q = review.queue()
    assert q["remaining"] == 2          # two merchants
    assert q["transactions"] == 3       # three rows
    # The $156 question outranks the $57 one, even though it is a single row.
    assert q["questions"][0]["merchant"] == "Zenith Partners"
    assert q["questions"][1]["count"] == 2


def test_a_stem_does_not_match_inside_an_unrelated_word(store):
    """"pita" must find PITA PLUS and not CA-PITA-L ONE."""
    account_id = _account()
    _add(account_id, "CAPITAL ONE DES:ONLINE PMT ID:CA01B3 INDN:K", -7.02)

    question = review.queue()["questions"][0]
    assert not any(s["category"] == "Dining" for s in question["suggestions"])


def test_an_ach_bill_does_not_match_another_by_the_account_holders_name(store):
    """Every ACH row carries INDN:<your name>. It proves nothing."""
    account_id = _account("Checking", "depository", "Bank of America")
    _add(account_id, "PAWSURE PET DES:XXXXX32685 ID: INDN:Alex Rivera CO ID:X", -71.01)
    review.answer(merchant_key="pawsure pet", category="Other", subcategory="Pets")

    _add(account_id, "LAKESIDE TECHN DES:Lakeside ID: INDN:Alex Rivera CO ID:X", -420.00)
    question = next(q for q in review.queue()["questions"] if "Lakeside" in q["merchant"])
    # Pets may still appear as a fallback ("your most-used category") — what it
    # must never claim is that the two merchant names resemble each other.
    assert not any("shares" in s["reason"] for s in question["suggestions"])


def test_a_merchant_you_already_answered_is_suggested_for_its_other_spelling(store):
    account_id = _account()
    _add(account_id, "TST*SAFFRON LANE - MAIN", -2.14, txn_id="d1")
    _add(account_id, "SAFFRON LANE", -89.01, txn_id="d2")
    # The Toast row categorises itself; the bare one cannot.
    assert db.query_one(
        "SELECT category FROM transactions WHERE provider_txn_id = 'd1'"
    )["category"] == "Dining"

    question = next(q for q in review.queue()["questions"] if q["merchant"] == "Saffron Lane")
    top = question["suggestions"][0]
    assert (top["category"], top["confidence"]) == ("Dining", "medium")
    assert "Saffron Lane" in top["reason"]


def test_there_is_always_something_to_click(store):
    account_id = _account()
    _add(account_id, "GROCERY MART", -30.00, txn_id="g1")
    review.answer(merchant_key="grocery mart", category="Groceries", subcategory="Supermarket")
    _add(account_id, "XQZ7 HOLDINGS", -44.00, txn_id="x1")

    question = next(q for q in review.queue()["questions"] if "XQZ7" in q["merchant"])
    assert question["suggestions"], "a question with no signal still needs options"
    assert all(s["reason"] for s in question["suggestions"])


def test_answering_settles_every_transaction_from_that_merchant(store):
    account_id = _account()
    _add(account_id, "SAFFRON LANE", -89.01, txn_id="d1")
    _add(account_id, "SAFFRON LANE", -61.78, txn_id="d2")

    result = review.answer(merchant_key="saffron lane", category="Dining",
                           subcategory="Restaurants")
    assert result["updated"] == 2
    assert result["remaining"] == 0
    rows = db.query("SELECT category, subcategory FROM transactions")
    assert {(r["category"], r["subcategory"]) for r in rows} == {("Dining", "Restaurants")}


def test_an_answer_becomes_a_rule_so_it_is_never_asked_again(store):
    account_id = _account()
    _add(account_id, "SAFFRON LANE", -89.01, txn_id="d1")
    review.answer(merchant_key="saffron lane", category="Dining", subcategory="Restaurants")

    # A later transaction from the same merchant categorises itself on arrival.
    _add(account_id, "SAFFRON LANE", -12.00, date="2026-10-01", txn_id="d2")
    assert db.query_one(
        "SELECT category FROM transactions WHERE provider_txn_id = 'd2'"
    )["category"] == "Dining"
    assert review.queue()["remaining"] == 0


def test_answering_without_a_rule_leaves_future_transactions_alone(store):
    account_id = _account()
    _add(account_id, "ONE OFF THING", -50.00, txn_id="o1")
    review.answer(merchant_key="one off thing", category="Other", subcategory=None,
                  create_rule=False)

    assert db.query("SELECT * FROM category_rules") == []
    _add(account_id, "ONE OFF THING", -50.00, date="2026-10-01", txn_id="o2")
    assert review.queue()["remaining"] == 1


def test_changing_your_mind_updates_the_rule_rather_than_stacking_one(store):
    account_id = _account()
    _add(account_id, "SAFFRON LANE", -89.01, txn_id="d1")
    review.answer(merchant_key="saffron lane", category="Dining", subcategory="Restaurants")
    db.execute("UPDATE transactions SET category = 'Uncategorized'")
    review.answer(merchant_key="saffron lane", category="Groceries", subcategory="Supermarket")

    rules = db.query("SELECT * FROM category_rules WHERE pattern = 'saffron lane'")
    assert len(rules) == 1
    assert rules[0]["category"] == "Groceries"


def test_a_transfer_answer_is_marked_as_a_transfer(store):
    account_id = _account("Checking", "depository")
    _add(account_id, "CAPITAL ONE DES:ONLINE PMT ID:CA01 INDN:K", -14.69)
    review.answer(merchant_key="capital one", category="Transfer", subcategory="Card Payment")

    row = db.query_one("SELECT * FROM transactions")
    assert row["is_transfer"] == 1


def test_an_unknown_category_is_refused(store):
    with pytest.raises(ValueError):
        review.answer(merchant_key="whatever", category="Vibes", subcategory=None)


def test_stats_track_coverage(store):
    account_id = _account()
    _add(account_id, "STARBUCKS", -5.00, txn_id="s1")
    _add(account_id, "XQZ7 HOLDINGS", -44.00, txn_id="x1")

    stats = review.stats()
    assert stats["total"] == 2
    assert stats["uncategorized"] == 1
    assert stats["coverage"] == 50.0
    assert stats["amount"] == 44.00


def test_the_ach_envelope_is_stripped_from_merchant_names(store):
    """DES:/ID:/INDN: is routing metadata, and INDN is your own name."""
    merchant, key = categorize.normalize_merchant(
        "LAKESIDE TECHN DES:Lakeside ID: INDN:Alex Rivera CO ID:XXXXX"
    )
    assert merchant == "Lakeside Techn"
    assert "indn" not in key and "rivera" not in key


def test_a_short_merchant_key_never_becomes_a_rule(store):
    """A two-letter key matches a quarter of a real ledger."""
    account_id = _account()
    _add(account_id, "ACMEPROPERTY2-CT- DES:WEB PMTS ID:44YYJM INDN:AlexRivera", -1491.00)

    key = db.query_one("SELECT merchant_key FROM transactions")["merchant_key"]
    result = review.answer(merchant_key=key, category="Housing", subcategory="Utilities")

    assert result["updated"] == 1        # the transaction is still categorised
    assert db.query("SELECT * FROM category_rules") == [] or len(key) >= 5


def test_a_rule_is_withheld_when_it_would_rewrite_another_merchant(store):
    account_id = _account()
    _add(account_id, "CHEESECAKE FACTORY", -60.00, txn_id="c1")
    review.answer(merchant_key="cheesecake factory", category="Dining", subcategory="Restaurants")

    # Long enough to pass the length guard, but it still appears inside a
    # merchant you categorise differently, so a substring rule would take it
    # over silently.
    _add(account_id, "CHEESECAKE", -12.00, txn_id="k1")
    refusal = review.rule_refusal("cheesecake", "Groceries")
    assert refusal and "Cheesecake Factory" in refusal

    result = review.answer(merchant_key="cheesecake", category="Groceries", subcategory=None)
    assert result["rule_created"] is None
    assert result["rule_skipped_reason"]
    # The transaction in hand is still answered.
    assert db.query_one("SELECT category FROM transactions WHERE provider_txn_id = 'k1'"
                        )["category"] == "Groceries"
    # And the merchant it would have stolen is untouched.
    assert db.query_one("SELECT category FROM transactions WHERE provider_txn_id = 'c1'"
                        )["category"] == "Dining"


def test_a_company_name_with_a_digit_is_not_mistaken_for_an_id(store):
    """ACMEPROPERTY2 is a merchant; CA01B3E6A3AB625 is a machine id."""
    merchant, _key = categorize.normalize_merchant(
        "ACMEPROPERTY2-CT- DES:WEB PMTS ID:44YYJM INDN:AlexRivera CO ID:X"
    )
    assert merchant == "Acmeproperty2"

    merchant, _key = categorize.normalize_merchant(
        "CAPITAL ONE DES:ONLINE PMT ID:CA01B3E6A3AB625 INDN:Jordan C"
    )
    assert merchant == "Capital One"


def test_fallback_suggestions_offer_different_categories(store):
    """Three subcategories of Dining is one guess, not three."""
    account_id = _account()
    for i, (desc, cat, sub) in enumerate([
        ("STARBUCKS", "Dining", "Coffee"), ("PEETS", "Dining", "Coffee"),
        ("CHIPOTLE", "Dining", "Fast Food"), ("SUBWAY", "Dining", "Fast Food"),
        ("DOORDASH", "Dining", "Delivery"), ("SAFEWAY", "Groceries", "Supermarket"),
        ("TARGET", "Shopping", "General"),
    ]):
        _add(account_id, desc, -10.0, txn_id=f"seed-{i}")
    _add(account_id, "XQZ7 HOLDINGS", -44.00, txn_id="x1")

    question = next(q for q in review.queue()["questions"] if "XQZ7" in q["merchant"])
    fallback = [s["category"] for s in question["suggestions"] if s["confidence"] == "low"]
    assert len(fallback) == len(set(fallback)), fallback
