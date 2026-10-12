"""What happens to a database that still has Teller connections in it.

Teller withdrew its API in July 2026. A database written before then holds live
enrollments pointing at a service that no longer answers, and the migration has
to retire them without taking the history down with them — losing months of real
transactions to a vendor's shutdown would be worse than a stale balance.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

import db  # noqa: E402


@pytest.fixture()
def legacy_database():
    """A database as it looked while Teller still worked.

    A fresh file per test: the connections table is unique on
    (provider, provider_ref), so a shared file would collide on the second
    insert rather than test anything.
    """
    previous = db.DB_PATH
    db.use_database(os.path.join(tempfile.mkdtemp(prefix="finance-teller-"), "legacy.db"))
    db.init_db()

    connection_id = db.execute(
        "INSERT INTO connections (provider, institution, provider_ref, access_token_enc)"
        " VALUES ('teller', 'Chase', 'enr_123', 'encrypted-token')"
    )
    account_id = db.execute(
        "INSERT INTO accounts (connection_id, provider, provider_account_id, institution,"
        " name, type, balance_current) VALUES (?, 'teller', 'acc_1', 'Chase',"
        " 'Sapphire Reserve', 'credit', -1840.00)",
        (connection_id,),
    )
    db.execute(
        "INSERT INTO transactions (account_id, provider_txn_id, date, amount, description)"
        " VALUES (?, 'txn_1', '2026-06-01', -42.50, 'PHILZ COFFEE')",
        (account_id,),
    )
    yield {"connection_id": connection_id, "account_id": account_id}
    db.use_database(previous)


def test_teller_connections_are_retired_on_startup(legacy_database):
    db.init_db()

    conn = db.query_one(
        "SELECT * FROM connections WHERE id = ?", (legacy_database["connection_id"],)
    )
    assert conn["status"] == "disconnected"
    # A dead credential is still a credential; it must not survive.
    assert conn["access_token_enc"] is None
    assert "Teller" in conn["error"]


def test_the_history_behind_them_is_kept(legacy_database):
    db.init_db()

    account = db.query_one("SELECT * FROM accounts WHERE id = ?", (legacy_database["account_id"],))
    assert account is not None
    # Handed back to manual entry, exactly as disconnecting any provider does.
    assert account["provider"] == "manual"
    assert account["connection_id"] is None
    assert account["balance_current"] == -1840.00

    txns = db.query("SELECT * FROM transactions WHERE account_id = ?",
                    (legacy_database["account_id"],))
    assert len(txns) == 1
    assert txns[0]["description"] == "PHILZ COFFEE"


def test_retiring_is_idempotent(legacy_database):
    db.init_db()
    db.init_db()

    rows = db.query("SELECT * FROM connections WHERE provider = 'teller'")
    assert len(rows) == 1
    assert rows[0]["status"] == "disconnected"


def test_plaid_connections_are_left_alone(legacy_database):
    plaid_id = db.execute(
        "INSERT INTO connections (provider, institution, provider_ref, products,"
        " access_token_enc) VALUES ('plaid', 'Chase', 'item_1', 'transactions', 'enc')"
    )
    db.init_db()

    row = db.query_one("SELECT * FROM connections WHERE id = ?", (plaid_id,))
    assert row["status"] == "active"
    assert row["access_token_enc"] == "enc"
