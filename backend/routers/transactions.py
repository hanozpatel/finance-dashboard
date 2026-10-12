"""Transaction list, edits, categorisation rules, and budgets."""

from fastapi import APIRouter, HTTPException, Query

import db
from models.schemas import (
    BudgetUpdate, BulkCategorize, CategoryRule, ManualTransaction, ReviewAnswer,
    TransactionUpdate,
)
from services import analytics as analytics_service
from services import categorize, recurring, review, sync_service

router = APIRouter(prefix="/api/transactions", tags=["transactions"])
rules_router = APIRouter(prefix="/api/rules", tags=["rules"])
budgets_router = APIRouter(prefix="/api/budgets", tags=["budgets"])


@router.get("")
def list_transactions(
    start: str | None = None,
    end: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    account_id: int | None = None,
    merchant_key: str | None = None,
    search: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    include_transfers: bool = False,
    recurring_only: bool = False,
    uncategorized_only: bool = False,
    sort: str = Query("date", pattern="^(date|amount|merchant|category)$"),
    direction: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Filtered, sorted, paginated transactions.

    ``min_amount``/``max_amount`` filter on the *magnitude*, because "show me
    everything over $100" is a question about size, not about sign.
    """
    where, params = ["1 = 1"], []

    if start:
        where.append("t.date >= ?"); params.append(start)
    if end:
        where.append("t.date <= ?"); params.append(end)
    if category:
        where.append("t.category = ?"); params.append(category)
    if subcategory:
        where.append("t.subcategory = ?"); params.append(subcategory)
    if account_id:
        where.append("t.account_id = ?"); params.append(account_id)
    if merchant_key:
        where.append("t.merchant_key = ?"); params.append(merchant_key)
    if search:
        where.append("(t.description LIKE ? OR t.merchant LIKE ? OR t.notes LIKE ?)")
        params += [f"%{search}%"] * 3
    if min_amount is not None:
        where.append("ABS(t.amount) >= ?"); params.append(min_amount)
    if max_amount is not None:
        where.append("ABS(t.amount) <= ?"); params.append(max_amount)
    if not include_transfers:
        where.append("t.is_transfer = 0")
    if recurring_only:
        where.append("t.recurring_id IS NOT NULL")
    if uncategorized_only:
        where.append("t.category = 'Uncategorized'")

    clause = " AND ".join(where)
    order = {"date": "t.date", "amount": "t.amount", "merchant": "t.merchant",
             "category": "t.category"}[sort]
    # A stable secondary key stops rows shuffling between pages when many share
    # the same date.
    order_sql = f"{order} {direction.upper()}, t.id DESC"

    rows = db.query(
        f"""
        SELECT t.*, a.name AS account_name, a.institution, a.type AS account_type,
               a.mask, r.display_name AS recurring_name, r.cadence AS recurring_cadence
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        LEFT JOIN recurring_series r ON r.id = t.recurring_id
        WHERE {clause}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
        """,
        tuple(params) + (limit, offset),
    )
    totals = db.query_one(
        f"""
        SELECT COUNT(*) AS count,
               COALESCE(-SUM(CASE WHEN t.amount < 0 THEN t.amount END), 0) AS outflow,
               COALESCE(SUM(CASE WHEN t.amount > 0 THEN t.amount END), 0)  AS inflow
        FROM transactions t JOIN accounts a ON a.id = t.account_id
        WHERE {clause}
        """,
        tuple(params),
    )
    return {
        "transactions": rows,
        "total_count": totals["count"],
        "outflow": round(totals["outflow"], 2),
        "inflow": round(totals["inflow"], 2),
        "net": round(totals["inflow"] - totals["outflow"], 2),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(rows) < totals["count"],
    }


@router.post("")
def create_transaction(body: ManualTransaction):
    """Record a transaction by hand — Apple Savings interest, cash, a deposit.

    With ``update_balance`` the account balance moves by the same amount. For a
    manual account that is almost always what you want: recording $214 of
    interest without moving the balance leaves the ledger and the headline
    figure telling different stories.
    """
    account = db.query_one("SELECT * FROM accounts WHERE id = ?", (body.account_id,))
    if not account:
        raise HTTPException(404, f"Account {body.account_id} not found.")

    result = sync_service.insert_transactions(
        body.account_id,
        [{"date": body.date, "amount": body.amount, "description": body.description,
          "provider_merchant": None, "raw_category": None}],
        source="manual",
    )
    if body.category:
        latest = db.query_one(
            "SELECT id FROM transactions WHERE account_id = ? ORDER BY id DESC LIMIT 1",
            (body.account_id,),
        )
        db.execute("UPDATE transactions SET category = ?, subcategory = ? WHERE id = ?",
                   (body.category, body.subcategory, latest["id"]))

    new_balance = account["balance_current"]
    if body.update_balance and result["inserted"]:
        new_balance = round(account["balance_current"] + body.amount, 2)
        db.execute("UPDATE accounts SET balance_current = ? WHERE id = ?",
                   (new_balance, body.account_id))
        sync_service.snapshot_balances()

    return {**result, "balance": new_balance, "balance_updated": bool(
        body.update_balance and result["inserted"])}


@router.patch("/{transaction_id}")
def update_transaction(transaction_id: int, body: TransactionUpdate):
    if not db.query_one("SELECT id FROM transactions WHERE id = ?", (transaction_id,)):
        raise HTTPException(404, f"Transaction {transaction_id} not found.")
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return db.query_one("SELECT * FROM transactions WHERE id = ?", (transaction_id,))
    for flag in ("is_transfer", "excluded"):
        if flag in updates:
            updates[flag] = int(updates[flag])
    sets = ", ".join(f"{k} = ?" for k in updates)
    db.execute(f"UPDATE transactions SET {sets} WHERE id = ?",
               tuple(updates.values()) + (transaction_id,))
    return db.query_one("SELECT * FROM transactions WHERE id = ?", (transaction_id,))


@router.post("/bulk-categorize")
def bulk_categorize(body: BulkCategorize):
    """Recategorise a selection, optionally turning it into a standing rule."""
    placeholders = ",".join("?" * len(body.transaction_ids))
    rows = db.query(
        f"SELECT id, merchant, merchant_key FROM transactions WHERE id IN ({placeholders})",
        tuple(body.transaction_ids),
    )
    if not rows:
        raise HTTPException(404, "None of those transactions exist.")

    db.execute(
        f"UPDATE transactions SET category = ?, subcategory = ? WHERE id IN ({placeholders})",
        (body.category, body.subcategory) + tuple(body.transaction_ids),
    )

    rule_created = None
    if body.create_rule:
        # Use the merchant shared by the selection; a rule built from a mixed
        # selection would fire on merchants the user never looked at.
        keys = {r["merchant_key"] for r in rows if r["merchant_key"]}
        if len(keys) == 1:
            pattern = keys.pop()
            db.execute(
                "INSERT INTO category_rules (match_type, pattern, category, subcategory, priority)"
                " VALUES ('merchant_contains', ?, ?, ?, 50)",
                (pattern, body.category, body.subcategory),
            )
            rule_created = pattern
        else:
            rule_created = None

    return {"updated": len(rows), "rule_created": rule_created,
            "rule_skipped_reason": None if rule_created or not body.create_rule
            else "The selection spans more than one merchant, so no rule was created."}


@router.get("/review")
def review_queue(limit: int = Query(60, ge=1, le=200)):
    """Uncategorised transactions as one question per merchant, with guesses."""
    return review.queue(limit)


@router.get("/review/stats")
def review_stats():
    return review.stats()


@router.post("/review/answer")
def review_answer(body: ReviewAnswer):
    """Answer one question: categorise the merchant and remember the answer."""
    try:
        return review.answer(
            merchant_key=body.merchant_key,
            category=body.category,
            subcategory=body.subcategory,
            create_rule=body.create_rule,
            transaction_ids=body.transaction_ids,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/categories")
def categories():
    """Known categories plus the subcategories actually in use."""
    used = db.query(
        "SELECT category, subcategory, COUNT(*) AS n FROM transactions "
        "WHERE subcategory IS NOT NULL GROUP BY category, subcategory ORDER BY category, n DESC"
    )
    by_category: dict[str, list[str]] = {}
    for r in used:
        by_category.setdefault(r["category"], []).append(r["subcategory"])
    return {"categories": categorize.ALL_CATEGORIES, "subcategories": by_category}


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

@rules_router.get("")
def list_rules():
    return {"rules": db.query(
        "SELECT * FROM category_rules ORDER BY priority ASC, id ASC")}


@rules_router.post("")
def create_rule(body: CategoryRule):
    import re
    if body.match_type == "description_regex":
        try:
            re.compile(body.pattern)
        except re.error as e:
            raise HTTPException(400, f"That is not a valid regular expression: {e}")
    rule_id = db.execute(
        "INSERT INTO category_rules (match_type, pattern, category, subcategory,"
        " is_transfer, priority) VALUES (?, ?, ?, ?, ?, ?)",
        (body.match_type, body.pattern, body.category, body.subcategory,
         int(body.is_transfer), body.priority),
    )
    # A new rule is worthless until it is applied to the history already stored.
    affected = categorize.recategorize_all()
    recurring.refresh()
    return {"rule": db.query_one("SELECT * FROM category_rules WHERE id = ?", (rule_id,)),
            "transactions_recategorized": affected}


@rules_router.delete("/{rule_id}")
def delete_rule(rule_id: int):
    if not db.query_one("SELECT id FROM category_rules WHERE id = ?", (rule_id,)):
        raise HTTPException(404, f"Rule {rule_id} not found.")
    db.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,))
    affected = categorize.recategorize_all()
    recurring.refresh()
    return {"deleted": rule_id, "transactions_recategorized": affected}


@rules_router.post("/reapply")
def reapply_rules():
    affected = categorize.recategorize_all()
    derived = recurring.refresh()
    return {"transactions_recategorized": affected, "recurring": derived}


# --------------------------------------------------------------------------
# Budgets
# --------------------------------------------------------------------------

@budgets_router.get("")
def list_budgets(month: str | None = None):
    return {"budgets": analytics_service.budget_status(month)}


@budgets_router.put("")
def set_budget(body: BudgetUpdate):
    if body.monthly_limit == 0:
        db.execute("DELETE FROM budgets WHERE category = ?", (body.category,))
        return {"deleted": body.category}
    db.execute(
        "INSERT INTO budgets (category, monthly_limit) VALUES (?, ?) "
        "ON CONFLICT(category) DO UPDATE SET monthly_limit = excluded.monthly_limit",
        (body.category, body.monthly_limit),
    )
    return {"budgets": analytics_service.budget_status()}
