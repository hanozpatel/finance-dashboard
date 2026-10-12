"""Write provider data into the canonical tables.

This is the only place that knows about more than one provider, and the only
place that writes transactions. Everything it stores is already normalised to
the app's conventions (see db.py), so no query downstream needs a provider
branch.

Re-running a sync must be safe and idempotent, because it happens every time the
dashboard loads. Provider feeds give stable ids, so those dedupe naturally; CSV
rows do not, and get a deterministic synthetic id instead — see ``_csv_txn_id``.
"""

from __future__ import annotations

import hashlib
from datetime import date

import db
from services import categorize, crypto_service, plaid_service, recurring, snaptrade_service


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------

def upsert_account(
    *,
    provider: str,
    provider_account_id: str,
    institution: str,
    name: str,
    type: str,
    subtype: str | None = None,
    mask: str | None = None,
    currency: str = "USD",
    connection_id: int | None = None,
    balance_current: float | None = None,
    balance_available: float | None = None,
    credit_limit: float | None = None,
    apy: float | None = None,
) -> int:
    existing = db.query_one(
        "SELECT id FROM accounts WHERE provider = ? AND provider_account_id = ?",
        (provider, provider_account_id),
    )
    if existing:
        sets = ["institution = ?", "name = ?", "type = ?", "subtype = ?", "mask = ?",
                "currency = ?", "last_synced = datetime('now')"]
        params: list = [institution, name, type, subtype, mask, currency]
        # Balances are only written when the provider actually reported one, so
        # a partial sync cannot zero out a known balance.
        for column, value in (("balance_current", balance_current),
                              ("balance_available", balance_available),
                              ("credit_limit", credit_limit),
                              ("apy", apy),
                              ("connection_id", connection_id)):
            if value is not None:
                sets.append(f"{column} = ?")
                params.append(value)
        params.append(existing["id"])
        db.execute(f"UPDATE accounts SET {', '.join(sets)} WHERE id = ?", tuple(params))
        return existing["id"]

    return db.execute(
        """
        INSERT INTO accounts (connection_id, provider, provider_account_id, institution,
                              name, mask, type, subtype, currency, balance_current,
                              balance_available, credit_limit, apy, last_synced)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (connection_id, provider, provider_account_id, institution, name, mask, type,
         subtype, currency, balance_current or 0.0, balance_available, credit_limit,
         apy),
    )


def snapshot_balances(on: str | None = None) -> int:
    """Record today's balance for every account, for the net-worth trend.

    Upserts on (account_id, date) so syncing five times a day leaves one point
    per day rather than five.
    """
    on = on or date.today().isoformat()
    rows = db.query("SELECT id, balance_current FROM accounts WHERE is_active = 1")
    with db.tx() as conn:
        for r in rows:
            conn.execute(
                "INSERT INTO balance_snapshots (account_id, date, balance) VALUES (?, ?, ?) "
                "ON CONFLICT(account_id, date) DO UPDATE SET balance = excluded.balance",
                (r["id"], on, r["balance_current"]),
            )
    return len(rows)


# --------------------------------------------------------------------------
# Transactions
# --------------------------------------------------------------------------

def _csv_txn_id(account_id: int, row: dict, occurrence: int) -> str:
    """Deterministic id for a CSV row, so re-importing cannot duplicate.

    Apple exports overlap month to month, so the same charge arrives repeatedly
    and must collapse. The occurrence counter keeps *genuinely* repeated charges
    — two identical coffees on one day — as separate rows, which a plain content
    hash would silently merge into one.
    """
    basis = f"{account_id}|{row['date']}|{row['amount']:.2f}|{row['description'].strip().upper()}|{occurrence}"
    return "csv:" + hashlib.sha1(basis.encode()).hexdigest()[:24]


def insert_transactions(
    account_id: int, txns: list[dict], *, source: str = "sync",
    update_existing: bool = False,
) -> dict:
    """Insert transactions, categorising each. Returns counts.

    Existing rows are left alone rather than updated, with two exceptions: a
    transaction that was pending and has now posted gets its amount and date
    refreshed, because pending amounts are estimates; and rows Plaid reports as
    *modified* are refreshed too, via ``update_existing``.

    Either way only the provider's own fields move. Category, notes, and the
    excluded flag are yours, and a bank restating an amount must not silently
    undo a categorisation you made.
    """
    if not txns:
        return {"inserted": 0, "updated": 0, "skipped": 0}

    account = db.query_one("SELECT type FROM accounts WHERE id = ?", (account_id,))
    if not account:
        raise ValueError(f"Account {account_id} does not exist.")
    account_type = account["type"]
    rules = db.query("SELECT * FROM category_rules ORDER BY priority ASC, id ASC")

    inserted = updated = skipped = 0
    seen_basis: dict[str, int] = {}

    with db.tx() as conn:
        for t in txns:
            txn_id = t.get("provider_txn_id")
            if not txn_id:
                basis = f"{t['date']}|{t['amount']:.2f}|{t['description'].strip().upper()}"
                occurrence = seen_basis.get(basis, 0)
                seen_basis[basis] = occurrence + 1
                txn_id = _csv_txn_id(account_id, t, occurrence)

            existing = conn.execute(
                "SELECT id, pending FROM transactions WHERE account_id = ? AND provider_txn_id = ?",
                (account_id, txn_id),
            ).fetchone()

            if existing:
                posted = existing["pending"] and not t.get("pending")
                if posted or update_existing:
                    conn.execute(
                        "UPDATE transactions SET amount = ?, date = ?, pending = ? WHERE id = ?",
                        (t["amount"], t["date"], int(t.get("pending", 0)), existing["id"]),
                    )
                    updated += 1
                else:
                    skipped += 1
                continue

            merchant, merchant_key = categorize.normalize_merchant(
                t["description"], t.get("provider_merchant")
            )
            category, subcategory, is_transfer = categorize.categorize(
                description=t["description"],
                merchant=merchant,
                merchant_key=merchant_key,
                raw_category=t.get("raw_category"),
                amount=t["amount"],
                account_type=account_type,
                rules=rules,
            )
            conn.execute(
                """
                INSERT INTO transactions
                    (account_id, provider_txn_id, date, amount, description, merchant,
                     merchant_key, raw_category, category, subcategory, is_transfer,
                     pending, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (account_id, txn_id, t["date"], t["amount"], t["description"], merchant,
                 merchant_key, t.get("raw_category"), category, subcategory,
                 int(is_transfer), int(t.get("pending", 0)), source),
            )
            inserted += 1

    return {"inserted": inserted, "updated": updated, "skipped": skipped}


# --------------------------------------------------------------------------
# Per-provider sync
# --------------------------------------------------------------------------

def _connection_token(conn_row: dict) -> str:
    if not conn_row.get("access_token_enc"):
        raise RuntimeError("This connection has no stored access token; re-link it.")
    return crypto_service.decrypt(conn_row["access_token_enc"])


def _mark(connection_id: int, *, error: str | None) -> None:
    db.execute(
        "UPDATE connections SET status = ?, error = ?, last_synced = datetime('now') "
        "WHERE id = ?",
        ("error" if error else "active", error, connection_id),
    )


def delete_transactions(account_ids: list[int], provider_txn_ids: list[str]) -> int:
    """Remove transactions the bank has retracted.

    Plaid reports these on the next sync after an institution reverses a
    transaction that never really happened. Leaving them behind would quietly
    overstate a month's spending forever.
    """
    if not account_ids or not provider_txn_ids:
        return 0
    removed = 0
    with db.tx() as conn:
        accounts = ",".join("?" * len(account_ids))
        for chunk_start in range(0, len(provider_txn_ids), 400):
            chunk = provider_txn_ids[chunk_start:chunk_start + 400]
            ids = ",".join("?" * len(chunk))
            cur = conn.execute(
                f"DELETE FROM transactions WHERE account_id IN ({accounts}) "
                f"AND provider_txn_id IN ({ids})",
                tuple(account_ids) + tuple(chunk),
            )
            removed += cur.rowcount or 0
    return removed


def _connection_products(conn_row: dict) -> list[str]:
    """What this Item was linked for.

    Connections created before bank links existed have no products recorded and
    are all brokerages, so they default to investments.
    """
    raw = (conn_row.get("products") or "").strip()
    if not raw:
        return ["investments"]
    return [p.strip() for p in raw.split(",") if p.strip()]


def _sync_plaid_transactions(
    connection_id: int, cursor: str | None, token: str, id_map: dict[str, int]
) -> dict:
    """Apply one ``/transactions/sync`` run and advance the stored cursor.

    The cursor is written *after* the rows land. If writing throws, the cursor
    stays where it was and the next sync replays the same batch — duplicate
    inserts are already impossible, so a replay is free, while a lost batch
    would be a silent hole in the history.
    """
    changes = plaid_service.sync_transactions(token, cursor)
    counts = {"inserted": 0, "updated": 0, "skipped": 0, "removed": 0}

    for batch, update_existing in ((changes["added"], False), (changes["modified"], True)):
        by_account: dict[str, list[dict]] = {}
        for t in batch:
            by_account.setdefault(t.get("provider_account_id"), []).append(t)
        for provider_account_id, txns in by_account.items():
            account_id = id_map.get(provider_account_id)
            if not account_id:
                continue
            result = insert_transactions(
                account_id, txns, source="sync", update_existing=update_existing
            )
            for k in ("inserted", "updated", "skipped"):
                counts[k] += result[k]

    counts["removed"] = delete_transactions(list(id_map.values()), changes["removed"])
    db.execute(
        "UPDATE connections SET sync_cursor = ? WHERE id = ?",
        (changes["cursor"], connection_id),
    )
    return counts


def sync_plaid(connection_id: int) -> dict:
    """Pull everything this Item is allowed to give us.

    A bank Item answers transactions, a brokerage Item answers holdings, and the
    products recorded at link time decide which is asked for — calling the wrong
    endpoint on an Item is an error from Plaid, not an empty result.
    """
    conn_row = db.query_one("SELECT * FROM connections WHERE id = ?", (connection_id,))
    if not conn_row:
        raise ValueError(f"Connection {connection_id} not found.")
    try:
        token = _connection_token(conn_row)
        products = _connection_products(conn_row)
        accounts = plaid_service.list_accounts(token, conn_row["institution"])
        id_map: dict[str, int] = {}
        for a in accounts:
            account_id = upsert_account(
                provider="plaid",
                provider_account_id=a["provider_account_id"],
                institution=a["institution"],
                name=a["name"],
                type=a["type"],
                subtype=a["subtype"],
                mask=a["mask"],
                currency=a["currency"],
                connection_id=connection_id,
                balance_current=a["balance_current"],
                balance_available=a.get("balance_available"),
                credit_limit=a.get("credit_limit"),
            )
            id_map[a["provider_account_id"]] = account_id

        result = {"accounts": len(accounts), "inserted": 0, "updated": 0,
                  "skipped": 0, "removed": 0, "holdings": 0}

        if "transactions" in products:
            try:
                result.update(
                    _sync_plaid_transactions(
                        connection_id, conn_row["sync_cursor"], token, id_map
                    )
                )
            except plaid_service.PlaidNotReady as e:
                # Not a failure: the accounts and balances landed, and Plaid is
                # still assembling the history. The connection stays healthy so
                # the next sync picks up where this one stopped.
                result["note"] = str(e)

        if "investments" in products:
            result["holdings"] = replace_holdings(plaid_service.get_holdings(token), id_map)

        _mark(connection_id, error=None)
        return result
    except Exception as e:
        _mark(connection_id, error=f"{type(e).__name__}: {e}")
        raise


def sync_snaptrade(connection_id: int) -> dict:
    """Pull one brokerage connection's accounts and positions.

    SnapTrade's identity is per user rather than per connection, so unlike
    Plaid there is no token on the row to decrypt — the connection only records
    *which* brokerage authorisation this is, and the accounts are filtered to it.
    """
    conn_row = db.query_one("SELECT * FROM connections WHERE id = ?", (connection_id,))
    if not conn_row:
        raise ValueError(f"Connection {connection_id} not found.")
    try:
        accounts = [
            a for a in snaptrade_service.list_accounts(conn_row["institution"])
            if not conn_row["provider_ref"] or a["authorization_id"] == conn_row["provider_ref"]
        ]
        id_map: dict[str, int] = {}
        for a in accounts:
            account_id = upsert_account(
                provider="snaptrade",
                provider_account_id=a["provider_account_id"],
                institution=a["institution"],
                name=a["name"],
                type=a["type"],
                subtype=a["subtype"],
                mask=a["mask"],
                currency=a["currency"],
                connection_id=connection_id,
                balance_current=a["balance_current"],
            )
            id_map[a["provider_account_id"]] = account_id

        holdings: list[dict] = []
        for provider_account_id in id_map:
            holdings.extend(snaptrade_service.get_positions(provider_account_id))
        stored = replace_holdings(holdings, id_map)

        _mark(connection_id, error=None)
        return {"accounts": len(accounts), "holdings": stored}
    except Exception as e:
        _mark(connection_id, error=f"{type(e).__name__}: {e}")
        raise


def replace_holdings(holdings: list[dict], id_map: dict[str, int]) -> int:
    """Replace the holdings for the accounts named in ``id_map``.

    Holdings are a snapshot, not a ledger: a position that was sold must
    disappear, so this deletes and rewrites rather than upserting. Only the
    accounts in this sync are touched, so a failed Plaid sync cannot wipe out a
    different brokerage's positions.
    """
    if not id_map:
        return 0
    today = date.today().isoformat()
    with db.tx() as conn:
        placeholders = ",".join("?" * len(id_map))
        conn.execute(
            f"DELETE FROM holdings WHERE account_id IN ({placeholders})",
            tuple(id_map.values()),
        )
        count = 0
        for h in holdings:
            account_id = id_map.get(h.get("provider_account_id"))
            if not account_id:
                continue
            conn.execute(
                """
                INSERT INTO holdings (account_id, symbol, name, security_type, quantity,
                                      price, value, cost_basis, as_of)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, symbol, name) DO UPDATE SET
                    quantity = excluded.quantity, price = excluded.price,
                    value = excluded.value, cost_basis = excluded.cost_basis,
                    as_of = excluded.as_of
                """,
                (account_id, h.get("symbol"), h["name"], h.get("security_type"),
                 h["quantity"], h["price"], h["value"], h.get("cost_basis"), today),
            )
            count += 1
    return count


def sync_all() -> dict:
    """Sync every active connection, then rebuild derived data.

    One failing connection must not stop the others, so failures are collected
    and reported rather than raised.
    """
    results: list[dict] = []
    for c in db.query("SELECT * FROM connections WHERE status != 'disconnected'"):
        entry = {"connection_id": c["id"], "provider": c["provider"],
                 "institution": c["institution"]}
        try:
            if c["provider"] == "plaid":
                entry["result"] = sync_plaid(c["id"])
            elif c["provider"] == "snaptrade":
                entry["result"] = sync_snaptrade(c["id"])
            else:
                entry["skipped"] = f"no sync for provider '{c['provider']}'"
            entry["ok"] = True
        except Exception as e:
            entry["ok"] = False
            entry["error"] = f"{type(e).__name__}: {e}"
        results.append(entry)

    snapshot_balances()
    derived = recurring.refresh()
    return {
        "connections": results,
        "failed": [r for r in results if not r.get("ok")],
        "recurring": derived,
        "synced_at": date.today().isoformat(),
    }
