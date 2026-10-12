"""End-to-end API tests against a seeded database.

Each test runs against the demo dataset, which is deterministic, so these assert
real numbers rather than just status codes.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

# The database path is read at import time, so it has to be set before db loads.
_TMP = tempfile.mkdtemp(prefix="finance-test-")
os.environ["FINANCE_DB_PATH"] = os.path.join(_TMP, "test.db")

import db  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402
from services import seed  # noqa: E402


@pytest.fixture(scope="module")
def client():
    db.init_db()
    seed.reseed()
    with TestClient(app) as c:
        yield c


def test_health_reports_a_populated_database(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["accounts"] == 4
    assert body["transactions"] > 1000


def test_accounts_list_and_net_worth_agree(client):
    body = client.get("/api/accounts").json()
    assert len(body["accounts"]) == 4
    total = sum(a["balance_current"] for a in body["accounts"])
    assert abs(total - body["net_worth"]["net_worth"]) < 0.01
    # A credit card must be stored as a negative balance.
    card = next(a for a in body["accounts"] if a["type"] == "credit")
    assert card["balance_current"] <= 0


def test_overview_is_internally_consistent(client):
    body = client.get("/api/analytics/overview").json()
    assert body["net_worth"]["net_worth"] == (
        body["net_worth"]["assets"] - body["net_worth"]["liabilities"]
    )
    assert len(body["cash_flow"]) >= 12
    for month in body["cash_flow"]:
        assert abs(month["net"] - (month["income"] - month["spend"])) < 0.01


def test_spending_category_shares_sum_to_100(client):
    body = client.get("/api/analytics/spending?months=3").json()
    cats = body["by_category"]
    assert cats
    assert abs(sum(c["share"] for c in cats) - 100.0) < 0.5
    # Category totals must reconcile with the headline spend figure.
    assert abs(sum(c["spend"] for c in cats) - body["summary"]["spend"]) < 1.0


def test_transfers_are_excluded_from_spending(client):
    """Paying the card from checking must not register as spending."""
    spending = client.get("/api/analytics/spending?months=6").json()
    assert all(c["category"] != "Transfer" for c in spending["by_category"])

    with_transfers = client.get(
        "/api/transactions?include_transfers=true&limit=1000"
    ).json()
    without = client.get("/api/transactions?include_transfers=false&limit=1000").json()
    assert with_transfers["total_count"] > without["total_count"]


def test_transaction_filters(client):
    big = client.get("/api/transactions?min_amount=100&limit=50").json()
    assert all(abs(t["amount"]) >= 100 for t in big["transactions"])

    dining = client.get("/api/transactions?category=Dining&limit=50").json()
    assert dining["total_count"] > 0
    assert all(t["category"] == "Dining" for t in dining["transactions"])

    found = client.get("/api/transactions?search=NETFLIX&limit=50").json()
    assert found["total_count"] > 0
    assert all("NETFLIX" in t["description"].upper() for t in found["transactions"])


def test_transaction_pagination_does_not_repeat_rows(client):
    page1 = client.get("/api/transactions?limit=50&offset=0").json()
    page2 = client.get("/api/transactions?limit=50&offset=50").json()
    ids1 = {t["id"] for t in page1["transactions"]}
    ids2 = {t["id"] for t in page2["transactions"]}
    assert len(ids1) == 50 and len(ids2) == 50
    assert not (ids1 & ids2)


def test_recurring_detection_finds_the_seeded_subscriptions(client):
    body = client.get("/api/recurring?active_only=true").json()
    names = {s["display_name"].lower() for s in body["series"]}
    for expected in ("netflix", "spotify", "hbo max", "adobe creative cloud"):
        assert any(expected in n for n in names), f"{expected} not detected"
    assert body["monthly_total"] > 0
    assert all(s["cadence"] == "monthly" for s in body["series"])


def test_recurring_detects_the_seeded_price_increase(client):
    body = client.get("/api/recurring").json()
    netflix = next(s for s in body["series"] if "netflix" in s["display_name"].lower())
    # Seeded as 15.49 rising to 22.99.
    assert netflix["price_increase"] > 1.4
    assert netflix["amount_min"] == 15.49
    assert netflix["amount_max"] == 22.99


def test_insights_are_quantified_and_ranked(client):
    body = client.get("/api/insights").json()
    assert body["count"] > 0
    savings = [i["annual_savings"] for i in body["insights"]]
    assert savings == sorted(savings, reverse=True)
    for i in body["insights"]:
        assert i["monthly_savings"] > 0
        assert round(i["annual_savings"], 2) == round(i["monthly_savings"] * 12, 2)
        assert i["effort"] in ("easy", "moderate", "hard")
        assert i["basis"] and i["detail"]
    # The conservative figure must never exceed the ceiling.
    assert body["conservative_monthly"] <= body["monthly_total"] + 0.01
    assert body["easy_monthly_total"] <= body["monthly_total"] + 0.01


def test_insights_find_the_seeded_problems(client):
    ids = {i["id"] for i in client.get("/api/insights").json()["insights"]}
    # The seed deliberately contains all of these.
    assert "fees_interest" in ids            # late fees, interest, FX fees
    assert "idle_cash" in ids                # $14.8k in a 0.01% checking account
    assert "delivery_premium" in ids         # a DoorDash habit
    assert "subscription_audit" in ids       # 11 subscriptions
    assert any(i.startswith("overlap_") for i in ids)  # 4 streaming services
    assert "price_creep" in ids              # Netflix +48%


def test_house_plan_is_complete_and_consistent(client):
    body = client.get("/api/goals/house").json()
    payment, goal = body["payment"], body["goal"]

    assert payment["loan_amount"] == round(
        goal["target_price"] * (1 - goal["down_payment_pct"] / 100), 2)
    parts = (payment["principal_interest"] + payment["property_tax"]
             + payment["insurance"] + payment["hoa"] + payment["pmi"])
    assert abs(parts - payment["total_monthly"]) < 0.02

    assert body["cash_needed"]["total"] == round(
        body["cash_needed"]["down_payment"] + body["cash_needed"]["closing_costs"], 2)
    assert body["dti"]["back_end"] >= body["dti"]["front_end"]
    assert len(body["scenarios"]) == 6
    assert len(body["readiness"]["checks"]) == 4
    assert body["rent_vs_buy"]["yearly"]


def test_house_plan_savings_impact_shortens_the_timeline(client):
    body = client.get("/api/goals/house").json()
    impact = body["savings_impact"]
    assert impact["available"] is True
    assert impact["options"]
    for option in impact["options"]:
        # Contributing more must never take longer.
        assert option["months"] <= impact["base_months"]
        assert option["months_saved"] >= 0


def test_house_goal_update_round_trips(client):
    original = client.get("/api/goals/house").json()["goal"]["target_price"]
    updated = client.put("/api/goals/house", json={"target_price": 925_000}).json()
    assert updated["goal"]["target_price"] == 925_000
    assert updated["payment"]["loan_amount"] == round(925_000 * 0.8, 2)
    client.put("/api/goals/house", json={"target_price": original})


def test_house_goal_rejects_nonsense(client):
    assert client.put("/api/goals/house", json={"down_payment_pct": 150}).status_code == 422
    assert client.put("/api/goals/house", json={"interest_rate": -5}).status_code == 422
    assert client.put("/api/goals/house", json={"credit_score": 200}).status_code == 422


def test_mortgage_calculator_standalone(client):
    r = client.post("/api/goals/mortgage", json={
        "home_price": 500_000, "down_payment_pct": 20, "interest_rate": 6.5,
        "loan_term_years": 30, "property_tax_rate": 1.1, "insurance_annual": 1800,
        "gross_annual_income": 150_000, "monthly_debts": 400,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["payment"]["loan_amount"] == 400_000
    # $400k at 6.5%/30yr is $2,528.27.
    assert body["payment"]["principal_interest"] == 2528.27
    assert body["payment"]["pmi"] == 0.0
    assert "dti" in body and "affordability" in body
    assert len(body["yearly"]) == 30


def test_mortgage_calculator_extra_payments(client):
    body = client.post("/api/goals/mortgage", json={
        "home_price": 500_000, "down_payment_pct": 20, "interest_rate": 6.5,
        "extra_monthly": 500,
    }).json()
    effect = body["extra_payment_effect"]
    assert effect["months_saved"] > 0
    assert effect["interest_saved"] > 0
    assert effect["payoff_years"] < effect["baseline_payoff_years"]


def test_mortgage_calculator_charges_pmi_under_20_percent_down(client):
    body = client.post("/api/goals/mortgage", json={
        "home_price": 500_000, "down_payment_pct": 5, "interest_rate": 6.5,
        "pmi_rate": 0.6,
    }).json()
    assert body["payment"]["pmi"] > 0
    assert body["totals"]["pmi_ends_month"] is not None


def test_investments_allocation_sums_to_total(client):
    body = client.get("/api/investments").json()
    assert body["holdings"]
    assert abs(sum(h["value"] for h in body["holdings"]) - body["total_value"]) < 0.01
    assert abs(sum(a["value"] for a in body["allocation"]) - body["total_value"]) < 0.01
    assert abs(sum(h["weight"] for h in body["holdings"]) - 100) < 0.5


def test_budgets_and_category_rules(client):
    client.put("/api/budgets", json={"category": "Dining", "monthly_limit": 500})
    budgets = client.get("/api/budgets").json()["budgets"]
    dining = next(b for b in budgets if b["category"] == "Dining")
    assert dining["limit"] == 500
    assert dining["spent"] >= 0

    before = client.get("/api/transactions?search=ZEITGEIST&limit=10").json()
    assert before["total_count"] > 0
    assert before["transactions"][0]["category"] == "Uncategorized"

    rule = client.post("/api/rules", json={
        "match_type": "description_contains", "pattern": "ZEITGEIST",
        "category": "Dining", "subcategory": "Bars",
    })
    assert rule.status_code == 200
    assert rule.json()["transactions_recategorized"] > 0

    after = client.get("/api/transactions?search=ZEITGEIST&limit=10").json()
    assert after["transactions"][0]["category"] == "Dining"
    assert after["transactions"][0]["subcategory"] == "Bars"

    rule_id = rule.json()["rule"]["id"]
    assert client.delete(f"/api/rules/{rule_id}").status_code == 200
    reverted = client.get("/api/transactions?search=ZEITGEIST&limit=10").json()
    assert reverted["transactions"][0]["category"] == "Uncategorized"


def test_invalid_regex_rule_is_rejected(client):
    r = client.post("/api/rules", json={
        "match_type": "description_regex", "pattern": "[unclosed",
        "category": "Dining",
    })
    assert r.status_code == 400
    assert "regular expression" in r.json()["detail"]


def test_transaction_edit_and_exclusion(client):
    txn = client.get("/api/transactions?category=Dining&limit=1").json()["transactions"][0]
    r = client.patch(f"/api/transactions/{txn['id']}",
                     json={"excluded": True, "notes": "reimbursed by work"})
    assert r.status_code == 200
    assert r.json()["excluded"] == 1
    assert r.json()["notes"] == "reimbursed by work"
    client.patch(f"/api/transactions/{txn['id']}", json={"excluded": False})


def test_bulk_categorize_can_create_a_rule(client):
    rows = client.get("/api/transactions?search=PHILZ&limit=5").json()["transactions"]
    assert rows
    r = client.post("/api/transactions/bulk-categorize", json={
        "transaction_ids": [t["id"] for t in rows],
        "category": "Dining", "subcategory": "Coffee", "create_rule": True,
    })
    assert r.status_code == 200
    assert r.json()["updated"] == len(rows)
    assert r.json()["rule_created"]


@pytest.fixture()
def no_provider_credentials(monkeypatch):
    """Tests of the "not set up" path must not depend on the developer's .env.

    main.py calls load_dotenv() at import, so a machine with working Plaid keys
    would otherwise fail these assertions while a fresh checkout passed them.
    """
    for var in ("PLAID_CLIENT_ID", "PLAID_SECRET"):
        monkeypatch.delenv(var, raising=False)


def test_provider_status_explains_what_is_missing(client, no_provider_credentials):
    body = client.get("/api/connections/providers").json()
    assert "teller" not in body
    assert body["plaid"]["configured"] is False
    assert "PLAID_CLIENT_ID" in body["plaid"]["problem"]
    assert body["csv"]["configured"] is True
    # Apple's limitation must be stated, not implied.
    assert "aggregator" in body["csv"]["purpose"]

    # Both link kinds are offered, and each asks for only its own product.
    kinds = {k["kind"]: k for k in body["plaid"]["kinds"]}
    assert kinds["bank"]["products"] == ["transactions"]
    assert kinds["investments"]["products"] == ["investments"]


def test_linking_without_credentials_fails_with_a_useful_message(client, no_provider_credentials):
    for kind in ("bank", "investments"):
        r = client.post(f"/api/connections/plaid/link-token?kind={kind}")
        assert r.status_code == 400
        assert "PLAID_CLIENT_ID" in r.json()["detail"]


def test_unknown_link_kind_is_rejected(client):
    r = client.post("/api/connections/plaid/link-token?kind=crypto")
    assert r.status_code == 422


def test_csv_import_round_trip_for_apple_card(client):
    accounts = client.get("/api/accounts").json()["accounts"]
    apple = next(a for a in accounts if a["institution"] == "Apple")

    data = (
        b"Transaction Date,Clearing Date,Description,Merchant,Category,Type,Amount (USD),Purchased By\n"
        b"09/03/2026,09/04/2026,APPLE STORE,Apple Store,Shopping,Purchase,149.00,Alex\n"
        b"09/04/2026,09/05/2026,SOME LOCAL CAFE,Some Local Cafe,Restaurants,Purchase,18.25,Alex\n"
    )
    preview = client.post("/api/imports/preview",
                          files={"file": ("apple.csv", data, "text/csv")}).json()
    assert preview["detected_preset"] == "apple_card"
    assert preview["mapping"]["sign"] == "positive_is_spend"
    # The preview must show the parsed result so an inverted sign is catchable.
    assert preview["sample_parsed"][0]["amount"] == -149.00

    import json
    mapping = {**preview["mapping"], "header_row": preview["header_row"],
               "delimiter": preview["delimiter"]}
    r = client.post("/api/imports/commit", data={
        "account_id": apple["id"],
        "upload_token": preview["upload_token"],
        "mapping_json": json.dumps(mapping),
    })
    assert r.status_code == 200, r.text
    assert r.json()["inserted"] == 2

    imported = client.get(
        f"/api/transactions?account_id={apple['id']}&search=APPLE STORE").json()
    assert imported["transactions"][0]["amount"] == -149.00


def test_csv_reimport_is_idempotent(client):
    """Apple statements overlap month to month, so this must not duplicate."""
    accounts = client.get("/api/accounts").json()["accounts"]
    apple = next(a for a in accounts if a["institution"] == "Apple")
    data = (
        b"Transaction Date,Clearing Date,Description,Merchant,Category,Type,Amount (USD),Purchased By\n"
        b"09/03/2026,09/04/2026,REPEATED CHARGE,Repeated,Shopping,Purchase,77.00,Alex\n"
    )
    import json

    def send():
        preview = client.post("/api/imports/preview",
                              files={"file": ("a.csv", data, "text/csv")}).json()
        mapping = {**preview["mapping"], "header_row": preview["header_row"],
                   "delimiter": preview["delimiter"]}
        return client.post("/api/imports/commit", data={
            "account_id": apple["id"],
            "upload_token": preview["upload_token"],
            "mapping_json": json.dumps(mapping),
        }).json()

    first, second = send(), send()
    assert first["inserted"] == 1
    assert second["inserted"] == 0 and second["skipped"] == 1

    rows = client.get(f"/api/transactions?account_id={apple['id']}&search=REPEATED").json()
    assert rows["total_count"] == 1


def test_expired_upload_token_is_reported_not_crashed(client):
    import json
    account_id = client.get("/api/accounts").json()["accounts"][0]["id"]
    r = client.post("/api/imports/commit", data={
        "account_id": account_id, "upload_token": "deadbeef" * 4,
        "mapping_json": json.dumps({"date": "Date", "amount": "Amount"}),
    })
    assert r.status_code == 410


def test_upload_token_cannot_traverse_the_filesystem(client):
    """Rejected on the token alone, before the account is even looked up.

    The account id below does not exist; a 400 rather than a 404 is what proves
    the token check runs first.
    """
    import json
    for token in ("../../etc/passwd", "..%2F..%2Fetc", "a/b", "with space", "."):
        r = client.post("/api/imports/commit", data={
            "account_id": 999_999, "upload_token": token,
            "mapping_json": json.dumps({"date": "Date", "amount": "Amount"}),
        })
        assert r.status_code == 400, f"{token!r} was not rejected"
        assert "Invalid upload token" in r.json()["detail"]

    # An empty token never reaches the handler — FastAPI rejects the form first.
    empty = client.post("/api/imports/commit", data={
        "account_id": 999_999, "upload_token": "",
        "mapping_json": json.dumps({"date": "Date", "amount": "Amount"}),
    })
    assert empty.status_code in (400, 422)


def test_manual_account_creation_for_apple_savings(client):
    r = client.post("/api/accounts", json={
        "institution": "Apple", "name": "Apple Savings (manual)",
        "type": "depository", "subtype": "savings", "balance_current": 5000,
        "apy": 4.15,
    })
    assert r.status_code == 200
    created = r.json()
    assert created["balance_current"] == 5000
    assert created["apy"] == 4.15
    assert client.delete(f"/api/accounts/{created['id']}").status_code == 200


def test_seed_endpoint_refuses_without_confirmation(client):
    r = client.post("/api/seed")
    assert r.status_code == 400
    assert "confirm=true" in r.json()["detail"]
