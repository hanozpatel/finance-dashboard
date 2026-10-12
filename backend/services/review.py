"""The uncategorised-transaction review queue — one question per merchant.

Automatic categorisation gets most of a real feed right and then stops dead at
the local restaurant, the ACH bill with a mangled company name, and the
acronym nobody outside the household would recognise. No keyword list reaches
those, and guessing at them silently is worse than asking: a wrong category is
harder to notice than a missing one.

So what cannot be inferred is asked, once per merchant rather than once per
transaction — answering "Saffron Lane is Dining" settles every visit, past and
future, because the answer becomes a rule.

Suggestions are ranked by how much they are actually worth trusting:

1. the same merchant, already categorised elsewhere in your own data
2. a merchant whose name overlaps this one — the ACH spelling of a shop you
   already answered for
3. a weak keyword, matched loosely inside mangled text
4. the shape of the transaction: an ACH bill, a monthly repeat, a deposit
5. what you categorise most often, so there is always something to click

Every suggestion carries the reason it was made, because a guess the user
cannot audit is a guess they should not accept.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

import db
from services import categorize

# Weak signals: matched as plain substrings rather than whole words, because
# the text they hide in is mangled ("SKYHOP AIRWAVESG5R", "THE GELATERIA").
# Too unreliable to categorise on their own, which is exactly why they are
# offered as a suggestion for a human to confirm instead.
WEAK_SIGNALS: list[tuple[str, tuple[str, str], str]] = [
    ("market", ("Groceries", "Supermarket"), "\"market\" usually means a grocery or corner store"),
    ("grocer", ("Groceries", "Supermarket"), "\"grocer\" in the name"),
    ("pita", ("Dining", "Restaurants"), "\"pita\" in the name"),
    ("kebab", ("Dining", "Restaurants"), "\"kebab\" in the name"),
    ("taco", ("Dining", "Restaurants"), "\"taco\" in the name"),
    ("chop", ("Dining", "Restaurants"), "\"chop\" in the name"),
    ("gelat", ("Dining", "Dessert"), "\"gelat\" suggests an ice cream shop"),
    ("bagel", ("Dining", "Bakery"), "\"bagel\" in the name"),
    ("juice", ("Dining", "Restaurants"), "\"juice\" in the name"),
    ("airwave", ("Travel", "Flights"), "looks like an airline name run together"),
    ("airlin", ("Travel", "Flights"), "\"airlin\" in the name"),
    ("hotel", ("Travel", "Lodging"), "\"hotel\" in the name"),
    ("insurance", ("Other", "Insurance"), "\"insurance\" in the name — which kind is up to you"),
    ("subscription", ("Subscriptions", "Other"), "the description says subscription"),
    ("fitness", ("Health", "Fitness"), "\"fitness\" in the name"),
    ("gym", ("Health", "Fitness"), "\"gym\" in the name"),
    ("crossfit", ("Health", "Fitness"), "\"crossfit\" in the name"),
    ("salon", ("Shopping", "Personal Care"), "\"salon\" in the name"),
    ("barber", ("Shopping", "Personal Care"), "\"barber\" in the name"),
    ("daycare", ("Other", "Childcare"), "\"daycare\" in the name"),
    ("church", ("Gifts & Donations", "Charity"), "\"church\" in the name"),
]

# Anchored to the start of a word, never mid-token: "pita" must match
# "PITA PLUS" and not CA-PITA-L ONE. The right-hand side stays open so a stem
# still matches the run-together text these signals exist for ("AIRWAVESG5R").
_WEAK_PATTERNS = [
    (re.compile(r"\b" + re.escape(needle)), value, reason)
    for needle, value, reason in WEAK_SIGNALS
]

# The ACH envelope every US bank wraps a bill payment in. Its presence says
# "this is a company billing you directly", which narrows the options a lot
# even when the company name inside it is unreadable.
_ACH_BILL = re.compile(r"\bDES:.*\bID:", re.I)

# Tokens too common to prove two merchant names refer to the same place.
_WEAK_TOKENS = {
    "des", "id", "indn", "co", "web", "pmts", "pmt", "online", "payment",
    "purchase", "the", "llc", "inc", "card", "authoriz", "authorized",
}


# Where the merchant name stops and the ACH envelope begins. Anything from
# here on is routing metadata and the account holder's own name.
_ENVELOPE_MARKERS = {"des", "indn", "id", "co", "pmts", "pmt", "web"}


def _tokens(merchant_key: str) -> set[str]:
    """Distinctive words in a merchant key, for comparing two spellings.

    Stops at the ACH envelope: two unrelated debits both carry your name, and
    matching on it would suggest the pet-insurance category for a tuition bill.
    """
    out: set[str] = set()
    for token in re.split(r"[^a-z0-9]+", (merchant_key or "").lower()):
        if token in _ENVELOPE_MARKERS:
            break
        if len(token) >= 4 and token not in _WEAK_TOKENS and not token.isdigit():
            out.add(token)
    return out


def _categorised_merchants() -> list[dict]:
    """Every merchant the user has already settled, with its category."""
    return db.query(
        "SELECT merchant_key, merchant, category, subcategory, COUNT(*) AS n "
        "FROM transactions "
        "WHERE category != 'Uncategorized' AND merchant_key IS NOT NULL "
        "GROUP BY merchant_key, category, subcategory "
        "ORDER BY n DESC"
    )


def _popular_categories(limit: int = 3) -> list[tuple[str, str | None]]:
    """Your most-used categories, one subcategory each.

    Distinct *categories*, not distinct pairs: the fallback exists to offer
    real alternatives, and "Dining · Coffee, Dining · Fast Food, Dining ·
    Delivery" is one guess wearing three hats.
    """
    rows = db.query(
        "SELECT category, subcategory, COUNT(*) AS n FROM transactions "
        "WHERE category NOT IN ('Uncategorized', 'Transfer', 'Income') "
        "GROUP BY category, subcategory ORDER BY n DESC"
    )
    out: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for r in rows:
        if r["category"] in seen:
            continue
        seen.add(r["category"])
        out.append((r["category"], r["subcategory"]))
        if len(out) == limit:
            break
    return out


def suggest(group: dict, history: list[dict] | None = None,
            popular: list[tuple[str, str | None]] | None = None) -> list[dict]:
    """Ranked guesses for one merchant, each with the reason it was offered."""
    history = _categorised_merchants() if history is None else history
    popular = _popular_categories() if popular is None else popular

    merchant_key = group["merchant_key"] or ""
    description = group["sample_description"]
    haystack = f"{merchant_key} {description}".lower()
    out: list[dict] = []
    seen: set[tuple[str, str | None]] = set()

    def add(category, subcategory, reason, confidence):
        if (category, subcategory) in seen:
            return
        seen.add((category, subcategory))
        out.append({"category": category, "subcategory": subcategory,
                    "reason": reason, "confidence": confidence})

    # 1. The same merchant key, already answered somewhere in the data.
    for row in history:
        if row["merchant_key"] == merchant_key:
            add(row["category"], row["subcategory"],
                f"you already categorise {row['merchant'] or merchant_key} this way",
                "high")

    # 2. A different spelling of a merchant already answered. This is what
    #    catches the ACH version of a shop you answered for on the card.
    mine = _tokens(merchant_key)
    if mine:
        scored = []
        for row in history:
            overlap = mine & _tokens(row["merchant_key"])
            if overlap:
                scored.append((len(overlap), row, sorted(overlap)))
        scored.sort(key=lambda x: (-x[0], -x[1]["n"]))
        for _score, row, overlap in scored[:2]:
            add(row["category"], row["subcategory"],
                f"shares \"{' '.join(overlap)}\" with {row['merchant'] or row['merchant_key']}, "
                f"which you categorise as {row['category']}",
                "medium")

    # 3. Weak keywords, matched loosely inside text the strict pass rejected.
    for pattern, (category, subcategory), reason in _WEAK_PATTERNS:
        if pattern.search(haystack):
            add(category, subcategory, reason, "medium")

    # 4. The shape of the transaction itself.
    if _ACH_BILL.search(description):
        add("Housing", "Utilities", "an ACH bill paid directly to a company", "low")
    if group["count"] >= 3 and len({round(abs(t["amount"]), 2) for t in group["examples"]}) == 1:
        add("Subscriptions", "Other",
            f"the same amount {group['count']} times — looks like a subscription", "medium")
    if group["total"] > 0:
        add("Income", "Other Income", "money coming in, not going out", "medium")

    # 5. Always leave something clickable, even with nothing to go on.
    for category, subcategory in popular:
        add(category, subcategory, "one of your most-used categories", "low")

    return out[:5]


def queue(limit: int = 60) -> dict:
    """Uncategorised transactions as questions, biggest money first.

    Ordering by amount rather than date is deliberate: answering the $1,491 ACH
    before the $2.14 coffee is what actually moves the spending picture.
    """
    rows = db.query(
        "SELECT t.id, t.description, t.merchant, t.merchant_key, t.amount, t.date,"
        "       t.raw_category, a.type AS account_type, a.institution, a.name AS account_name "
        "FROM transactions t JOIN accounts a ON a.id = t.account_id "
        "WHERE t.category = 'Uncategorized' AND t.excluded = 0 "
        "ORDER BY t.date DESC"
    )

    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[r["merchant_key"] or f"txn:{r['id']}"].append(dict(r))

    history = _categorised_merchants()
    popular = _popular_categories()

    questions = []
    for merchant_key, txns in grouped.items():
        group = {
            "merchant_key": merchant_key,
            "merchant": txns[0]["merchant"] or txns[0]["description"],
            "sample_description": txns[0]["description"],
            "count": len(txns),
            "total": round(sum(t["amount"] for t in txns), 2),
            "accounts": sorted({t["institution"] for t in txns}),
            "first_date": min(t["date"] for t in txns),
            "last_date": max(t["date"] for t in txns),
            "transaction_ids": [t["id"] for t in txns],
            "examples": [
                {"id": t["id"], "date": t["date"], "amount": t["amount"],
                 "description": t["description"], "account": t["institution"]}
                for t in sorted(txns, key=lambda t: abs(t["amount"]), reverse=True)[:4]
            ],
        }
        group["suggestions"] = suggest(group, history, popular)
        questions.append(group)

    # Biggest absolute money first; ties broken by how many transactions the
    # one answer would settle.
    questions.sort(key=lambda q: (-abs(q["total"]), -q["count"]))

    return {
        "questions": questions[:limit],
        "remaining": len(questions),
        "transactions": len(rows),
        "total_amount": round(sum(r["amount"] for r in rows), 2),
    }


def answer(*, merchant_key: str, category: str, subcategory: str | None,
           create_rule: bool = True, transaction_ids: list[int] | None = None) -> dict:
    """Apply one answer, and optionally never ask about this merchant again.

    The rule is what makes this worth doing: without it the same local
    restaurant comes back as a question every month.
    """
    if category not in categorize.ALL_CATEGORIES:
        raise ValueError(f"'{category}' is not a category this app knows.")

    is_transfer = category == "Transfer"
    if transaction_ids:
        placeholders = ",".join("?" * len(transaction_ids))
        rows = db.query(
            f"SELECT id FROM transactions WHERE id IN ({placeholders})",
            tuple(transaction_ids),
        )
        db.execute(
            f"UPDATE transactions SET category = ?, subcategory = ?, is_transfer = ? "
            f"WHERE id IN ({placeholders})",
            (category, subcategory, int(is_transfer)) + tuple(transaction_ids),
        )
    else:
        rows = db.query(
            "SELECT id FROM transactions WHERE merchant_key = ? AND category = 'Uncategorized'",
            (merchant_key,),
        )
        db.execute(
            "UPDATE transactions SET category = ?, subcategory = ?, is_transfer = ? "
            "WHERE merchant_key = ? AND category = 'Uncategorized'",
            (category, subcategory, int(is_transfer), merchant_key),
        )

    rule_created = None
    rule_skipped_reason = rule_refusal(merchant_key, category) if create_rule else None
    if create_rule and not rule_skipped_reason and merchant_key:
        existing = db.query_one(
            "SELECT id FROM category_rules WHERE match_type = 'merchant_contains' AND pattern = ?",
            (merchant_key,),
        )
        if existing:
            db.execute(
                "UPDATE category_rules SET category = ?, subcategory = ?, is_transfer = ? "
                "WHERE id = ?",
                (category, subcategory, int(is_transfer), existing["id"]),
            )
        else:
            db.execute(
                "INSERT INTO category_rules (match_type, pattern, category, subcategory,"
                " is_transfer, priority) VALUES ('merchant_contains', ?, ?, ?, ?, 50)",
                (merchant_key, category, subcategory, int(is_transfer)),
            )
        rule_created = merchant_key

    remaining = db.query_one(
        "SELECT COUNT(*) AS n FROM transactions WHERE category = 'Uncategorized' AND excluded = 0"
    )["n"]
    return {"updated": len(rows), "rule_created": rule_created,
            "rule_skipped_reason": rule_skipped_reason, "remaining": remaining}


# A merchant key has to be distinctive enough to be safe as a substring match.
# "ct" is not: it appears inside Victoria's Secret, Cheesecake Factory and
# Joint Chiropractic, and a rule built on it recategorised all of them.
MIN_RULE_KEY_LENGTH = 5


def rule_refusal(merchant_key: str, category: str) -> str | None:
    """Why a rule for this merchant would be unsafe, or None if it is fine.

    A rule matches the merchant name as a *substring*, which is what makes it
    useful — one answer covers "SAFFRON LANE" and "SAFFRON LANE - MAIN". The
    same property makes a short or common key dangerous, so the answer is still
    applied to the transactions in hand; only the standing rule is withheld.
    """
    if not merchant_key or merchant_key.startswith("txn:"):
        return "this is a single unnamed transaction, so there is no merchant to remember"
    if len(merchant_key.replace(" ", "")) < MIN_RULE_KEY_LENGTH:
        return (f"\"{merchant_key}\" is too short to match safely — it would catch "
                f"any merchant containing those letters")

    # The decisive test: does this key already appear inside merchants you
    # categorise differently? If so the rule would silently rewrite them.
    clash = db.query_one(
        "SELECT merchant, category FROM transactions "
        "WHERE merchant_key IS NOT NULL AND merchant_key != ? "
        "  AND instr(merchant_key, ?) > 0 "
        "  AND category NOT IN ('Uncategorized', ?) LIMIT 1",
        (merchant_key, merchant_key, category),
    )
    if clash:
        return (f"\"{merchant_key}\" also appears in {clash['merchant']}, which is "
                f"{clash['category']} — a rule would recategorise that too")
    return None


def stats() -> dict:
    """How much of the feed is still unanswered — drives the review prompt."""
    row = db.query_one(
        "SELECT COUNT(*) AS total,"
        "       SUM(CASE WHEN category = 'Uncategorized' THEN 1 ELSE 0 END) AS uncategorized,"
        "       SUM(CASE WHEN category = 'Uncategorized' THEN ABS(amount) ELSE 0 END) AS amount"
        " FROM transactions WHERE excluded = 0"
    )
    total = row["total"] or 0
    uncategorized = row["uncategorized"] or 0
    merchants = db.query_one(
        "SELECT COUNT(DISTINCT COALESCE(merchant_key, id)) AS n FROM transactions "
        "WHERE category = 'Uncategorized' AND excluded = 0"
    )["n"]
    return {
        "total": total,
        "uncategorized": uncategorized,
        "questions": merchants,
        "amount": round(row["amount"] or 0.0, 2),
        "coverage": round(100.0 * (total - uncategorized) / total, 1) if total else 100.0,
    }
