"""Accounts, balances, and net worth."""

from fastapi import APIRouter, HTTPException

import db
from models.schemas import AccountUpdate, ManualAccount
from services import analytics as analytics_service
from services import sync_service

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("")
def list_accounts(include_inactive: bool = False):
    sql = """
        SELECT a.*, c.status AS connection_status, c.error AS connection_error,
               (SELECT COUNT(*) FROM transactions t WHERE t.account_id = a.id) AS transaction_count,
               (SELECT MAX(t.date) FROM transactions t WHERE t.account_id = a.id) AS latest_transaction
        FROM accounts a
        LEFT JOIN connections c ON c.id = a.connection_id
    """
    if not include_inactive:
        sql += " WHERE a.is_active = 1"
    sql += " ORDER BY CASE a.type WHEN 'depository' THEN 0 WHEN 'investment' THEN 1 ELSE 2 END, a.balance_current DESC"
    return {"accounts": db.query(sql), "net_worth": analytics_service.net_worth()}


@router.post("")
def create_manual_account(body: ManualAccount):
    """Create an account the app cannot sync — Apple Savings above all.

    Apple permits no third-party aggregation, so its balance is either typed in
    here or imported from a CSV. Treating that as a first-class account rather
    than an afterthought is what keeps net worth correct.
    """
    import uuid
    account_id = sync_service.upsert_account(
        provider="manual",
        provider_account_id=f"manual-{uuid.uuid4().hex[:12]}",
        institution=body.institution,
        name=body.name,
        type=body.type,
        subtype=body.subtype,
        mask=body.mask,
        balance_current=(
            -abs(body.balance_current) if body.type == "credit" else body.balance_current
        ),
        credit_limit=body.credit_limit,
        apy=body.apy,
    )
    if body.account_number or body.notes:
        db.execute(
            "UPDATE accounts SET account_number = ?, notes = ? WHERE id = ?",
            (body.account_number, body.notes, account_id),
        )
        # Show the last four in listings without storing a second copy.
        if body.account_number and not body.mask:
            digits = "".join(c for c in body.account_number if c.isdigit())
            if len(digits) >= 4:
                db.execute("UPDATE accounts SET mask = ? WHERE id = ?",
                           (digits[-4:], account_id))
    sync_service.snapshot_balances()
    return db.query_one("SELECT * FROM accounts WHERE id = ?", (account_id,))


@router.patch("/{account_id}")
def update_account(account_id: int, body: AccountUpdate):
    if not db.query_one("SELECT id FROM accounts WHERE id = ?", (account_id,)):
        raise HTTPException(404, f"Account {account_id} not found.")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        return db.query_one("SELECT * FROM accounts WHERE id = ?", (account_id,))
    if "is_active" in updates:
        updates["is_active"] = int(updates["is_active"])

    sets = ", ".join(f"{k} = ?" for k in updates)
    db.execute(f"UPDATE accounts SET {sets} WHERE id = ?",
               tuple(updates.values()) + (account_id,))
    if "balance_current" in updates:
        sync_service.snapshot_balances()
    return db.query_one("SELECT * FROM accounts WHERE id = ?", (account_id,))


@router.delete("/{account_id}")
def delete_account(account_id: int):
    """Remove an account and its transactions.

    Deliberately destructive and deliberately explicit: the alternative —
    hiding it — leaves its transactions in every spending total, which is worse
    than either option the user thinks they are choosing between.
    """
    account = db.query_one("SELECT * FROM accounts WHERE id = ?", (account_id,))
    if not account:
        raise HTTPException(404, f"Account {account_id} not found.")
    count = db.query_one(
        "SELECT COUNT(*) AS n FROM transactions WHERE account_id = ?", (account_id,)
    )["n"]
    db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    return {"deleted": account["name"], "transactions_removed": count}


@router.get("/net-worth/trend")
def net_worth_trend(months: int = 12):
    return {"trend": analytics_service.net_worth_trend(months)}
