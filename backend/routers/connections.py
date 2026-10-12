"""Linking and syncing provider connections.

Everything live goes through Plaid, in two steps: the server creates a link
token naming the products it wants, the browser runs Plaid Link against it, and
the short-lived public token that comes back is exchanged here for the long-lived
access token that gets encrypted and stored.

Linking is per *kind* — a bank link and a brokerage link request different
products and produce separate Items even at the same institution — because an
Item's products cannot be widened after it exists.

SnapTrade is the second provider, and it is here for one reason: brokerages
Plaid cannot reach. Its flow is shaped differently — the login happens on
SnapTrade's own page and nothing is handed back to us — so linking is two
calls, one for the URL and one to adopt whatever came of it.
"""

from fastapi import APIRouter, HTTPException, Query

import db
from models.schemas import PlaidExchange
from services import crypto_service, plaid_service, snaptrade_service, sync_service

router = APIRouter(prefix="/api/connections", tags=["connections"])


@router.get("")
def list_connections():
    return {
        "connections": db.query(
            "SELECT c.id, c.provider, c.institution, c.provider_ref, c.status, c.error,"
            "       c.last_synced, c.created_at,"
            "       (SELECT COUNT(*) FROM accounts a WHERE a.connection_id = c.id) AS account_count"
            " FROM connections c ORDER BY c.created_at DESC"
        ),
        "providers": provider_status(),
    }


@router.get("/providers")
def provider_status():
    """What each provider can do right now, and why not if it cannot.

    Surfacing the *reason* matters: "PLAID_SECRET is not set" is actionable,
    while a disabled button is not.
    """
    return {
        "plaid": {
            "label": "Plaid",
            "purpose": "Banks and credit cards",
            "configured": plaid_service.is_configured(),
            "problem": plaid_service.configuration_problem(),
            "environment": plaid_service.config()["env"],
            "kinds": [
                {"kind": kind, "label": spec["label"], "purpose": spec["purpose"],
                 "products": spec["products"]}
                for kind, spec in plaid_service.LINK_KINDS.items()
            ],
        },
        "snaptrade": {
            "label": "SnapTrade",
            "purpose": "Brokerages, including Robinhood, which Plaid often cannot reach",
            "configured": snaptrade_service.is_configured(),
            "problem": snaptrade_service.configuration_problem(),
            "mode": snaptrade_service.auth_mode() if snaptrade_service.is_configured() else None,
            "registered": snaptrade_service.is_ready(),
        },
        "csv": {
            "label": "CSV import",
            "purpose": "Accounts no aggregator can reach, such as Apple Card and Apple Savings",
            "configured": True,
            "problem": None,
        },
        "encryption": {
            "key_from_environment": not crypto_service.key_is_ephemeral(),
            "warning": (
                None if not crypto_service.key_is_ephemeral() else
                "FINANCE_MASTER_KEY is not set, so the key encrypting your provider "
                "tokens is stored in the database itself. Anyone who copies the "
                "database file can decrypt them. Set it in backend/.env."
            ),
        },
    }


@router.post("/plaid/link-token")
def plaid_link_token(kind: str = Query("bank", pattern="^(bank|investments)$")):
    """A link token scoped to one kind of institution.

    ``bank`` asks for transactions, ``investments`` asks for holdings. Consent
    stays as narrow as the account being linked actually needs.
    """
    problem = plaid_service.configuration_problem()
    if problem:
        raise HTTPException(400, problem)
    try:
        return {"link_token": plaid_service.create_link_token(kind), "kind": kind}
    except plaid_service.PlaidError as e:
        raise HTTPException(502, str(e)) from e


@router.post("/plaid")
def connect_plaid(body: PlaidExchange):
    problem = plaid_service.configuration_problem()
    if problem:
        raise HTTPException(400, problem)
    try:
        exchanged = plaid_service.exchange_public_token(body.public_token)
    except plaid_service.PlaidError as e:
        raise HTTPException(502, str(e)) from e

    institution = body.institution or "Unknown institution"
    products = ",".join(plaid_service.LINK_KINDS[body.kind]["products"])
    encrypted = crypto_service.encrypt(exchanged["access_token"])
    existing = db.query_one(
        "SELECT id FROM connections WHERE provider = 'plaid' AND provider_ref = ?",
        (exchanged["item_id"],),
    )
    if existing:
        connection_id = existing["id"]
        # Re-linking an Item resets its cursor: the new token may reach further
        # back than the old one did, and replaying costs nothing.
        db.execute(
            "UPDATE connections SET access_token_enc = ?, institution = ?, "
            "products = ?, sync_cursor = NULL, status = 'active', error = NULL "
            "WHERE id = ?",
            (encrypted, institution, products, connection_id),
        )
    else:
        connection_id = db.execute(
            "INSERT INTO connections (provider, institution, provider_ref, products,"
            " access_token_enc) VALUES ('plaid', ?, ?, ?, ?)",
            (institution, exchanged["item_id"], products, encrypted),
        )

    try:
        result = sync_service.sync_plaid(connection_id)
    except Exception as e:
        raise HTTPException(
            502, f"The connection was saved but the first sync failed: {e}"
        ) from e
    sync_service.snapshot_balances()
    return {"connection_id": connection_id, "institution": institution, **result}


@router.post("/snaptrade/portal")
def snaptrade_portal(broker: str | None = Query(None)):
    """A one-time URL where the brokerage login happens, on SnapTrade's page.

    Unlike Plaid there is no embeddable widget, so the browser opens this and
    nothing returns here on its own — the accounts are imported afterwards.
    """
    problem = snaptrade_service.configuration_problem()
    if problem:
        raise HTTPException(400, problem)
    try:
        return {"url": snaptrade_service.connection_portal_url(broker or None)}
    except snaptrade_service.SnapTradeError as e:
        raise HTTPException(502, str(e)) from e


@router.post("/snaptrade/import")
def snaptrade_import():
    """Adopt whatever was connected on SnapTrade's page, then sync it.

    Safe to call repeatedly: connections already known are refreshed rather
    than duplicated, which is what makes "did it work yet?" polling harmless.
    """
    problem = snaptrade_service.configuration_problem()
    if problem:
        raise HTTPException(400, problem)
    try:
        authorizations = snaptrade_service.list_connections()
    except snaptrade_service.SnapTradeError as e:
        raise HTTPException(502, str(e)) from e

    results = []
    for auth in authorizations:
        existing = db.query_one(
            "SELECT id FROM connections WHERE provider = 'snaptrade' AND provider_ref = ?",
            (auth["authorization_id"],),
        )
        if existing:
            connection_id = existing["id"]
            db.execute(
                "UPDATE connections SET institution = ?, status = 'active', error = NULL "
                "WHERE id = ?", (auth["institution"], connection_id),
            )
        else:
            connection_id = db.execute(
                "INSERT INTO connections (provider, institution, provider_ref, products)"
                " VALUES ('snaptrade', ?, ?, 'investments')",
                (auth["institution"], auth["authorization_id"]),
            )
        entry = {"connection_id": connection_id, "institution": auth["institution"]}
        try:
            entry.update(sync_service.sync_snaptrade(connection_id))
        except Exception as e:
            entry["error"] = f"{type(e).__name__}: {e}"
        results.append(entry)

    if results:
        sync_service.snapshot_balances()
    return {
        "connections": results,
        "accounts": sum(r.get("accounts", 0) for r in results),
        "holdings": sum(r.get("holdings", 0) for r in results),
        "found": len(authorizations),
    }


@router.post("/sync")
def sync_all():
    """Sync every connection. Partial failure is reported, not raised."""
    return sync_service.sync_all()


@router.post("/{connection_id}/sync")
def sync_one(connection_id: int):
    conn = db.query_one("SELECT * FROM connections WHERE id = ?", (connection_id,))
    if not conn:
        raise HTTPException(404, f"Connection {connection_id} not found.")
    try:
        if conn["provider"] == "plaid":
            result = sync_service.sync_plaid(connection_id)
        elif conn["provider"] == "snaptrade":
            result = sync_service.sync_snaptrade(connection_id)
        else:
            raise HTTPException(400, f"Provider '{conn['provider']}' cannot be synced.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"{type(e).__name__}: {e}") from e
    sync_service.snapshot_balances()
    return result


@router.delete("/{connection_id}")
def disconnect(connection_id: int, delete_accounts: bool = False):
    """Drop the stored token, and optionally the accounts it created.

    The token is always destroyed — leaving live credentials behind for a
    connection the user just removed would be the wrong default. Their history
    is kept unless explicitly discarded, so removing a connection does not
    silently rewrite past months' spending.
    """
    conn = db.query_one("SELECT * FROM connections WHERE id = ?", (connection_id,))
    if not conn:
        raise HTTPException(404, f"Connection {connection_id} not found.")

    removed = 0
    if delete_accounts:
        rows = db.query("SELECT id FROM accounts WHERE connection_id = ?", (connection_id,))
        removed = len(rows)
        db.execute("DELETE FROM accounts WHERE connection_id = ?", (connection_id,))
    else:
        db.execute(
            "UPDATE accounts SET connection_id = NULL, provider = 'manual' "
            "WHERE connection_id = ?", (connection_id,)
        )
    db.execute(
        "UPDATE connections SET status = 'disconnected', access_token_enc = NULL,"
        " error = NULL WHERE id = ?", (connection_id,)
    )
    return {"disconnected": connection_id, "accounts_removed": removed}
