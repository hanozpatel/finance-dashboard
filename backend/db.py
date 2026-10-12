"""SQLite store for every account, transaction, holding, and goal.

Single-user by design: one file on your machine, no network listener beyond
localhost. That is the whole privacy model, and it is why provider access
tokens are encrypted at rest (see services/crypto_service.py) rather than
trusted to file permissions alone.

Two conventions the rest of the codebase depends on:

1. ``transactions.amount`` is **negative for money leaving you** and positive
   for money arriving, on every account type. Card purchases are negative even
   though they *increase* a balance owed, because for spend analysis the only
   question that matters is which direction the money went.

2. ``accounts.balance_current`` is **signed by net worth contribution**:
   assets positive, liabilities negative. A Chase card with $1,840 owed is
   stored as -1840.00, so net worth is a plain SUM with no type switch.

Normalising both at the ingestion boundary (services/sync_service.py) keeps
every downstream query free of provider-specific sign handling.
"""

import os
import sqlite3
import threading
from contextlib import contextmanager

DB_PATH = os.getenv("FINANCE_DB_PATH", os.path.join(os.path.dirname(__file__), "finance.db"))

_local = threading.local()
# Every connection handed out, so the store can be repointed at a different
# file without leaking handles to the old one. Only tests do that.
_all_connections: list[sqlite3.Connection] = []
_registry_lock = threading.Lock()

SCHEMA = """
-- A linked provider login. One row per Plaid item; an item can expose several
-- accounts (BofA checking + savings). Products are fixed when the item is
-- created and cannot be widened later, so they are recorded here: syncing reads
-- them to know whether this item answers transactions, holdings, or both.
CREATE TABLE IF NOT EXISTS connections (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    provider          TEXT NOT NULL,              -- plaid | manual
    institution       TEXT,
    provider_ref      TEXT,                       -- Plaid item_id
    products          TEXT,                       -- comma-separated: transactions,investments
    access_token_enc  TEXT,                       -- AES-256-GCM, never plaintext
    sync_cursor       TEXT,                       -- Plaid /transactions/sync position
    status            TEXT NOT NULL DEFAULT 'active',  -- active | error | disconnected
    error             TEXT,
    last_synced       TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (provider, provider_ref)
);

CREATE TABLE IF NOT EXISTS accounts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    connection_id       INTEGER REFERENCES connections(id) ON DELETE SET NULL,
    provider            TEXT NOT NULL,            -- plaid | csv | manual
    provider_account_id TEXT,
    institution         TEXT NOT NULL,
    name                TEXT NOT NULL,
    mask                TEXT,
    type                TEXT NOT NULL,            -- depository | credit | investment
    subtype             TEXT,                     -- checking | savings | credit_card | brokerage
    currency            TEXT NOT NULL DEFAULT 'USD',
    balance_current     REAL NOT NULL DEFAULT 0,  -- signed: asset +, liability -
    balance_available   REAL,
    credit_limit        REAL,
    apy                 REAL,                     -- for savings; drives goal projections
    account_number      TEXT,                     -- manual accounts only, for your own reference
    notes               TEXT,
    is_active           INTEGER NOT NULL DEFAULT 1,
    last_synced         TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (provider, provider_account_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    provider_txn_id TEXT,
    date            TEXT NOT NULL,                -- ISO yyyy-mm-dd, the posting date
    amount          REAL NOT NULL,                -- signed: outflow -, inflow +
    description     TEXT NOT NULL,
    merchant        TEXT,                         -- cleaned counterparty name
    merchant_key    TEXT,                         -- normalised, for grouping
    raw_category    TEXT,                         -- whatever the provider said
    category        TEXT NOT NULL DEFAULT 'Uncategorized',
    subcategory     TEXT,
    is_transfer     INTEGER NOT NULL DEFAULT 0,   -- card payments, internal moves
    pending         INTEGER NOT NULL DEFAULT 0,
    excluded        INTEGER NOT NULL DEFAULT 0,   -- user said "ignore in spend analysis"
    recurring_id    INTEGER REFERENCES recurring_series(id) ON DELETE SET NULL,
    notes           TEXT,
    source          TEXT NOT NULL DEFAULT 'sync', -- sync | csv | manual
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (account_id, provider_txn_id)
);

CREATE INDEX IF NOT EXISTS idx_txn_date     ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_txn_account  ON transactions(account_id, date);
CREATE INDEX IF NOT EXISTS idx_txn_category ON transactions(category, date);
CREATE INDEX IF NOT EXISTS idx_txn_merchant ON transactions(merchant_key);

-- A detected subscription / bill. Rebuilt by services/recurring.py, but
-- persisted so the UI can attach user decisions (cancelled, keep) to it.
CREATE TABLE IF NOT EXISTS recurring_series (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_key   TEXT NOT NULL UNIQUE,
    display_name   TEXT NOT NULL,
    category       TEXT,
    cadence        TEXT NOT NULL,                 -- weekly | biweekly | monthly | quarterly | annual
    interval_days  REAL NOT NULL,
    amount_median  REAL NOT NULL,                 -- positive magnitude
    amount_min     REAL NOT NULL,
    amount_max     REAL NOT NULL,
    monthly_cost   REAL NOT NULL,                 -- cadence-normalised
    occurrences    INTEGER NOT NULL,
    first_date     TEXT NOT NULL,
    last_date      TEXT NOT NULL,
    next_expected  TEXT,
    confidence     REAL NOT NULL DEFAULT 0,
    is_active      INTEGER NOT NULL DEFAULT 1,    -- stopped appearing => 0
    user_status    TEXT NOT NULL DEFAULT 'none',  -- none | keep | review | cancelled
    price_increase REAL,                          -- latest amount vs earliest, as a ratio
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- User-defined categorisation, consulted before any provider hint.
CREATE TABLE IF NOT EXISTS category_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    priority    INTEGER NOT NULL DEFAULT 100,
    match_type  TEXT NOT NULL,                    -- merchant_contains | description_contains | description_regex
    pattern     TEXT NOT NULL,
    category    TEXT NOT NULL,
    subcategory TEXT,
    is_transfer INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS holdings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    symbol      TEXT,
    name        TEXT NOT NULL,
    security_type TEXT,                           -- equity | etf | crypto | cash | option
    quantity    REAL NOT NULL,
    price       REAL NOT NULL,
    value       REAL NOT NULL,
    cost_basis  REAL,                             -- total, not per share
    as_of       TEXT NOT NULL,
    UNIQUE (account_id, symbol, name)
);

CREATE TABLE IF NOT EXISTS balance_snapshots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    date       TEXT NOT NULL,
    balance    REAL NOT NULL,
    UNIQUE (account_id, date)
);

CREATE TABLE IF NOT EXISTS budgets (
    category      TEXT PRIMARY KEY,
    monthly_limit REAL NOT NULL
);

-- Single-row table (id = 1) holding every house-purchase assumption.
CREATE TABLE IF NOT EXISTS house_goal (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),
    target_price         REAL NOT NULL DEFAULT 650000,
    down_payment_pct     REAL NOT NULL DEFAULT 20,
    saved_amount         REAL NOT NULL DEFAULT 0,
    monthly_contribution REAL NOT NULL DEFAULT 2500,
    savings_apy          REAL NOT NULL DEFAULT 4.0,
    target_date          TEXT,
    interest_rate        REAL NOT NULL DEFAULT 6.5,
    loan_term_years      INTEGER NOT NULL DEFAULT 30,
    property_tax_rate    REAL NOT NULL DEFAULT 1.1,
    insurance_annual     REAL NOT NULL DEFAULT 1800,
    hoa_monthly          REAL NOT NULL DEFAULT 0,
    pmi_rate             REAL NOT NULL DEFAULT 0.55,
    closing_cost_pct     REAL NOT NULL DEFAULT 3.0,
    gross_annual_income  REAL NOT NULL DEFAULT 180000,
    monthly_debts        REAL NOT NULL DEFAULT 450,
    credit_score         INTEGER NOT NULL DEFAULT 760,
    current_rent         REAL NOT NULL DEFAULT 3200,
    home_appreciation    REAL NOT NULL DEFAULT 3.5,
    investment_return    REAL NOT NULL DEFAULT 7.0,
    rent_inflation       REAL NOT NULL DEFAULT 3.0,
    marginal_tax_rate    REAL NOT NULL DEFAULT 32,
    -- Two-letter state code. Drives property tax, insurance, and closing-cost
    -- defaults, which vary more between states than any other assumption here.
    state                TEXT,
    loan_type            TEXT NOT NULL DEFAULT 'conventional',
    -- Baseline conforming limit; above it the loan is a jumbo. County-specific
    -- in high-cost areas, so it is editable rather than derived.
    conforming_limit     REAL NOT NULL DEFAULT 806500,
    va_first_use         INTEGER NOT NULL DEFAULT 1,
    -- Which accounts count toward the down payment, as a JSON array of ids.
    funding_account_ids  TEXT NOT NULL DEFAULT '[]',
    updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    """One connection per thread. FastAPI's threadpool reuses threads, so this
    amortises to a handful of connections rather than one per request."""
    conn = getattr(_local, "conn", None)
    path = getattr(_local, "path", None)
    # A repoint invalidates any connection opened against the previous file.
    if conn is not None and path != DB_PATH:
        try:
            conn.close()
        except sqlite3.Error:
            pass
        conn = None
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        _local.conn = conn
        _local.path = DB_PATH
        with _registry_lock:
            _all_connections.append(conn)
    return conn


def use_database(path: str) -> None:
    """Repoint the store at a different file, closing what is already open.

    Test support only. The module-level DB_PATH is read from the environment at
    import time, which makes two test modules that each want their own database
    silently share whichever imported first — this is the escape hatch.
    """
    global DB_PATH
    with _registry_lock:
        for conn in _all_connections:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        _all_connections.clear()
    if hasattr(_local, "conn"):
        del _local.conn
    if hasattr(_local, "path"):
        del _local.path
    DB_PATH = path


@contextmanager
def tx():
    """Transaction scope. Commits on clean exit, rolls back on exception."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def query(sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in connect().execute(sql, params).fetchall()]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    row = connect().execute(sql, params).fetchone()
    return dict(row) if row else None


def execute(sql: str, params: tuple = ()) -> int:
    with tx() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid


# Columns added after the first release. ``CREATE TABLE IF NOT EXISTS`` does
# nothing to a table that already exists, so a database created before a column
# was introduced would never gain it — every one of these has to be applied
# explicitly. Adding a column here is idempotent: it is skipped when present.
MIGRATIONS: list[tuple[str, str, str]] = [
    # (table, column, full ALTER statement)
    ("house_goal", "state",
     "ALTER TABLE house_goal ADD COLUMN state TEXT"),
    ("house_goal", "loan_type",
     "ALTER TABLE house_goal ADD COLUMN loan_type TEXT NOT NULL DEFAULT 'conventional'"),
    ("house_goal", "conforming_limit",
     "ALTER TABLE house_goal ADD COLUMN conforming_limit REAL NOT NULL DEFAULT 806500"),
    ("house_goal", "va_first_use",
     "ALTER TABLE house_goal ADD COLUMN va_first_use INTEGER NOT NULL DEFAULT 1"),
    ("accounts", "account_number",
     "ALTER TABLE accounts ADD COLUMN account_number TEXT"),
    ("accounts", "notes",
     "ALTER TABLE accounts ADD COLUMN notes TEXT"),
    ("connections", "products",
     "ALTER TABLE connections ADD COLUMN products TEXT"),
    ("connections", "sync_cursor",
     "ALTER TABLE connections ADD COLUMN sync_cursor TEXT"),
]


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _migrate(conn: sqlite3.Connection) -> list[str]:
    applied = []
    for table, column, statement in MIGRATIONS:
        existing = _columns(conn, table)
        if not existing or column in existing:
            continue
        conn.execute(statement)
        applied.append(f"{table}.{column}")
    if applied:
        conn.commit()
    return applied


def _retire_teller(conn: sqlite3.Connection) -> int:
    """Teller withdrew its API in July 2026, so those connections cannot sync.

    The stored tokens are dead credentials pointing at a service that no longer
    answers, so they are destroyed. The accounts and their history are kept and
    handed back to manual entry, which is what disconnecting any provider does —
    losing months of real transactions to a vendor's shutdown would be worse
    than a stale balance.
    """
    rows = conn.execute(
        "SELECT id FROM connections WHERE provider = 'teller' AND status != 'disconnected'"
    ).fetchall()
    if not rows:
        return 0
    ids = [r["id"] for r in rows]
    placeholders = ",".join("?" * len(ids))
    conn.execute(
        f"UPDATE accounts SET connection_id = NULL, provider = 'manual' "
        f"WHERE connection_id IN ({placeholders})", tuple(ids)
    )
    conn.execute(
        f"UPDATE connections SET status = 'disconnected', access_token_enc = NULL, "
        f"error = 'Teller shut down its API in July 2026. Re-link this institution "
        f"with Plaid.' WHERE id IN ({placeholders})", tuple(ids)
    )
    conn.commit()
    return len(ids)


def init_db() -> None:
    conn = connect()
    conn.executescript(SCHEMA)
    applied = _migrate(conn)
    if applied:
        print(f"[db] added column(s): {', '.join(applied)}")
    retired = _retire_teller(conn)
    if retired:
        print(f"[db] retired {retired} Teller connection(s); their accounts are now manual.")
    # The goal row must exist before the House tab can read it.
    conn.execute("INSERT OR IGNORE INTO house_goal (id) VALUES (1)")
    conn.commit()


def get_setting(key: str) -> str | None:
    row = query_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
