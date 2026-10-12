"""Budgets against state averages.

The numbers here are only worth showing if three things hold: the bundled BEA
data is complete and internally consistent, the household scaling is applied
exactly once, and a half-finished month is compared on its pace rather than its
spend so far. Each of those is pinned below.
"""

import json
import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

import db  # noqa: E402
from services import benchmarks, budgeting, sync_service  # noqa: E402
from services.analytics import add_months  # noqa: E402

DATA = json.loads(
    (benchmarks._DATA_FILE).read_text()
)


@pytest.fixture()
def store():
    previous = db.DB_PATH
    db.use_database(os.path.join(tempfile.mkdtemp(prefix="finance-budget-"), "b.db"))
    db.init_db()
    yield
    db.use_database(previous)


def _account():
    return sync_service.upsert_account(
        provider="manual", provider_account_id="card", institution="Bank",
        name="Card", type="credit", balance_current=0.0,
    )


def _spend(account_id, when: date, amount: float, description: str, category: str):
    sync_service.insert_transactions(account_id, [{
        "provider_txn_id": f"{when}-{description}-{amount}", "date": when.isoformat(),
        "amount": -abs(amount), "description": description, "pending": 0,
    }])
    db.execute("UPDATE transactions SET category = ? WHERE description = ?",
               (category, description))


# --------------------------------------------------------------------------
# The bundled data
# --------------------------------------------------------------------------

def test_every_state_dc_and_the_nation_are_present():
    assert len(DATA["areas"]) == 52
    assert {"US", "DC", "CA", "SC", "WY"} <= set(DATA["areas"])


def test_every_area_has_every_comparable_category():
    expected = set(DATA["lines"])
    for code, area in DATA["areas"].items():
        assert set(area["annual_per_person"]) == expected, code
        assert all(v > 0 for v in area["annual_per_person"].values()), code


def test_the_national_population_is_plausible():
    """The build derives population; a wrong derivation shows up here first."""
    assert 320_000_000 < DATA["areas"]["US"]["population"] < 360_000_000


def test_health_is_explained_rather_than_compared():
    assert "Health" not in DATA["lines"]
    assert "insurers" in DATA["not_comparable"]["Health"]


def test_the_source_is_recorded():
    assert "Bureau of Economic Analysis" in DATA["source"]
    assert DATA["year"] >= 2024


# --------------------------------------------------------------------------
# Settings and scaling
# --------------------------------------------------------------------------

def test_the_default_is_the_national_figure_until_you_choose(store):
    s = benchmarks.settings()
    assert (s["state"], s["household_size"], s["state_chosen"]) == ("US", 1, False)


def test_choosing_a_state_and_household_is_remembered(store):
    benchmarks.save_settings(state="sc", household_size=2)
    s = benchmarks.settings()
    assert (s["state"], s["household_size"], s["state_chosen"]) == ("SC", 2, True)
    assert s["state_name"] == "South Carolina"


def test_an_unknown_state_is_refused(store):
    with pytest.raises(ValueError):
        benchmarks.save_settings(state="ZZ")
    with pytest.raises(ValueError):
        benchmarks.save_settings(household_size=0)


def test_monthly_figures_scale_by_household_exactly_once(store):
    one = benchmarks.monthly("SC", 1)
    three = benchmarks.monthly("SC", 3)
    annual = DATA["areas"]["SC"]["annual_per_person"]["Groceries"]
    assert one["Groceries"] == round(annual / 12, 2)
    assert three["Groceries"] == pytest.approx(one["Groceries"] * 3, abs=0.02)


# --------------------------------------------------------------------------
# The month view
# --------------------------------------------------------------------------

def test_a_finished_month_is_compared_on_what_was_spent(store):
    benchmarks.save_settings(state="US", household_size=1)
    account_id = _account()
    last_month = add_months(date.today().replace(day=1), -1)
    _spend(account_id, last_month.replace(day=5), 300.00, "GROCER A", "Groceries")
    _spend(account_id, last_month.replace(day=20), 72.00, "GROCER B", "Groceries")

    view = budgeting.overview(last_month.strftime("%Y-%m"))
    groceries = next(r for r in view["categories"] if r["category"] == "Groceries")
    assert groceries["spent"] == 372.00
    assert groceries["projected"] is None
    state = groceries["state"]
    assert groceries["vs_state_pct"] == round((372.00 / state - 1) * 100, 1)


def test_with_no_history_the_running_month_falls_back_to_straight_pace(store):
    """Day 10 of 30 with $100 spent and nothing to compare is a $300 month."""
    account_id = _account()
    today = date.today()
    _spend(account_id, today, 100.00, "GROCER", "Groceries")

    view = budgeting.overview()
    groceries = next(r for r in view["categories"] if r["category"] == "Groceries")
    assert view["is_current"]
    expected = round(100.00 / view["elapsed_days"] * view["days_in_month"], 2)
    assert groceries["projected"] == expected
    assert groceries["vs_state_pct"] == round((expected / groceries["state"] - 1) * 100, 1)


def test_with_history_the_projection_is_spent_plus_your_typical_rate(store):
    """One big early grocery run must not extrapolate to an absurd month.

    The bug this replaced: $820 by day 12 projected to $2,119 against a typical
    $918, and the page reported the household at +470% of the state average.
    """
    account_id = _account()
    this_month = date.today().replace(day=1)
    for back in range(1, 12):
        _spend(account_id, add_months(this_month, -back).replace(day=10), 900.00,
               f"GROCER {back}", "Groceries")
    _spend(account_id, date.today(), 820.00, "BIG RUN", "Groceries")

    view = budgeting.overview()
    groceries = next(r for r in view["categories"] if r["category"] == "Groceries")
    remaining = view["days_in_month"] - view["elapsed_days"]
    assert groceries["typical"] == 900.00
    assert groceries["projected"] == round(820.00 + 900.00 * remaining / view["days_in_month"], 2)
    # Never below what has already been spent.
    assert groceries["projected"] >= 820.00


def test_a_month_that_nets_to_a_credit_is_shown_but_not_compared(store):
    account_id = _account()
    last_month = add_months(date.today().replace(day=1), -1)
    _spend(account_id, last_month.replace(day=2), 200.00, "UTILITY", "Housing")
    # A reimbursement larger than the spend: money came *in* under Housing.
    sync_service.insert_transactions(account_id, [{
        "provider_txn_id": "refund", "date": last_month.replace(day=9).isoformat(),
        "amount": 700.00, "description": "ROOMMATE SHARE", "pending": 0,
    }])
    db.execute("UPDATE transactions SET category = 'Housing' WHERE provider_txn_id = 'refund'")

    housing = next(r for r in budgeting.overview(last_month.strftime("%Y-%m"))["categories"]
                   if r["category"] == "Housing")
    assert housing["spent"] == -500.00
    assert housing["net_credit"] is True
    assert housing["vs_state_pct"] is None


def test_transfers_and_income_are_not_budget_lines(store):
    account_id = _account()
    _spend(account_id, date.today(), 500.00, "CARD PAYMENT", "Transfer")
    names = {r["category"] for r in budgeting.overview()["categories"]}
    assert "Transfer" not in names and "Income" not in names


def test_a_category_without_a_state_figure_says_why(store):
    account_id = _account()
    _spend(account_id, date.today(), 40.00, "PHARMACY", "Health")
    health = next(r for r in budgeting.overview()["categories"] if r["category"] == "Health")
    assert health["comparable"] is False
    assert health["state"] is None and health["vs_state_pct"] is None
    assert "insurers" in health["not_comparable_reason"]


def test_your_typical_month_ignores_the_unfinished_one(store):
    account_id = _account()
    this_month = date.today().replace(day=1)
    _spend(account_id, add_months(this_month, -1).replace(day=3), 400.00, "A", "Dining")
    _spend(account_id, add_months(this_month, -2).replace(day=3), 200.00, "B", "Dining")
    _spend(account_id, date.today(), 5000.00, "C", "Dining")

    dining = next(r for r in budgeting.overview()["categories"] if r["category"] == "Dining")
    # Eleven complete months in the window, two with spending.
    assert dining["typical"] == round(600.00 / 11, 2)


def test_comparable_categories_come_first(store):
    rows = budgeting.overview()["categories"]
    seen_incomparable = False
    for r in rows:
        if not r["comparable"]:
            seen_incomparable = True
        else:
            assert not seen_incomparable, "a comparable row came after an incomparable one"


def test_history_covers_twelve_months_ending_on_the_selected_one(store):
    view = budgeting.overview("2026-03")
    assert view["months"][0] == "2025-04"
    assert view["months"][-1] == "2026-03"
    assert all(len(r["history"]) == 12 for r in view["categories"])


# --------------------------------------------------------------------------
# Filling budgets
# --------------------------------------------------------------------------

def test_filling_never_overwrites_a_budget_you_set(store):
    benchmarks.save_settings(state="US", household_size=2)
    db.execute("INSERT INTO budgets (category, monthly_limit) VALUES ('Groceries', 999)")

    result = budgeting.fill_from_state()
    assert "Groceries" in result["skipped"]
    budgets = {r["category"]: r["monthly_limit"] for r in db.query("SELECT * FROM budgets")}
    assert budgets["Groceries"] == 999


def test_filled_budgets_are_rounded_and_household_scaled(store):
    benchmarks.save_settings(state="US", household_size=2)
    budgeting.fill_from_state()
    budgets = {r["category"]: r["monthly_limit"] for r in db.query("SELECT * FROM budgets")}
    expected = round(benchmarks.monthly("US", 2)["Dining"] / 10) * 10
    assert budgets["Dining"] == expected
    assert all(v % 10 == 0 for v in budgets.values())


# --------------------------------------------------------------------------
# The demo's residence must not follow a real user
# --------------------------------------------------------------------------

def test_the_demo_persona_lives_in_california(store):
    from services import seed
    seed.reseed()
    s = benchmarks.settings()
    assert (s["state"], s["household_size"]) == ("CA", 1)


def test_clearing_the_demo_also_clears_its_state(store):
    from fastapi.testclient import TestClient
    from main import app
    from services import seed
    seed.reseed()
    with TestClient(app) as client:
        assert client.post("/api/demo/clear?confirm=true").status_code == 200
    s = benchmarks.settings()
    assert (s["state"], s["state_chosen"]) == ("US", False)


def test_a_state_you_chose_survives_clearing_the_demo(store):
    from fastapi.testclient import TestClient
    from main import app
    from services import seed
    seed.reseed()
    benchmarks.save_settings(state="TX")
    with TestClient(app) as client:
        client.post("/api/demo/clear?confirm=true")
    assert benchmarks.settings()["state"] == "TX"


def test_the_demo_has_something_to_review(store):
    from services import review, seed
    seed.reseed()
    stats = review.stats()
    assert 3 <= stats["questions"] <= 10


def test_a_category_you_never_spend_in_is_not_a_row(store):
    """No education spending should not mean a permanent 'Education: -100%'."""
    account_id = _account()
    _spend(account_id, date.today(), 50.00, "GROCER", "Groceries")
    names = {r["category"] for r in budgeting.overview()["categories"]}
    assert "Groceries" in names
    assert "Education" not in names


def test_a_budget_alone_earns_a_row(store):
    db.execute("INSERT INTO budgets (category, monthly_limit) VALUES ('Education', 100)")
    names = {r["category"] for r in budgeting.overview()["categories"]}
    assert "Education" in names
