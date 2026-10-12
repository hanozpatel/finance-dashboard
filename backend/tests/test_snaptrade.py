"""SnapTrade: the shapes it returns, and what this app stores from them.

The API is stubbed — what matters here is the translation. Two conversions are
easy to get backwards and would be invisible until a portfolio total looked
wrong: the cost basis is quoted per share, and the security sits at a different
nesting depth depending on the endpoint.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

import db  # noqa: E402
from services import crypto_service, snaptrade_service, sync_service  # noqa: E402


@pytest.fixture()
def store():
    previous = db.DB_PATH
    db.use_database(os.path.join(tempfile.mkdtemp(prefix="finance-snaptrade-"), "st.db"))
    db.init_db()
    yield
    db.use_database(previous)


def test_cost_basis_is_converted_from_per_share_to_per_position(store, monkeypatch):
    monkeypatch.setattr(snaptrade_service, "_user_kwargs", dict)

    class FakePositions:
        body = [{
            "symbol": {"symbol": {"symbol": "VTI", "description": "Vanguard Total Market",
                                  "type": {"code": "etf"}}},
            "units": 40, "price": 300.0, "average_purchase_price": 225.0,
        }]

    monkeypatch.setattr(snaptrade_service, "_client", lambda: type("C", (), {
        "account_information": type("A", (), {
            "get_all_account_positions": staticmethod(lambda **kw: FakePositions())
        })()
    })())

    position = snaptrade_service.get_positions("acct-1")[0]
    assert position["symbol"] == "VTI"
    assert position["security_type"] == "etf"
    assert position["quantity"] == 40
    assert position["value"] == 12000.00
    # 225 per share over 40 shares, not 225 for the lot.
    assert position["cost_basis"] == 9000.00


def test_a_flatter_symbol_shape_is_read_the_same_way(store, monkeypatch):
    """Some endpoints nest the universal symbol one level less."""
    assert snaptrade_service._symbol_of({"symbol": {"symbol": "AAPL"}}) == {"symbol": "AAPL"}
    assert snaptrade_service._symbol_of(
        {"symbol": {"symbol": {"symbol": "AAPL", "description": "Apple"}}}
    ) == {"symbol": "AAPL", "description": "Apple"}
    assert snaptrade_service._symbol_of({}) == {}


def test_a_personal_key_signs_calls_as_itself_with_no_user(store, monkeypatch):
    """The bug this guards: a personal key has no user to register.

    Passing a user id and secret alongside one selects the commercial security
    scheme, and SnapTrade answers 403 "Authentication credentials were not
    provided" — which reads like bad credentials rather than a wrong flow.
    """
    monkeypatch.setenv("SNAPTRADE_CLIENT_ID", "PERS-ABC123")
    monkeypatch.setenv("SNAPTRADE_CONSUMER_KEY", "consumer")
    monkeypatch.delenv("SNAPTRADE_MODE", raising=False)

    assert snaptrade_service.auth_mode() == snaptrade_service.PERSONAL
    assert snaptrade_service._user_kwargs() == {}
    # Ready the moment the key is set: there is no registration step.
    assert snaptrade_service.is_ready() is True
    with pytest.raises(snaptrade_service.SnapTradeError):
        snaptrade_service.ensure_user()


def test_a_commercial_key_registers_a_user(store, monkeypatch):
    monkeypatch.setenv("SNAPTRADE_CLIENT_ID", "FINANCE-DASHBOARD")
    monkeypatch.setenv("SNAPTRADE_CONSUMER_KEY", "consumer")
    monkeypatch.delenv("SNAPTRADE_MODE", raising=False)

    assert snaptrade_service.auth_mode() == snaptrade_service.COMMERCIAL
    # Nothing registered yet, so it is not usable until something registers it.
    assert snaptrade_service.is_ready() is False


def test_the_mode_can_be_forced_when_the_prefix_lies(store, monkeypatch):
    monkeypatch.setenv("SNAPTRADE_CLIENT_ID", "PERS-ABC123")
    monkeypatch.setenv("SNAPTRADE_MODE", "commercial")
    assert snaptrade_service.auth_mode() == snaptrade_service.COMMERCIAL


def test_the_user_secret_is_registered_once_and_stored_encrypted(store, monkeypatch):
    monkeypatch.setenv("SNAPTRADE_MODE", "commercial")
    calls = []

    class FakeRegister:
        body = {"userId": "finance-dashboard-local", "userSecret": "secret-abc"}

    def fake_client():
        calls.append(1)
        return type("C", (), {"authentication": type("A", (), {
            "register_snap_trade_user": staticmethod(lambda **kw: FakeRegister())
        })()})()

    monkeypatch.setattr(snaptrade_service, "_client", fake_client)

    user_id, secret = snaptrade_service.ensure_user()
    assert (user_id, secret) == ("finance-dashboard-local", "secret-abc")

    # Second call reuses the stored identity: re-registering would issue a new
    # secret and orphan every brokerage connection made under the old one.
    assert snaptrade_service.ensure_user() == ("finance-dashboard-local", "secret-abc")
    assert len(calls) == 1

    stored = db.get_setting("snaptrade_user_secret_enc")
    assert stored and "secret-abc" not in stored
    assert crypto_service.decrypt(stored) == "secret-abc"


def test_sync_stores_accounts_and_positions(store, monkeypatch):
    connection_id = db.execute(
        "INSERT INTO connections (provider, institution, provider_ref, products)"
        " VALUES ('snaptrade', 'Robinhood', 'auth-1', 'investments')"
    )
    monkeypatch.setattr(snaptrade_service, "list_accounts", lambda institution=None: [
        {"provider_account_id": "acct-1", "authorization_id": "auth-1",
         "institution": "Robinhood", "name": "Individual", "mask": "9999",
         "type": "investment", "subtype": "brokerage", "currency": "USD",
         "balance_current": 18250.10, "balance_available": None, "credit_limit": None},
        # A second brokerage on the same SnapTrade user must not be adopted by
        # this connection.
        {"provider_account_id": "acct-2", "authorization_id": "auth-2",
         "institution": "Other", "name": "Other", "mask": "1111",
         "type": "investment", "subtype": "brokerage", "currency": "USD",
         "balance_current": 100.0, "balance_available": None, "credit_limit": None},
    ])
    monkeypatch.setattr(snaptrade_service, "get_positions", lambda account_id: [
        {"provider_account_id": account_id, "symbol": "VTI", "name": "Vanguard",
         "security_type": "etf", "quantity": 40.0, "price": 300.0, "value": 12000.0,
         "cost_basis": 9000.0},
    ])

    result = sync_service.sync_snaptrade(connection_id)
    assert result == {"accounts": 1, "holdings": 1}

    account = db.query_one("SELECT * FROM accounts WHERE provider_account_id = 'acct-1'")
    assert account["type"] == "investment"
    assert account["balance_current"] == 18250.10
    assert db.query_one("SELECT * FROM accounts WHERE provider_account_id = 'acct-2'") is None

    holding = db.query_one("SELECT * FROM holdings")
    assert (holding["symbol"], holding["quantity"], holding["cost_basis"]) == ("VTI", 40.0, 9000.0)


def test_a_failed_sync_marks_the_connection(store, monkeypatch):
    connection_id = db.execute(
        "INSERT INTO connections (provider, institution, provider_ref, products)"
        " VALUES ('snaptrade', 'Robinhood', 'auth-1', 'investments')"
    )

    def broken(institution=None):
        raise snaptrade_service.SnapTradeError("connection disabled by the brokerage")

    monkeypatch.setattr(snaptrade_service, "list_accounts", broken)
    with pytest.raises(snaptrade_service.SnapTradeError):
        sync_service.sync_snaptrade(connection_id)

    row = db.query_one("SELECT * FROM connections WHERE id = ?", (connection_id,))
    assert row["status"] == "error"
    assert "disabled" in row["error"]


def test_sdk_types_are_converted_to_plain_python(store):
    """Responses arrive as frozendict and Decimal lookalikes."""
    import decimal
    converted = snaptrade_service._plain(
        {"units": decimal.Decimal("40.5"), "nested": [{"ok": True, "none": None}]}
    )
    assert converted == {"units": 40.5, "nested": [{"ok": True, "none": None}]}
    assert isinstance(converted["units"], float)
