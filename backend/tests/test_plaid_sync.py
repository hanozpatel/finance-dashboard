"""The Plaid sync pipeline, from provider payload to stored rows.

``plaid_service`` is stubbed here rather than reached over the network: what is
under test is what ``sync_service`` *does* with a response — the signs it stores,
the cursor it advances, and its handling of the corrections Plaid sends after
the fact.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

import db  # noqa: E402
from services import crypto_service, plaid_service, sync_service  # noqa: E402


@pytest.fixture()
def store():
    previous = db.DB_PATH
    db.use_database(os.path.join(tempfile.mkdtemp(prefix="finance-plaidsync-"), "sync.db"))
    db.init_db()
    yield
    db.use_database(previous)


def _connection(products: str, institution: str = "Chase") -> int:
    return db.execute(
        "INSERT INTO connections (provider, institution, provider_ref, products,"
        " access_token_enc) VALUES ('plaid', ?, ?, ?, ?)",
        (institution, f"item_{products}", products, crypto_service.encrypt("access-token")),
    )


BANK_ACCOUNTS = [
    {"provider_account_id": "card_1", "institution": "Chase", "name": "Sapphire",
     "mask": "4242", "type": "credit", "subtype": "credit card", "currency": "USD",
     "balance_current": -1840.00, "balance_available": 8160.00, "credit_limit": 10000.00},
    {"provider_account_id": "chk_1", "institution": "Chase", "name": "Checking",
     "mask": "1111", "type": "depository", "subtype": "checking", "currency": "USD",
     "balance_current": 5400.25, "balance_available": 5400.25, "credit_limit": None},
]


def _txn(txn_id, account, amount, date="2026-09-01", name="PHILZ COFFEE", pending=0):
    return {"provider_txn_id": txn_id, "provider_account_id": account, "amount": amount,
            "date": date, "description": name, "provider_merchant": None,
            "raw_category": None, "pending": pending}


def test_a_bank_sync_stores_signed_balances_and_transactions(store, monkeypatch):
    connection_id = _connection("transactions")
    monkeypatch.setattr(plaid_service, "list_accounts", lambda *a, **k: BANK_ACCOUNTS)
    monkeypatch.setattr(plaid_service, "sync_transactions", lambda *a, **k: {
        "added": [_txn("t1", "card_1", -42.50), _txn("t2", "chk_1", 2400.00, name="PAYROLL")],
        "modified": [], "removed": [], "cursor": "cursor-1",
    })

    result = sync_service.sync_plaid(connection_id)
    assert result["accounts"] == 2
    assert result["inserted"] == 2

    card = db.query_one("SELECT * FROM accounts WHERE provider_account_id = 'card_1'")
    assert card["balance_current"] == -1840.00
    assert card["credit_limit"] == 10000.00

    spend = db.query_one("SELECT * FROM transactions WHERE provider_txn_id = 't1'")
    assert spend["amount"] == -42.50

    # The cursor has to persist, or every sync would replay the whole history.
    conn_row = db.query_one("SELECT * FROM connections WHERE id = ?", (connection_id,))
    assert conn_row["sync_cursor"] == "cursor-1"
    assert conn_row["status"] == "active"


def test_the_next_sync_starts_from_the_stored_cursor(store, monkeypatch):
    connection_id = _connection("transactions")
    monkeypatch.setattr(plaid_service, "list_accounts", lambda *a, **k: BANK_ACCOUNTS)
    monkeypatch.setattr(plaid_service, "sync_transactions", lambda *a, **k: {
        "added": [_txn("t1", "card_1", -42.50)], "modified": [], "removed": [],
        "cursor": "cursor-1",
    })
    sync_service.sync_plaid(connection_id)

    seen = {}

    def second_call(token, cursor=None):
        seen["cursor"] = cursor
        return {"added": [], "modified": [], "removed": [], "cursor": "cursor-2"}

    monkeypatch.setattr(plaid_service, "sync_transactions", second_call)
    sync_service.sync_plaid(connection_id)
    assert seen["cursor"] == "cursor-1"


def test_corrections_and_reversals_are_applied(store, monkeypatch):
    connection_id = _connection("transactions")
    monkeypatch.setattr(plaid_service, "list_accounts", lambda *a, **k: BANK_ACCOUNTS)
    monkeypatch.setattr(plaid_service, "sync_transactions", lambda *a, **k: {
        "added": [_txn("t1", "card_1", -42.50), _txn("t2", "card_1", -19.00, name="LUNCH")],
        "modified": [], "removed": [], "cursor": "c1",
    })
    sync_service.sync_plaid(connection_id)

    # The bank restates one amount and retracts the other entirely.
    monkeypatch.setattr(plaid_service, "sync_transactions", lambda *a, **k: {
        "added": [], "modified": [_txn("t1", "card_1", -45.00)], "removed": ["t2"],
        "cursor": "c2",
    })
    result = sync_service.sync_plaid(connection_id)

    assert result["updated"] == 1
    assert result["removed"] == 1
    assert db.query_one("SELECT * FROM transactions WHERE provider_txn_id = 't1'")["amount"] == -45.00
    assert db.query_one("SELECT * FROM transactions WHERE provider_txn_id = 't2'") is None


def test_a_correction_does_not_undo_your_categorisation(store, monkeypatch):
    connection_id = _connection("transactions")
    monkeypatch.setattr(plaid_service, "list_accounts", lambda *a, **k: BANK_ACCOUNTS)
    monkeypatch.setattr(plaid_service, "sync_transactions", lambda *a, **k: {
        "added": [_txn("t1", "card_1", -42.50)], "modified": [], "removed": [], "cursor": "c1",
    })
    sync_service.sync_plaid(connection_id)
    db.execute(
        "UPDATE transactions SET category = 'Travel', notes = 'work trip' "
        "WHERE provider_txn_id = 't1'"
    )

    monkeypatch.setattr(plaid_service, "sync_transactions", lambda *a, **k: {
        "added": [], "modified": [_txn("t1", "card_1", -45.00)], "removed": [], "cursor": "c2",
    })
    sync_service.sync_plaid(connection_id)

    row = db.query_one("SELECT * FROM transactions WHERE provider_txn_id = 't1'")
    assert row["amount"] == -45.00
    assert row["category"] == "Travel"
    assert row["notes"] == "work trip"


def test_a_brokerage_item_is_never_asked_for_transactions(store, monkeypatch):
    connection_id = _connection("investments", institution="Robinhood")
    monkeypatch.setattr(plaid_service, "list_accounts", lambda *a, **k: [
        {"provider_account_id": "inv_1", "institution": "Robinhood", "name": "Individual",
         "mask": "9999", "type": "investment", "subtype": "brokerage", "currency": "USD",
         "balance_current": 18250.10, "balance_available": None, "credit_limit": None},
    ])
    monkeypatch.setattr(plaid_service, "get_holdings", lambda *a, **k: [
        {"provider_account_id": "inv_1", "symbol": "VTI", "name": "Vanguard Total Market",
         "security_type": "etf", "quantity": 40.0, "price": 300.0, "value": 12000.0,
         "cost_basis": 9000.0},
    ])

    def must_not_be_called(*a, **k):
        raise AssertionError("an investments Item cannot answer /transactions/sync")

    monkeypatch.setattr(plaid_service, "sync_transactions", must_not_be_called)

    result = sync_service.sync_plaid(connection_id)
    assert result["holdings"] == 1
    assert result["inserted"] == 0
    assert db.query_one("SELECT * FROM holdings WHERE symbol = 'VTI'")["quantity"] == 40.0


def test_history_still_loading_is_not_a_failed_connection(store, monkeypatch):
    connection_id = _connection("transactions")
    monkeypatch.setattr(plaid_service, "list_accounts", lambda *a, **k: BANK_ACCOUNTS)

    def not_ready(*a, **k):
        raise plaid_service.PlaidNotReady("Plaid is still fetching this institution's history.")

    monkeypatch.setattr(plaid_service, "sync_transactions", not_ready)
    result = sync_service.sync_plaid(connection_id)

    # Balances landed, the connection is healthy, and the user is told why the
    # transactions are not there yet.
    assert result["accounts"] == 2
    assert "still fetching" in result["note"]
    conn_row = db.query_one("SELECT * FROM connections WHERE id = ?", (connection_id,))
    assert conn_row["status"] == "active"
    assert conn_row["sync_cursor"] is None


def test_a_real_failure_marks_the_connection(store, monkeypatch):
    connection_id = _connection("transactions")
    monkeypatch.setattr(plaid_service, "list_accounts", lambda *a, **k: BANK_ACCOUNTS)

    def broken(*a, **k):
        raise plaid_service.PlaidError("ITEM_LOGIN_REQUIRED")

    monkeypatch.setattr(plaid_service, "sync_transactions", broken)
    with pytest.raises(plaid_service.PlaidError):
        sync_service.sync_plaid(connection_id)

    conn_row = db.query_one("SELECT * FROM connections WHERE id = ?", (connection_id,))
    assert conn_row["status"] == "error"
    assert "ITEM_LOGIN_REQUIRED" in conn_row["error"]


def test_connections_linked_before_bank_support_still_sync(store, monkeypatch):
    """Rows with no products recorded predate bank links and are all brokerages."""
    connection_id = db.execute(
        "INSERT INTO connections (provider, institution, provider_ref, access_token_enc)"
        " VALUES ('plaid', 'Robinhood', 'item_old', ?)",
        (crypto_service.encrypt("access-token"),),
    )
    monkeypatch.setattr(plaid_service, "list_accounts", lambda *a, **k: [])
    monkeypatch.setattr(plaid_service, "get_holdings", lambda *a, **k: [])
    monkeypatch.setattr(plaid_service, "sync_transactions", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("legacy items must not be asked for transactions")))

    assert sync_service.sync_plaid(connection_id)["accounts"] == 0
