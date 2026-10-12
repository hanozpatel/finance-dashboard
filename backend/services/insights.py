"""Ranked, quantified places to cut spending.

Every insight must answer "how much per month, and what do I do about it" with
a number traceable to real transactions. An insight that cannot estimate a
dollar figure is not emitted, because an unquantified suggestion cannot be
ranked against the others and so cannot be acted on in order.

Estimates are deliberately conservative and each carries its assumption in
``basis``, so a number the user disagrees with can be argued with rather than
just distrusted.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta

import db
from services import analytics, recurring

# Share of a delivery order that is fee, tip, and menu markup rather than food.
# Conservative end of the commonly cited 30-45% range.
DELIVERY_PREMIUM = 0.30
# How much of a habitual small-purchase run is realistically cuttable.
SMALL_PURCHASE_CUTTABLE = 0.40
SMALL_PURCHASE_CEILING = 15.00
# Months of spending to leave in checking before calling the rest idle.
CHECKING_BUFFER_MONTHS = 1.5
# A category has to be this far above its own baseline, in both percent and
# dollars, before it is worth mentioning.
OVERAGE_PCT = 20.0
OVERAGE_MIN = 50.00
# Subscription price creep worth flagging.
PRICE_CREEP_RATIO = 1.15

EFFORT_EASY, EFFORT_MODERATE, EFFORT_HARD = "easy", "moderate", "hard"


def _trailing_complete_months(n: int = 3) -> tuple[str, str, int]:
    """(start, end, month_count) over the last ``n`` *complete* months."""
    this_month = analytics.month_start(date.today())
    start = analytics.add_months(this_month, -n)
    end = this_month - timedelta(days=1)
    return start.isoformat(), end.isoformat(), n


def _monthly_avg(sql_extra: str, params: tuple, months: int = 3) -> float:
    start, end, n = _trailing_complete_months(months)
    row = db.query_one(
        f"SELECT COALESCE(-SUM(t.amount), 0) AS spend FROM transactions t "
        f"WHERE {analytics.SPEND_WHERE} AND t.date BETWEEN ? AND ? {sql_extra}",
        (start, end) + params,
    )
    return (row["spend"] or 0.0) / n


def _insight(**kw) -> dict:
    monthly = round(max(0.0, kw.pop("monthly_savings")), 2)
    return {
        "monthly_savings": monthly,
        "annual_savings": round(monthly * 12, 2),
        **kw,
    }


# --------------------------------------------------------------------------
# Generators. Each returns a list (possibly empty) of insights.
# --------------------------------------------------------------------------

def _fees_and_interest() -> list[dict]:
    """Bank fees and card interest are the only spending that is ~100% waste."""
    start, end, n = _trailing_complete_months(3)
    rows = db.query(
        f"SELECT COALESCE(t.subcategory, 'Fee') AS sub, -SUM(t.amount) AS spend, "
        f"       COUNT(*) AS n FROM transactions t "
        f"WHERE {analytics.SPEND_WHERE} AND t.category = 'Fees & Interest' "
        f"  AND t.date BETWEEN ? AND ? GROUP BY sub ORDER BY spend DESC",
        (start, end),
    )
    total = sum(r["spend"] for r in rows)
    if total < 5:
        return []
    monthly = total / n
    worst = ", ".join(f"{r['sub']} (${r['spend']:,.0f})" for r in rows[:3])
    return [_insight(
        id="fees_interest",
        kind="waste",
        title="Eliminate bank fees and card interest",
        summary=f"${monthly:,.0f}/mo in fees and interest — all of it avoidable.",
        detail=(
            f"Over the last {n} complete months you paid ${total:,.2f} in fees and "
            f"interest. Largest: {worst}. Interest charges mean a revolving card "
            f"balance, which is the most expensive money you can borrow; fees are "
            f"usually fixed by autopay, a different account tier, or a no-foreign-"
            f"transaction-fee card."
        ),
        monthly_savings=monthly,
        effort=EFFORT_EASY,
        category="Fees & Interest",
        basis=f"100% of the {n}-month average; these charges have no offsetting value.",
        evidence=[{"label": r["sub"], "amount": round(r["spend"], 2), "count": r["n"]}
                  for r in rows],
    )]


def _subscription_audit(series: list[dict]) -> list[dict]:
    active = [s for s in series if s["is_active"] and s["category"] != "Housing"]
    if not active:
        return []
    total = sum(s["monthly_cost"] for s in active)
    if total < 10:
        return []

    # Ranked cancellation candidates: discretionary categories, cheapest
    # commitment to break first. Nothing here knows whether a service is
    # *used*, so this is framed as a review list, not an instruction.
    discretionary = [
        s for s in active
        if s["category"] in ("Subscriptions", "Entertainment", "Health")
    ]
    discretionary.sort(key=lambda s: -s["monthly_cost"])
    reviewable = sum(s["monthly_cost"] for s in discretionary)

    out = [_insight(
        id="subscription_audit",
        kind="review",
        title=f"Review {len(active)} recurring charges totalling ${total:,.0f}/mo",
        summary=f"${total * 12:,.0f}/yr committed to subscriptions and bills.",
        detail=(
            f"{len(active)} active recurring charges were detected, worth "
            f"${total:,.2f}/mo (${total * 12:,.2f}/yr). Of that, ${reviewable:,.2f}/mo "
            f"sits in discretionary categories. The estimate below assumes you "
            f"cancel a quarter of the discretionary total — the usual outcome of "
            f"an audit, not a specific recommendation."
        ),
        monthly_savings=reviewable * 0.25,
        effort=EFFORT_EASY,
        category="Subscriptions",
        basis="25% of discretionary recurring spend; adjust once you mark each one keep/cancel.",
        evidence=[{"label": s["display_name"], "amount": s["monthly_cost"],
                   "count": s["occurrences"], "note": s["cadence"]}
                  for s in discretionary[:15]],
    )]

    # Overlapping services in one subcategory: four streaming apps is a real,
    # common, and easily-fixed duplication.
    sub_by_key = {
        r["merchant_key"]: r["subcategory"]
        for r in db.query(
            "SELECT merchant_key, subcategory, MAX(date) AS latest FROM transactions "
            "WHERE subcategory IS NOT NULL GROUP BY merchant_key"
        )
    }
    by_sub: dict[str, list[dict]] = {}
    for s in discretionary:
        by_sub.setdefault(sub_by_key.get(s["merchant_key"]) or "Other", []).append(s)

    for sub, group in sorted(by_sub.items(), key=lambda kv: -sum(s["monthly_cost"] for s in kv[1])):
        if sub in ("Other",) or len(group) < 3:
            continue
        group.sort(key=lambda s: -s["monthly_cost"])
        # Keep the most expensive (usually the most-used); the rest are the
        # candidates.
        droppable = sum(s["monthly_cost"] for s in group[1:])
        out.append(_insight(
            id=f"overlap_{sub.lower().replace(' ', '_')}",
            kind="duplication",
            title=f"{len(group)} overlapping {sub.lower()} subscriptions",
            summary=f"${droppable:,.0f}/mo beyond the largest {sub.lower()} service.",
            detail=(
                f"You pay for {len(group)} {sub.lower()} services: "
                + ", ".join(f"{s['display_name']} (${s['monthly_cost']:,.2f}/mo)" for s in group)
                + f". Keeping only {group[0]['display_name']} frees ${droppable:,.2f}/mo. "
                f"Rotating — one service at a time, cancelled when you finish a show — "
                f"captures most of this without giving anything up permanently."
            ),
            monthly_savings=droppable * 0.5,
            effort=EFFORT_EASY,
            category="Subscriptions",
            basis="Half the non-largest services in this subcategory, assuming you rotate rather than cut outright.",
            evidence=[{"label": s["display_name"], "amount": s["monthly_cost"]} for s in group],
        ))
    return out


def _price_creep(series: list[dict]) -> list[dict]:
    risen = [
        s for s in series
        if s["is_active"] and s.get("price_increase")
        and s["price_increase"] >= PRICE_CREEP_RATIO and s["occurrences"] >= 4
    ]
    if not risen:
        return []
    risen.sort(key=lambda s: -(s["amount_max"] - s["amount_min"]))

    def monthly_increase(s: dict) -> float:
        # The median is the current price; dividing by the observed ratio
        # recovers the original. Times charges-per-month so an annual plan and a
        # monthly plan are directly comparable.
        per_charge = s["amount_median"] * (1 - 1 / s["price_increase"])
        return per_charge * _charges_per_month(s)

    extra = sum(monthly_increase(s) for s in risen)
    if extra < 2:
        return []
    return [_insight(
        id="price_creep",
        kind="waste",
        title=(f"{len(risen)} subscription{'s' if len(risen) != 1 else ''} "
               f"quietly raised {'their' if len(risen) != 1 else 'its'} price"),
        summary=f"${extra:,.0f}/mo more than when you signed up.",
        detail=(
            "These recurring charges cost more now than they did at the start of "
            "the window: "
            + ", ".join(
                f"{s['display_name']} ${s['amount_min']:,.2f} → ${s['amount_max']:,.2f}"
                f" (+{(s['price_increase'] - 1) * 100:,.0f}%)"
                for s in risen[:8]
            )
            + ". Retention offers are routine — asking is usually enough to get the "
            "old price back, and cancelling is the fallback."
        ),
        monthly_savings=extra,
        effort=EFFORT_EASY,
        category="Subscriptions",
        basis="Difference between current and original price, normalised to monthly.",
        evidence=[{"label": s["display_name"], "amount": round(s["amount_max"] - s["amount_min"], 2),
                   "note": f"+{(s['price_increase'] - 1) * 100:,.0f}%"} for s in risen],
    )]


def _charges_per_month(s: dict) -> float:
    """Charges-per-month for a series, so annual and monthly plans compare."""
    return recurring.DAYS_PER_MONTH / max(1.0, s["interval_days"])


def _delivery_premium() -> list[dict]:
    monthly = _monthly_avg("AND t.subcategory = 'Delivery'", ())
    if monthly < 25:
        return []
    saving = monthly * DELIVERY_PREMIUM
    return [_insight(
        id="delivery_premium",
        kind="substitution",
        title="Food delivery carries a 30% markup",
        summary=f"${saving:,.0f}/mo is fees, tip, and menu markup — not food.",
        detail=(
            f"You average ${monthly:,.2f}/mo on delivery. Delivery platforms add "
            f"inflated menu prices, service fees, delivery fees, and tip — "
            f"commonly 30-45% over the same order collected in person. At the "
            f"conservative end, switching to pickup on the same orders saves "
            f"${saving:,.2f}/mo without changing what you eat."
        ),
        monthly_savings=saving,
        effort=EFFORT_MODERATE,
        category="Dining",
        basis=f"{DELIVERY_PREMIUM:.0%} of delivery spend, the low end of the typical markup range.",
        evidence=[{"label": "Avg monthly delivery spend", "amount": round(monthly, 2)}],
    )]


def _dining_vs_groceries() -> list[dict]:
    dining = _monthly_avg("AND t.category = 'Dining'", ())
    groceries = _monthly_avg("AND t.category = 'Groceries'", ())
    if dining < 150 or dining <= groceries:
        return []
    # Shifting a fifth of restaurant spend to groceries; home cooking runs
    # roughly a third the per-meal cost, so the shifted dollars shrink by ~65%.
    shifted = dining * 0.20
    saving = shifted * 0.65
    return [_insight(
        id="dining_vs_groceries",
        kind="substitution",
        title="Dining out exceeds groceries",
        summary=f"${dining:,.0f}/mo eating out vs ${groceries:,.0f}/mo on groceries.",
        detail=(
            f"Restaurant and takeout spending averages ${dining:,.2f}/mo against "
            f"${groceries:,.2f}/mo of groceries — meals are mostly being bought "
            f"rather than cooked. Moving one fifth of restaurant spend "
            f"(${shifted:,.2f}) to home cooking costs about ${shifted * 0.35:,.2f} "
            f"in groceries, netting ${saving:,.2f}/mo."
        ),
        monthly_savings=saving,
        effort=EFFORT_HARD,
        category="Dining",
        basis="20% of dining shifted to groceries, at roughly one third the per-meal cost.",
        evidence=[
            {"label": "Dining (monthly avg)", "amount": round(dining, 2)},
            {"label": "Groceries (monthly avg)", "amount": round(groceries, 2)},
        ],
    )]


def _small_purchase_leakage() -> list[dict]:
    start, end, n = _trailing_complete_months(3)
    row = db.query_one(
        f"SELECT COUNT(*) AS n, COALESCE(-SUM(t.amount), 0) AS spend FROM transactions t "
        f"WHERE {analytics.SPEND_WHERE} AND t.date BETWEEN ? AND ? "
        f"  AND -t.amount <= ? AND -t.amount > 0 "
        f"  AND t.category IN ('Dining', 'Entertainment', 'Shopping')",
        (start, end, SMALL_PURCHASE_CEILING),
    )
    count, spend = row["n"] or 0, row["spend"] or 0.0
    if count < 30 or spend < 90:
        return []
    monthly = spend / n
    per_month_count = count / n
    top = db.query(
        f"SELECT MAX(t.merchant) AS merchant, COUNT(*) AS n, -SUM(t.amount) AS spend "
        f"FROM transactions t WHERE {analytics.SPEND_WHERE} AND t.date BETWEEN ? AND ? "
        f"  AND -t.amount <= ? AND -t.amount > 0 "
        f"  AND t.category IN ('Dining', 'Entertainment', 'Shopping') "
        f"GROUP BY t.merchant_key ORDER BY spend DESC LIMIT 6",
        (start, end, SMALL_PURCHASE_CEILING),
    )
    return [_insight(
        id="small_purchase_leakage",
        kind="habit",
        title=f"{per_month_count:,.0f} small purchases a month add up",
        summary=f"${monthly:,.0f}/mo in charges under ${SMALL_PURCHASE_CEILING:,.0f}.",
        detail=(
            f"{count} discretionary charges under ${SMALL_PURCHASE_CEILING:,.0f} over "
            f"{n} months, ${spend:,.2f} in total — ${monthly:,.2f}/mo, none of it "
            f"individually noticeable. This is the spending that does not feel like "
            f"a decision, which is exactly why it is the easiest to halve."
        ),
        monthly_savings=monthly * SMALL_PURCHASE_CUTTABLE,
        effort=EFFORT_MODERATE,
        category="Dining",
        basis=f"{SMALL_PURCHASE_CUTTABLE:.0%} of small-charge volume.",
        evidence=[{"label": r["merchant"] or "Unknown", "amount": round(r["spend"], 2),
                   "count": r["n"]} for r in top],
    )]


def _categories_above_baseline() -> list[dict]:
    """Categories running hot against their own trailing median."""
    baselines = analytics.category_baselines(months=6)
    this_month = analytics.month_start(date.today())
    last_month_start = analytics.add_months(this_month, -1)
    last_month_end = this_month - timedelta(days=1)
    actual = {
        r["category"]: r["spend"]
        for r in db.query(
            f"SELECT t.category AS category, -SUM(t.amount) AS spend FROM transactions t "
            f"WHERE {analytics.SPEND_WHERE} AND t.date BETWEEN ? AND ? GROUP BY t.category",
            (last_month_start.isoformat(), last_month_end.isoformat()),
        )
    }
    out = []
    for cat, spend in sorted(actual.items(), key=lambda kv: -kv[1]):
        base = baselines.get(cat)
        if not base or base["months"] < 3 or cat in ("Housing", "Taxes"):
            continue
        median = base["median"]
        if median <= 0:
            continue
        over = spend - median
        pct = over / median * 100
        if pct < OVERAGE_PCT or over < OVERAGE_MIN:
            continue
        out.append(_insight(
            id=f"overage_{cat.lower().replace(' ', '_').replace('&', 'and')}",
            kind="anomaly",
            title=f"{cat} ran {pct:,.0f}% above your normal",
            summary=f"${over:,.0f} more than your ${median:,.0f} median month.",
            detail=(
                f"{last_month_start.strftime('%B')} {cat} spending was ${spend:,.2f} "
                f"against a {base['months']}-month median of ${median:,.2f} "
                f"(range ${base['min']:,.2f}–${base['max']:,.2f}). Returning to the "
                f"median saves ${over:,.2f}/mo. If the increase was deliberate, set a "
                f"budget at the new level so it stops showing up here."
            ),
            monthly_savings=over,
            effort=EFFORT_MODERATE,
            category=cat,
            basis=f"Last complete month minus the {base['months']}-month median for this category.",
            evidence=[
                {"label": f"{last_month_start.strftime('%b %Y')} actual", "amount": round(spend, 2)},
                {"label": "Median month", "amount": median},
                {"label": "Best month", "amount": base["min"]},
            ],
        ))
    return out[:5]


def _idle_cash() -> list[dict]:
    """Cash parked in checking earning nothing, versus the savings APY."""
    checking = db.query_one(
        "SELECT COALESCE(SUM(balance_current), 0) AS v, COALESCE(AVG(apy), 0) AS apy "
        "FROM accounts WHERE is_active = 1 AND type = 'depository' "
        "  AND (subtype = 'checking' OR subtype IS NULL)"
    )
    savings = db.query_one(
        "SELECT COALESCE(MAX(apy), 0) AS apy FROM accounts "
        "WHERE is_active = 1 AND type = 'depository' AND subtype = 'savings'"
    )
    checking_balance = checking["v"] or 0.0
    checking_apy = checking["apy"] or 0.0
    savings_apy = savings["apy"] or 0.0
    if savings_apy - checking_apy < 0.5:
        return []

    monthly_spend = _monthly_avg("", ())
    buffer = monthly_spend * CHECKING_BUFFER_MONTHS
    idle = checking_balance - buffer
    if idle < 1000:
        return []

    gain = idle * (savings_apy - checking_apy) / 100.0 / 12.0
    if gain < 5:
        return []
    return [_insight(
        id="idle_cash",
        kind="optimization",
        title=f"${idle:,.0f} sitting idle in checking",
        summary=f"${gain:,.0f}/mo of interest you are not earning.",
        detail=(
            f"Checking holds ${checking_balance:,.2f}. Keeping "
            f"{CHECKING_BUFFER_MONTHS:g} months of spending (${buffer:,.2f}) as a "
            f"buffer leaves ${idle:,.2f} idle at {checking_apy:.2f}%, while your "
            f"savings account pays {savings_apy:.2f}%. Moving it earns "
            f"${gain:,.2f}/mo (${gain * 12:,.2f}/yr) and — unlike every other item "
            f"here — costs you nothing at all."
        ),
        monthly_savings=gain,
        effort=EFFORT_EASY,
        category="Optimization",
        basis=f"Balance above a {CHECKING_BUFFER_MONTHS:g}-month buffer, at the APY spread.",
        evidence=[
            {"label": "Checking balance", "amount": round(checking_balance, 2)},
            {"label": "Recommended buffer", "amount": round(buffer, 2)},
            {"label": "Idle", "amount": round(idle, 2)},
        ],
    )]


def _budget_overages() -> list[dict]:
    """Budgets that are consistently exceeded, measured over complete months.

    Deliberately *not* based on the current month prorated to its end: on the
    12th, two early charges extrapolate into a four-figure annual claim that
    then outranks every real finding. A budget missed on average across three
    finished months is a pattern; a budget tracking high on day 12 is noise.
    """
    start, end, n = _trailing_complete_months(3)
    actual = {
        r["category"]: r["spend"] / n
        for r in db.query(
            f"SELECT t.category AS category, -SUM(t.amount) AS spend FROM transactions t "
            f"WHERE {analytics.SPEND_WHERE} AND t.date BETWEEN ? AND ? GROUP BY t.category",
            (start, end),
        )
    }
    out = []
    for b in db.query("SELECT * FROM budgets ORDER BY category"):
        limit = b["monthly_limit"]
        avg = actual.get(b["category"], 0.0)
        over = avg - limit
        if limit <= 0 or over < 25:
            continue
        out.append(_insight(
            id=f"budget_{b['category'].lower().replace(' ', '_').replace('&', 'and')}",
            kind="budget",
            title=f"{b['category']} averages ${over:,.0f} over budget",
            summary=f"${avg:,.0f}/mo against a ${limit:,.0f} budget.",
            detail=(
                f"{b['category']} has averaged ${avg:,.2f}/mo over the last {n} "
                f"complete months against your ${limit:,.2f} budget — ${over:,.2f} "
                f"over, every month. Either the spending needs to come down or the "
                f"budget was set below what this category actually costs you; both "
                f"are fine, but the current pair cannot both be true."
            ),
            monthly_savings=over,
            effort=EFFORT_MODERATE,
            category=b["category"],
            basis=f"{n}-month average spend minus your budget.",
            evidence=[{"label": f"{n}-month average", "amount": round(avg, 2)},
                      {"label": "Budget", "amount": limit}],
        ))
    return out


def _merchant_concentration() -> list[dict]:
    start, end, n = _trailing_complete_months(3)
    total = db.query_one(
        f"SELECT COALESCE(-SUM(t.amount), 0) AS v FROM transactions t "
        f"WHERE {analytics.SPEND_WHERE} AND t.date BETWEEN ? AND ? "
        f"  AND t.category NOT IN ('Housing', 'Taxes')",
        (start, end),
    )["v"] or 0.0
    if total < 500:
        return []
    top = db.query(
        f"SELECT MAX(t.merchant) AS merchant, MAX(t.category) AS category, "
        f"       -SUM(t.amount) AS spend, COUNT(*) AS n FROM transactions t "
        f"WHERE {analytics.SPEND_WHERE} AND t.date BETWEEN ? AND ? "
        f"  AND t.category NOT IN ('Housing', 'Taxes') "
        f"GROUP BY t.merchant_key ORDER BY spend DESC LIMIT 1",
        (start, end),
    )
    if not top:
        return []
    m = top[0]
    share = m["spend"] / total * 100
    if share < 12 or m["spend"] / n < 100:
        return []
    return [_insight(
        id="merchant_concentration",
        kind="review",
        title=f"{m['merchant']} is {share:,.0f}% of your discretionary spend",
        summary=f"${m['spend'] / n:,.0f}/mo across {m['n']} charges.",
        detail=(
            f"{m['merchant']} accounts for ${m['spend']:,.2f} of ${total:,.2f} in "
            f"discretionary spending over {n} months — {share:,.0f}% of it, across "
            f"{m['n']} separate charges. A single merchant at this share is worth "
            f"reviewing line by line; a 20% reduction here is worth more than "
            f"eliminating most categories entirely."
        ),
        monthly_savings=(m["spend"] / n) * 0.20,
        effort=EFFORT_MODERATE,
        category=m["category"] or "Shopping",
        basis="20% reduction at the single largest discretionary merchant.",
        evidence=[{"label": m["merchant"], "amount": round(m["spend"], 2), "count": m["n"]}],
    )]


GENERATORS_NO_ARGS = [
    _fees_and_interest,
    _idle_cash,
    _delivery_premium,
    _small_purchase_leakage,
    _dining_vs_groceries,
    _categories_above_baseline,
    _budget_overages,
    _merchant_concentration,
]


def generate() -> dict:
    """Every insight, ranked by annual savings."""
    series = recurring.list_series()
    found: list[dict] = []
    for gen in GENERATORS_NO_ARGS:
        try:
            found.extend(gen())
        except Exception as e:  # one bad generator must not blank the tab
            print(f"[insights] {gen.__name__} failed: {type(e).__name__}: {e}")
    for gen in (_subscription_audit, _price_creep):
        try:
            found.extend(gen(series))
        except Exception as e:
            print(f"[insights] {gen.__name__} failed: {type(e).__name__}: {e}")

    found = [f for f in found if f["monthly_savings"] >= 2]
    found.sort(key=lambda f: -f["annual_savings"])

    monthly_total = round(sum(f["monthly_savings"] for f in found), 2)
    easy_total = round(
        sum(f["monthly_savings"] for f in found if f["effort"] == EFFORT_EASY), 2
    )

    # Several insights can target the same dollars — a Dining budget overage, a
    # delivery markup, and a small-purchase habit all describe one restaurant
    # bill from different angles. Summing them overstates what is actually
    # recoverable, so the conservative figure keeps only the largest finding per
    # category. The sum is still reported, but as a ceiling rather than a target.
    best_per_category: dict[str, float] = {}
    for f in found:
        cat = f["category"]
        best_per_category[cat] = max(best_per_category.get(cat, 0.0), f["monthly_savings"])
    conservative = round(sum(best_per_category.values()), 2)

    return {
        "insights": found,
        "monthly_total": monthly_total,
        "annual_total": round(monthly_total * 12, 2),
        "conservative_monthly": conservative,
        "conservative_annual": round(conservative * 12, 2),
        "easy_monthly_total": easy_total,
        "easy_annual_total": round(easy_total * 12, 2),
        "overlap_note": (
            "Items in the same category often describe the same spending from "
            "different angles, so the totals differ: the conservative figure counts "
            "only the largest finding per category, and the full total is the ceiling "
            "if every item were acted on independently."
        ),
        "count": len(found),
        "generated_for": date.today().isoformat(),
    }
