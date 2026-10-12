"""Finance Dashboard API.

Single-user and local by design. It binds to localhost, has no authentication,
and keeps everything in one SQLite file — which is the right trade for an app
holding a complete record of someone's finances, provided it never becomes
reachable from anywhere else. The CORS policy below enforces that rather than
assuming it.
"""

import os

from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import db
from routers import (
    accounts, analytics, budget, connections, goals, imports, investments, transactions,
)
from services import crypto_service

def _first_run_seed() -> None:
    """Seed demo data once, on a genuinely empty database.

    An empty dashboard is a poor first impression and gives no way to judge the
    layout before spending an hour on provider signup. It runs only when the
    `initialized` marker has never been set, so clearing the demo data and
    restarting does not bring it back — which would be maddening.
    """
    if db.get_setting("initialized"):
        return
    counts = db.query_one(
        "SELECT (SELECT COUNT(*) FROM accounts) AS a, "
        "       (SELECT COUNT(*) FROM transactions) AS t"
    )
    db.set_setting("initialized", "1")
    if counts["a"] or counts["t"]:
        return
    try:
        from services import seed
        seed.generate()
        db.set_setting("is_demo", "1")
        print("[startup] Seeded demo data. Clear it from the Accounts tab whenever you like.")
    except Exception as e:
        print(f"[startup] could not seed demo data: {type(e).__name__}: {e}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    _first_run_seed()
    if crypto_service.key_is_ephemeral():
        print(
            "[startup] FINANCE_MASTER_KEY is not set. Provider access tokens will be "
            "encrypted with a key stored in the database, which a copied database "
            "file can decrypt. Generate one with:\n"
            "          python3 -c \"import os,base64;print(base64.b64encode(os.urandom(32)).decode())\""
        )
    yield


app = FastAPI(title="Finance Dashboard API", version="1.0.0", lifespan=lifespan)

# Only the local dev server and a locally-served build. There is no deployment
# story here on purpose: this data should not leave the machine.
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://localhost",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(transactions.rules_router)
app.include_router(transactions.budgets_router)
app.include_router(budget.router)
app.include_router(analytics.router)
app.include_router(analytics.recurring_router)
app.include_router(analytics.insights_router)
app.include_router(goals.router)
app.include_router(investments.router)
app.include_router(connections.router)
app.include_router(imports.router)


@app.get("/api/health")
def health():
    counts = db.query_one(
        "SELECT (SELECT COUNT(*) FROM accounts WHERE is_active = 1) AS accounts,"
        "       (SELECT COUNT(*) FROM transactions) AS transactions,"
        "       (SELECT COUNT(*) FROM connections WHERE status = 'active') AS connections,"
        "       (SELECT MAX(date) FROM transactions) AS latest_transaction"
    )
    return {
        "status": "ok",
        "database": os.path.basename(db.DB_PATH),
        **counts,
        "master_key_from_environment": not crypto_service.key_is_ephemeral(),
        "is_demo": db.get_setting("is_demo") == "1",
    }


@app.post("/api/seed")
def seed_demo_data(confirm: bool = False):
    """Replace all data with the demo dataset.

    Gated behind ``confirm`` because it deletes every account and transaction,
    and an accidental call against real synced data would be unrecoverable.
    """
    from fastapi import HTTPException
    if not confirm:
        existing = db.query_one(
            "SELECT COUNT(*) AS n FROM accounts "
            "WHERE provider_account_id NOT LIKE 'seed-%' OR provider_account_id IS NULL"
        )["n"]
        raise HTTPException(
            400,
            "This is a full reset: every account, transaction, and connection is "
            "deleted and replaced with demo data."
            + (f" That includes {existing} account(s) you created or linked yourself."
               if existing else "")
            + " To remove only the demo data and keep your own, use /api/demo/clear."
            " Call again with ?confirm=true to reset.",
        )
    from services import seed
    result = seed.reseed()
    db.set_setting("is_demo", "1")
    return result


@app.post("/api/demo/clear")
def clear_demo_data(confirm: bool = False):
    """Remove the demo dataset, keeping anything you created yourself.

    Only accounts the seeder made are deleted. An earlier version wiped every
    account, which meant adding a real account and *then* clearing the demo data
    silently destroyed the real one — the exact order someone naturally does it
    in. Seeded accounts are identifiable by their provider_account_id prefix.
    """
    from fastapi import HTTPException
    if not confirm:
        raise HTTPException(
            400,
            "This deletes the demo accounts and their transactions. Accounts you "
            "created or linked yourself are kept. Call again with ?confirm=true.",
        )

    seeded = db.query(
        "SELECT id, name FROM accounts WHERE provider_account_id LIKE 'seed-%'"
    )
    kept = db.query(
        "SELECT id, name FROM accounts WHERE provider_account_id NOT LIKE 'seed-%'"
        " OR provider_account_id IS NULL"
    )
    removed_txns = 0
    if seeded:
        ids = tuple(a["id"] for a in seeded)
        placeholders = ",".join("?" * len(ids))
        removed_txns = db.query_one(
            f"SELECT COUNT(*) AS n FROM transactions WHERE account_id IN ({placeholders})",
            ids,
        )["n"]
        with db.tx() as conn:
            # Transactions, holdings, and snapshots cascade from the account.
            conn.execute(f"DELETE FROM accounts WHERE id IN ({placeholders})", ids)
            # Seeded budgets would otherwise generate over-budget findings
            # against real data that never had those limits set.
            conn.execute("DELETE FROM budgets")

    from services import recurring
    recurring.refresh()

    # A residence the seeder chose is not one you chose. Drop it, so the
    # Budget tab asks rather than quietly comparing you against California.
    if db.get_setting("residence_seeded") == "1":
        db.execute(
            "DELETE FROM settings WHERE key IN "
            "('residence_state', 'household_size', 'residence_seeded')"
        )

    db.set_setting("is_demo", "0")
    # The marker stays set, so a restart does not re-seed what was just cleared.
    db.set_setting("initialized", "1")
    return {
        "cleared": True,
        "accounts_removed": len(seeded),
        "transactions_removed": removed_txns,
        "accounts_kept": [a["name"] for a in kept],
    }
