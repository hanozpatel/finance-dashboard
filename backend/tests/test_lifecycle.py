"""First-run seeding, clearing, and the empty-database state.

Every tab has to survive a database with nothing in it — that is what the app
looks like the moment someone clears the demo data and before their first sync
finishes. A division by zero in an insight generator would take out the page.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_TMP = tempfile.mkdtemp(prefix="finance-lifecycle-")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import db  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def isolated_database():
    """A genuinely empty file, whichever test module imported `db` first.

    FINANCE_DB_PATH is read once at import, so setting it here would be ignored
    when another module has already imported the store.
    """
    previous = db.DB_PATH
    db.use_database(os.path.join(_TMP, "lifecycle.db"))
    yield
    db.use_database(previous)


@pytest.fixture(scope="module")
def client(isolated_database):
    with TestClient(app) as c:
        yield c


def test_a_fresh_database_seeds_itself_once(client):
    health = client.get("/api/health").json()
    assert health["accounts"] == 4
    assert health["transactions"] > 1000
    assert health["is_demo"] is True


def test_clearing_leaves_an_empty_database(client):
    assert client.post("/api/demo/clear").status_code == 400  # needs confirmation
    assert client.post("/api/demo/clear?confirm=true").status_code == 200
    health = client.get("/api/health").json()
    assert health["accounts"] == 0
    assert health["transactions"] == 0
    assert health["is_demo"] is False


def test_a_restart_does_not_resurrect_cleared_data(isolated_database):
    """Re-seeding what someone just deleted would be maddening."""
    with TestClient(app) as c:
        health = c.get("/api/health").json()
        assert health["accounts"] == 0
        assert health["transactions"] == 0


@pytest.mark.parametrize("endpoint", [
    "/api/health",
    "/api/accounts",
    "/api/accounts/net-worth/trend",
    "/api/analytics/overview",
    "/api/analytics/spending",
    "/api/analytics/cash-flow",
    "/api/analytics/by-category",
    "/api/analytics/by-merchant",
    "/api/analytics/category-trend",
    "/api/transactions",
    "/api/transactions/categories",
    "/api/rules",
    "/api/budgets",
    "/api/recurring",
    "/api/insights",
    "/api/goals/house",
    "/api/investments",
    "/api/connections",
    "/api/connections/providers",
    "/api/imports/presets",
])
def test_every_endpoint_survives_an_empty_database(client, endpoint):
    r = client.get(endpoint)
    assert r.status_code == 200, f"{endpoint} -> {r.status_code}: {r.text[:200]}"


def test_empty_database_reports_zeroes_not_errors(client):
    overview = client.get("/api/analytics/overview").json()
    assert overview["net_worth"]["net_worth"] == 0
    assert overview["this_month"]["spend"] == 0
    # A savings rate cannot be computed without income, and must be null rather
    # than a fabricated zero.
    assert overview["this_month"]["savings_rate"] is None

    insights = client.get("/api/insights").json()
    assert insights["count"] == 0
    assert insights["monthly_total"] == 0

    house = client.get("/api/goals/house").json()
    # The plan still works off its defaults with no accounts linked.
    assert house["payment"]["total_monthly"] > 0
    assert house["goal"]["saved_amount"] == 0
    assert len(house["scenarios"]) == 6

    investments = client.get("/api/investments").json()
    assert investments["holdings"] == []
    assert investments["total_value"] == 0
    assert investments["total_gain"] is None


def test_mortgage_calculator_works_with_no_data_at_all(client):
    r = client.post("/api/goals/mortgage", json={"home_price": 400_000})
    assert r.status_code == 200
    assert r.json()["payment"]["loan_amount"] == 320_000


def test_reseeding_restores_the_demo_flag(client):
    assert client.post("/api/seed?confirm=true").status_code == 200
    health = client.get("/api/health").json()
    assert health["is_demo"] is True
    assert health["accounts"] == 4


def test_the_generated_encryption_key_survives_a_reseed(client):
    """Dropping it would make every stored provider token undecryptable."""
    before = db.get_setting("generated_master_key")
    client.post("/api/seed?confirm=true")
    assert db.get_setting("generated_master_key") == before
