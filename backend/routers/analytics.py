"""Spending analytics, recurring series, and savings insights."""

from fastapi import APIRouter, HTTPException

import db
from services import analytics as svc
from services import insights as insights_svc
from services import recurring as recurring_svc

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
recurring_router = APIRouter(prefix="/api/recurring", tags=["recurring"])
insights_router = APIRouter(prefix="/api/insights", tags=["insights"])


def _range(start: str | None, end: str | None, months: int) -> tuple[str, str]:
    if start and end:
        return start, end
    return svc.default_range(months)


@router.get("/overview")
def overview(months: int = 12):
    """Everything the Overview tab needs, in one round trip."""
    start, end = svc.default_range(1)
    return {
        "net_worth": svc.net_worth(),
        "net_worth_trend": svc.net_worth_trend(months),
        "cash_flow": svc.cash_flow(months),
        "this_month": svc.summary(start, end),
        "top_categories": svc.by_category(start, end)[:6],
        "budgets": svc.budget_status(),
        "accounts": db.query(
            "SELECT id, name, institution, type, subtype, mask, balance_current, "
            "       credit_limit, apy, last_synced FROM accounts WHERE is_active = 1 "
            "ORDER BY balance_current DESC"
        ),
    }


@router.get("/spending")
def spending(start: str | None = None, end: str | None = None, months: int = 1):
    """Everything the Spending tab needs."""
    s, e = _range(start, end, months)
    return {
        "range": {"start": s, "end": e},
        "summary": svc.summary(s, e),
        "by_category": svc.by_category(s, e),
        "by_subcategory": svc.by_subcategory(s, e),
        "by_merchant": svc.by_merchant(s, e, limit=25),
        "daily": svc.daily_spend(s, e),
        "category_trend": svc.category_trend(months=6),
        "baselines": svc.category_baselines(months=6),
    }


@router.get("/by-category")
def by_category(start: str | None = None, end: str | None = None, months: int = 1):
    s, e = _range(start, end, months)
    return {"range": {"start": s, "end": e}, "categories": svc.by_category(s, e)}


@router.get("/by-merchant")
def by_merchant(start: str | None = None, end: str | None = None, months: int = 1,
                limit: int = 25, category: str | None = None):
    s, e = _range(start, end, months)
    return {"range": {"start": s, "end": e},
            "merchants": svc.by_merchant(s, e, limit=limit, category=category)}


@router.get("/by-subcategory")
def by_subcategory(start: str | None = None, end: str | None = None, months: int = 1,
                   category: str | None = None):
    s, e = _range(start, end, months)
    return {"range": {"start": s, "end": e},
            "subcategories": svc.by_subcategory(s, e, category=category)}


@router.get("/cash-flow")
def cash_flow(months: int = 12):
    return {"cash_flow": svc.cash_flow(months)}


@router.get("/category-trend")
def category_trend(months: int = 6, top: int = 8):
    return svc.category_trend(months=months, top=top)


# --------------------------------------------------------------------------

@recurring_router.get("")
def list_recurring(active_only: bool = False):
    series = recurring_svc.list_series(active_only=active_only)
    active = [s for s in series if s["is_active"]]
    return {
        "series": series,
        "monthly_total": round(sum(s["monthly_cost"] for s in active), 2),
        "annual_total": round(sum(s["monthly_cost"] for s in active) * 12, 2),
        "active_count": len(active),
    }


@recurring_router.post("/refresh")
def refresh_recurring():
    return recurring_svc.refresh()


@recurring_router.patch("/{series_id}")
def set_series_status(series_id: int, user_status: str):
    if user_status not in ("none", "keep", "review", "cancelled"):
        raise HTTPException(400, "user_status must be none, keep, review, or cancelled.")
    if not db.query_one("SELECT id FROM recurring_series WHERE id = ?", (series_id,)):
        raise HTTPException(404, f"Series {series_id} not found.")
    db.execute("UPDATE recurring_series SET user_status = ? WHERE id = ?",
               (user_status, series_id))
    return db.query_one("SELECT * FROM recurring_series WHERE id = ?", (series_id,))


@recurring_router.get("/{series_id}/transactions")
def series_transactions(series_id: int):
    return {"transactions": db.query(
        "SELECT t.*, a.name AS account_name FROM transactions t "
        "JOIN accounts a ON a.id = t.account_id "
        "WHERE t.recurring_id = ? ORDER BY t.date DESC", (series_id,))}


# --------------------------------------------------------------------------

@insights_router.get("")
def get_insights():
    return insights_svc.generate()
