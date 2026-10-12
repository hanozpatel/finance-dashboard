"""Manual accounts — the Apple Savings path.

Apple permits no aggregator, so this is not a convenience feature: it is the
only way that money appears in net worth at all. It has to behave like a real
account, not a sticky note.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_TMP = tempfile.mkdtemp(prefix="finance-manual-")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import db  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def isolated_database():
    previous = db.DB_PATH
    db.use_database(os.path.join(_TMP, "manual.db"))
    # Mark the database as already initialised so startup does not seed demo
    # data into it — these tests are about a genuinely empty starting point.
    db.init_db()
    db.set_setting("initialized", "1")
    yield
    db.use_database(previous)


@pytest.fixture(scope="module")
def client(isolated_database):
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def apple(client):
    r = client.post("/api/accounts", json={
        "institution": "Apple",
        "name": "Apple Savings",
        "type": "depository",
        "subtype": "savings",
        "account_number": "123456789012",
        "balance_current": 42_000,
        "apy": 4.15,
        "notes": "Goldman Sachs; statements are PDF only",
    })
    assert r.status_code == 200, r.text
    return r.json()


def test_account_number_is_stored_and_masked(apple):
    assert apple["account_number"] == "123456789012"
    # The listing shows only the last four.
    assert apple["mask"] == "9012"
    assert apple["apy"] == 4.15
    assert apple["notes"].startswith("Goldman Sachs")


def test_a_manual_balance_counts_toward_net_worth(client, apple):
    body = client.get("/api/accounts").json()
    assert body["net_worth"]["net_worth"] == 42_000
    assert body["net_worth"]["cash"] == 42_000


def test_recording_interest_moves_the_balance_too(client, apple):
    before = client.get("/api/accounts").json()["net_worth"]["net_worth"]
    r = client.post("/api/transactions", json={
        "account_id": apple["id"],
        "date": "2026-09-01",
        "amount": 214.55,
        "description": "INTEREST PAID",
        "category": "Income",
        "subcategory": "Interest",
        "update_balance": True,
    })
    assert r.status_code == 200, r.text
    assert r.json()["inserted"] == 1
    assert r.json()["balance_updated"] is True
    assert r.json()["balance"] == round(before + 214.55, 2)

    after = client.get("/api/accounts").json()["net_worth"]["net_worth"]
    assert after == round(before + 214.55, 2)


def test_a_transaction_can_be_recorded_without_moving_the_balance(client, apple):
    before = client.get("/api/accounts").json()["net_worth"]["net_worth"]
    r = client.post("/api/transactions", json={
        "account_id": apple["id"],
        "date": "2026-08-01",
        "amount": 198.20,
        "description": "INTEREST PAID AUGUST",
        "update_balance": False,
    })
    assert r.json()["balance_updated"] is False
    after = client.get("/api/accounts").json()["net_worth"]["net_worth"]
    assert after == before


def test_a_manual_credit_balance_is_stored_as_a_liability(client):
    r = client.post("/api/accounts", json={
        "institution": "Some Bank", "name": "Store Card", "type": "credit",
        # Entered as what is owed, positive, which is how people think of it.
        "balance_current": 1_500,
    })
    assert r.json()["balance_current"] == -1_500


def test_manual_apy_feeds_the_house_down_payment_projection(client, apple):
    """A manual account is a first-class funding source, not a footnote."""
    plan = client.put("/api/goals/house", json={
        "funding_account_ids": [apple["id"]],
        "target_price": 500_000,
        "down_payment_pct": 20,
    }).json()
    assert plan["goal"]["saved_from_accounts"] is True
    # Reads the live balance rather than a figure typed into the goal.
    balance = client.get("/api/accounts").json()["accounts"]
    apple_now = next(a for a in balance if a["id"] == apple["id"])
    assert plan["goal"]["saved_amount"] == apple_now["balance_current"]


def test_seeding_is_a_full_reset_and_says_so(client):
    """Unlike clearing, seeding is destructive by design — but it must warn."""
    r = client.post("/api/seed")
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "full reset" in detail
    assert "you created or linked yourself" in detail
    assert "/api/demo/clear" in detail


def test_clearing_demo_data_keeps_accounts_you_made_yourself(client):
    """The bug this guards, in the order it actually happened:

    demo data is present, you add your real Apple Savings account, then you
    click "clear demo data" — and your real account must still be there.
    """
    client.post("/api/seed?confirm=true")
    assert len(client.get("/api/accounts").json()["accounts"]) == 4

    mine = client.post("/api/accounts", json={
        "institution": "Apple", "name": "My Apple Savings", "type": "depository",
        "subtype": "savings", "balance_current": 31_000, "apy": 4.15,
    }).json()
    client.post("/api/transactions", json={
        "account_id": mine["id"], "date": "2026-09-01", "amount": 107.40,
        "description": "INTEREST PAID", "update_balance": True,
    })
    assert len(client.get("/api/accounts").json()["accounts"]) == 5

    result = client.post("/api/demo/clear?confirm=true").json()
    assert result["accounts_removed"] == 4
    assert result["transactions_removed"] > 1000
    assert "My Apple Savings" in result["accounts_kept"]

    remaining = client.get("/api/accounts").json()["accounts"]
    names = {a["name"] for a in remaining}
    assert names == {"My Apple Savings"}
    assert "Sapphire Reserve" not in names

    # The account keeps its balance, its interest transaction, and its APY.
    survivor = remaining[0]
    assert survivor["balance_current"] == 31_107.40
    assert survivor["apy"] == 4.15
    rows = client.get(f"/api/transactions?account_id={survivor['id']}"
                      "&include_transfers=true").json()
    assert rows["total_count"] == 1


def test_seeded_budgets_do_not_outlive_the_demo_data(client):
    """Otherwise they generate over-budget findings against real spending."""
    assert client.get("/api/budgets").json()["budgets"] == []
