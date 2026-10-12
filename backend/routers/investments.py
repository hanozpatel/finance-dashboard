"""Holdings, allocation, and performance for the brokerage accounts."""

from fastapi import APIRouter

import db

router = APIRouter(prefix="/api/investments", tags=["investments"])


@router.get("")
def portfolio():
    holdings = db.query(
        "SELECT h.*, a.name AS account_name, a.institution FROM holdings h "
        "JOIN accounts a ON a.id = h.account_id WHERE a.is_active = 1 "
        "ORDER BY h.value DESC"
    )
    total_value = sum(h["value"] for h in holdings)
    # Cost basis is optional per holding, so gain is only reported across the
    # positions that actually have one — otherwise a single missing basis would
    # silently understate the whole portfolio's return.
    with_basis = [h for h in holdings if h.get("cost_basis")]
    basis_total = sum(h["cost_basis"] for h in with_basis)
    basis_value = sum(h["value"] for h in with_basis)

    by_type: dict[str, float] = {}
    for h in holdings:
        key = (h["security_type"] or "other").replace("_", " ").title()
        by_type[key] = round(by_type.get(key, 0.0) + h["value"], 2)

    enriched = []
    for h in holdings:
        gain = (h["value"] - h["cost_basis"]) if h.get("cost_basis") else None
        enriched.append({
            **h,
            "weight": round(h["value"] / total_value * 100, 2) if total_value else 0.0,
            "gain": round(gain, 2) if gain is not None else None,
            "gain_pct": round(gain / h["cost_basis"] * 100, 2)
            if gain is not None and h["cost_basis"] else None,
        })

    return {
        "holdings": enriched,
        "total_value": round(total_value, 2),
        "allocation": [{"type": k, "value": v,
                        "weight": round(v / total_value * 100, 2) if total_value else 0.0}
                       for k, v in sorted(by_type.items(), key=lambda kv: -kv[1])],
        "cost_basis": round(basis_total, 2),
        "total_gain": round(basis_value - basis_total, 2) if with_basis else None,
        "total_gain_pct": round((basis_value - basis_total) / basis_total * 100, 2)
        if basis_total else None,
        "positions_missing_basis": len(holdings) - len(with_basis),
        "accounts": db.query(
            "SELECT id, name, institution, balance_current, last_synced FROM accounts "
            "WHERE type = 'investment' AND is_active = 1"
        ),
    }
