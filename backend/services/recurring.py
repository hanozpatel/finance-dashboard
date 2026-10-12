"""Detect subscriptions and recurring bills from transaction history.

Nothing in a bank feed says "this is a subscription" — it has to be inferred
from rhythm. A merchant that charges a similar amount at a regular interval at
least three times is a recurring series; the regularity of the interval and the
stability of the amount become a confidence score, so the UI can separate
"definitely Netflix" from "you happen to buy groceries every nine days".

Three occurrences is the floor. Two points define an interval but not a
pattern, and acting on a two-point "subscription" means telling someone to
cancel a service they bought twice by coincidence.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta

import db

DAYS_PER_MONTH = 30.44
MIN_OCCURRENCES = 3
LOOKBACK_DAYS = 460          # ~15 months, so annual subscriptions can be seen twice

# (label, low, high, canonical) in days. Ranges are deliberately tight: a
# 20-day median gap is not a monthly bill, it is shopping.
CADENCES = [
    ("weekly",    6,   8,   7.0),
    ("biweekly",  12,  16,  14.0),
    ("monthly",   26,  34,  DAYS_PER_MONTH),
    ("quarterly", 83,  97,  91.3),
    ("semiannual",170, 195, 182.6),
    ("annual",    350, 380, 365.0),
]

# Share of gaps that must land inside the cadence window for the series to
# count as regular.
REGULARITY_THRESHOLD = 0.6
# Amount coefficient of variation above this means the charge is not fixed —
# usage-based utilities land here, which is correct: they are recurring but not
# a flat subscription.
AMOUNT_CV_CEILING = 0.35


def _parse(d: str) -> date:
    return datetime.strptime(d[:10], "%Y-%m-%d").date()


def _classify(median_gap: float) -> tuple[str, float] | None:
    for label, low, high, canonical in CADENCES:
        if low <= median_gap <= high:
            return label, canonical
    return None


def _series_from_group(merchant_key: str, rows: list[dict]) -> dict | None:
    """Build a recurring series from one merchant's transactions, or None."""
    if len(rows) < MIN_OCCURRENCES:
        return None

    rows = sorted(rows, key=lambda r: r["date"])
    dates = [_parse(r["date"]) for r in rows]
    # Same-day duplicates (a split charge) would read as a zero-day gap and
    # destroy the median, so collapse them first.
    deduped: list[date] = []
    for d in dates:
        if not deduped or (d - deduped[-1]).days > 0:
            deduped.append(d)
    if len(deduped) < MIN_OCCURRENCES:
        return None

    gaps = [(b - a).days for a, b in zip(deduped, deduped[1:])]
    if not gaps:
        return None
    median_gap = statistics.median(gaps)
    classified = _classify(median_gap)
    if not classified:
        return None
    cadence, canonical = classified

    low, high = next((lo, hi) for lbl, lo, hi, _ in CADENCES if lbl == cadence)
    in_window = sum(1 for g in gaps if low <= g <= high)
    regularity = in_window / len(gaps)
    if regularity < REGULARITY_THRESHOLD:
        return None

    amounts = [abs(r["amount"]) for r in rows]
    median_amt = statistics.median(amounts)
    if median_amt <= 0:
        return None
    mean_amt = statistics.fmean(amounts)
    cv = (statistics.pstdev(amounts) / mean_amt) if mean_amt > 0 and len(amounts) > 1 else 0.0
    if cv > AMOUNT_CV_CEILING:
        return None

    last = deduped[-1]
    next_expected = last + timedelta(days=round(canonical))
    # A series is stale once it has missed its slot by more than half a cycle.
    is_active = (date.today() - last).days <= canonical * 1.5

    # Confidence blends interval regularity, amount stability, and how many
    # times we have actually seen it. None of the three alone is convincing.
    occ_score = min(1.0, (len(deduped) - MIN_OCCURRENCES + 1) / 6.0)
    confidence = round(
        0.5 * regularity + 0.3 * (1 - min(cv / AMOUNT_CV_CEILING, 1.0)) + 0.2 * occ_score,
        3,
    )

    # Price creep: compare the mean of the earliest third to the latest third,
    # which is robust to a single odd charge in a way first-vs-last is not.
    third = max(1, len(amounts) // 3)
    early, late = statistics.fmean(amounts[:third]), statistics.fmean(amounts[-third:])
    price_increase = round(late / early, 4) if early > 0 else None

    categories = [r["category"] for r in rows if r.get("category")]
    category = statistics.mode(categories) if categories else None

    return {
        "merchant_key": merchant_key,
        "display_name": rows[-1].get("merchant") or merchant_key.title(),
        "category": category,
        "cadence": cadence,
        "interval_days": round(median_gap, 2),
        "amount_median": round(median_amt, 2),
        "amount_min": round(min(amounts), 2),
        "amount_max": round(max(amounts), 2),
        "monthly_cost": round(median_amt * (DAYS_PER_MONTH / canonical), 2),
        "occurrences": len(deduped),
        "first_date": deduped[0].isoformat(),
        "last_date": last.isoformat(),
        "next_expected": next_expected.isoformat(),
        "confidence": confidence,
        "is_active": 1 if is_active else 0,
        "price_increase": price_increase,
    }


def detect(lookback_days: int = LOOKBACK_DAYS) -> list[dict]:
    """Find every recurring series in recent history. Does not write."""
    since = (date.today() - timedelta(days=lookback_days)).isoformat()
    rows = db.query(
        "SELECT merchant_key, merchant, amount, date, category "
        "FROM transactions "
        "WHERE date >= ? AND amount < 0 AND is_transfer = 0 AND excluded = 0 "
        "  AND merchant_key IS NOT NULL AND merchant_key != '' "
        "ORDER BY merchant_key, date",
        (since,),
    )
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["merchant_key"], []).append(r)

    series = [s for s in (_series_from_group(k, v) for k, v in groups.items()) if s]
    series.sort(key=lambda s: -s["monthly_cost"])
    return series


def refresh() -> dict:
    """Re-detect and persist, preserving the user's per-series decisions.

    ``user_status`` is the one column the user owns, so an upsert must never
    clobber it — that is why this is not a delete-and-reinsert.
    """
    series = detect()
    keys = {s["merchant_key"] for s in series}

    with db.tx() as conn:
        for s in series:
            conn.execute(
                """
                INSERT INTO recurring_series
                    (merchant_key, display_name, category, cadence, interval_days,
                     amount_median, amount_min, amount_max, monthly_cost, occurrences,
                     first_date, last_date, next_expected, confidence, is_active,
                     price_increase)
                VALUES (:merchant_key, :display_name, :category, :cadence, :interval_days,
                        :amount_median, :amount_min, :amount_max, :monthly_cost, :occurrences,
                        :first_date, :last_date, :next_expected, :confidence, :is_active,
                        :price_increase)
                ON CONFLICT(merchant_key) DO UPDATE SET
                    display_name  = excluded.display_name,
                    category      = excluded.category,
                    cadence       = excluded.cadence,
                    interval_days = excluded.interval_days,
                    amount_median = excluded.amount_median,
                    amount_min    = excluded.amount_min,
                    amount_max    = excluded.amount_max,
                    monthly_cost  = excluded.monthly_cost,
                    occurrences   = excluded.occurrences,
                    first_date    = excluded.first_date,
                    last_date     = excluded.last_date,
                    next_expected = excluded.next_expected,
                    confidence    = excluded.confidence,
                    is_active     = excluded.is_active,
                    price_increase= excluded.price_increase
                """,
                s,
            )
        # A series that no longer qualifies is marked inactive rather than
        # deleted, so a cancelled subscription stays visible as evidence.
        existing = [r["merchant_key"] for r in conn.execute(
            "SELECT merchant_key FROM recurring_series").fetchall()]
        for key in existing:
            if key not in keys:
                conn.execute(
                    "UPDATE recurring_series SET is_active = 0 WHERE merchant_key = ?",
                    (key,),
                )

        # Link transactions to their series so the UI can show the history
        # behind any given subscription.
        conn.execute("UPDATE transactions SET recurring_id = NULL")
        conn.execute(
            "UPDATE transactions SET recurring_id = ("
            "  SELECT r.id FROM recurring_series r "
            "  WHERE r.merchant_key = transactions.merchant_key"
            ") WHERE merchant_key IN (SELECT merchant_key FROM recurring_series)"
        )

    return {
        "detected": len(series),
        "active": sum(1 for s in series if s["is_active"]),
        "monthly_total": round(sum(s["monthly_cost"] for s in series if s["is_active"]), 2),
    }


def list_series(active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM recurring_series"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY monthly_cost DESC"
    return db.query(sql)
