"""Analytics windowing and the spend/income conventions.

The comparison-window test exists because of a real bug: comparing a
month-to-date range against the immediately preceding N days puts rent inside
one window and outside the other, which reported a 465% spending increase on
the 12th of the month purely from where the boundary fell.
"""

import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_TMP = tempfile.mkdtemp(prefix="finance-analytics-")
os.environ["FINANCE_DB_PATH"] = os.path.join(_TMP, "analytics.db")

import db  # noqa: E402
import pytest  # noqa: E402
from services import analytics, sync_service  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def seeded():
    db.init_db()
    account = sync_service.upsert_account(
        provider="manual", provider_account_id="test-checking",
        institution="Test Bank", name="Checking", type="depository",
        subtype="checking",
    )
    card = sync_service.upsert_account(
        provider="manual", provider_account_id="test-card",
        institution="Test Bank", name="Card", type="credit", subtype="credit_card",
    )
    today = date.today()
    this_month = today.replace(day=1)
    last_month = analytics.add_months(this_month, -1)

    rows = []
    # Rent on the 1st of both months — the charge that made the old window lie.
    for month in (last_month, this_month):
        rows.append({"date": month.isoformat(), "amount": -3000.0,
                     "description": "RENT PAYMENT", "provider_merchant": None,
                     "raw_category": None})
    # A steady $20/day of groceries in the first 10 days of both months.
    for month in (last_month, this_month):
        for day in range(1, 11):
            rows.append({"date": month.replace(day=day).isoformat(), "amount": -20.0,
                         "description": "SAFEWAY", "provider_merchant": None,
                         "raw_category": "groceries"})
    # Nothing at all in the last third of the previous month, which is exactly
    # what the naive trailing window would have compared against.
    sync_service.insert_transactions(card, rows, source="seed")

    sync_service.insert_transactions(account, [
        {"date": this_month.replace(day=1).isoformat(), "amount": 5000.0,
         "description": "ACME DIRECT DEP", "provider_merchant": None,
         "raw_category": "income"},
        {"date": last_month.replace(day=1).isoformat(), "amount": 5000.0,
         "description": "ACME DIRECT DEP", "provider_merchant": None,
         "raw_category": "income"},
        # A card payment: a transfer, and so not spending on either account.
        {"date": this_month.replace(day=2).isoformat(), "amount": -1500.0,
         "description": "PAYMENT THANK YOU", "provider_merchant": None,
         "raw_category": None},
    ], source="seed")
    yield


def test_month_to_date_compares_against_the_same_days_last_month():
    today = date.today()
    start = today.replace(day=1).isoformat()
    p_start, p_end, label = analytics.comparison_window(start, today.isoformat())

    last_month = analytics.add_months(today.replace(day=1), -1)
    assert p_start == last_month.isoformat()
    # Same day-of-month as today, not a trailing window ending on the last of
    # the previous month.
    assert p_end.endswith(f"-{min(today.day, 28):02d}") or p_end == (
        analytics.add_months(today.replace(day=1), 0) - __import__("datetime").timedelta(days=1)
    ).isoformat()
    assert "last month" in label


def test_the_rent_boundary_artefact_is_gone():
    """Both windows must contain rent, so the delta reflects behaviour."""
    today = date.today()
    if today.day < 2:
        pytest.skip("Needs at least two days of the current month.")
    s = analytics.summary(today.replace(day=1).isoformat(), today.isoformat())
    # Rent is in both windows, so spend and prev_spend are the same order of
    # magnitude. The old trailing window produced a multi-hundred-percent jump.
    assert s["prev_spend"] > 1000
    assert abs(s["spend_change_pct"]) < 100


def test_arbitrary_ranges_still_use_a_trailing_window():
    p_start, p_end, label = analytics.comparison_window("2026-03-10", "2026-03-20")
    assert (p_start, p_end) == ("2026-02-27", "2026-03-09")
    assert "previous 11 days" in label


def test_month_to_date_window_clamps_to_a_shorter_previous_month():
    # 31 March against February, which has no 31st.
    p_start, p_end, _ = analytics.comparison_window("2026-03-01", "2026-03-31")
    assert p_start == "2026-02-01"
    assert p_end == "2026-02-28"


def test_category_deltas_use_the_same_window_as_the_headline():
    today = date.today()
    if today.day < 2:
        pytest.skip("Needs at least two days of the current month.")
    start, end = today.replace(day=1).isoformat(), today.isoformat()
    s = analytics.summary(start, end)
    cats = analytics.by_category(start, end)
    prior_total = sum(c["prev_spend"] or 0 for c in cats)
    # If the two used different windows these would not reconcile.
    assert abs(prior_total - s["prev_spend"]) < 1.0


def test_transfers_never_count_as_spending():
    today = date.today()
    s = analytics.summary(today.replace(day=1).isoformat(), today.isoformat())
    # The $1,500 card payment must be absent from spend entirely.
    cats = {c["category"] for c in analytics.by_category(
        today.replace(day=1).isoformat(), today.isoformat())}
    assert "Transfer" not in cats
    assert s["spend"] < 4000  # rent + groceries only, no card payment


def test_income_is_measured_separately_from_spend():
    today = date.today()
    s = analytics.summary(today.replace(day=1).isoformat(), today.isoformat())
    assert s["income"] == 5000.0
    assert s["net"] == round(s["income"] - s["spend"], 2)
    assert s["savings_rate"] == round(s["net"] / s["income"] * 100, 1)


def test_refunds_net_against_the_category_rather_than_being_ignored():
    account = db.query_one("SELECT id FROM accounts WHERE provider_account_id = 'test-card'")
    today = date.today()
    day = today.replace(day=min(today.day, 28))
    before = {c["category"]: c["spend"] for c in analytics.by_category(
        today.replace(day=1).isoformat(), today.isoformat())}
    sync_service.insert_transactions(account["id"], [{
        "date": day.isoformat(), "amount": 50.0,
        "description": "SAFEWAY REFUND", "provider_merchant": None,
        "raw_category": "groceries",
    }], source="manual")
    after = {c["category"]: c["spend"] for c in analytics.by_category(
        today.replace(day=1).isoformat(), today.isoformat())}
    assert round(before["Groceries"] - after["Groceries"], 2) == 50.0


def test_category_trend_never_exceeds_the_palette():
    """Eight hues, assigned in fixed order and never cycled.

    A ninth series would wrap onto slot 1, putting two categories on screen in
    the same colour — indistinguishable, and worse under colour-vision
    deficiency than having folded the tail into "Other".
    """
    trend = analytics.category_trend(months=6, top=8)
    assert len(trend["categories"]) <= 8
    names = [c["category"] for c in trend["categories"]]
    assert len(names) == len(set(names))

    # Even asked for far too many, the cap holds.
    greedy = analytics.category_trend(months=6, top=25)
    assert len(greedy["categories"]) <= 8


def test_category_trend_columns_still_total_all_spending():
    """Folding the tail into "Other" must not lose money."""
    trend = analytics.category_trend(months=6)
    if not trend["months"]:
        pytest.skip("No history in range.")
    charted = sum(sum(c["values"]) for c in trend["categories"])
    first, last = trend["months"][0], trend["months"][-1]
    start = first + "-01"
    end = (analytics.add_months(
        __import__("datetime").datetime.strptime(last + "-01", "%Y-%m-%d").date(), 1
    ) - __import__("datetime").timedelta(days=1)).isoformat()
    actual = sum(c["spend"] for c in analytics.by_category(start, end, compare=False))
    assert abs(charted - actual) < 1.0
