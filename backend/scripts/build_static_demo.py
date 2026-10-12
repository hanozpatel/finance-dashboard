"""Snapshot the demo dataset for the static, read-only preview on GitHub Pages.

    python scripts/build_static_demo.py [output.json]

The preview has no server, so every response the UI can ask for is computed
here, ahead of time, against a freshly seeded throwaway database. The browser
then answers requests from this file (see ``frontend/src/lib/demo.ts``).

That only works because the UI's choices are finite: four spending periods,
sixteen house-plan combinations, a bounded run of budget months. The one
open-ended view — searching and filtering transactions — gets the full ledger
instead, and is filtered in the browser by a mirror of the backend's query.

Isolation matters more than it looks. The script must never read a developer's
real database or their provider keys, so it points the store at a temp file and
blanks every credential *before* the app is imported: ``load_dotenv`` never
overrides a variable that is already set, so a real ``backend/.env`` sitting
next to this script cannot leak into the snapshot.

The GitHub Action re-runs this daily. Seeded data is relative to today, so a
daily rebuild keeps the preview's "this month" lined up with the visitor's.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent

# --- isolation: before anything from the app is imported -------------------
os.environ["FINANCE_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="finance-static-"), "demo.db")
os.environ["FINANCE_MASTER_KEY"] = base64.b64encode(os.urandom(32)).decode()
for var in ("PLAID_CLIENT_ID", "PLAID_SECRET", "SNAPTRADE_CLIENT_ID",
            "SNAPTRADE_CONSUMER_KEY", "SNAPTRADE_MODE"):
    os.environ[var] = ""
os.environ["PLAID_ENV"] = "sandbox"
sys.path.insert(0, str(BACKEND))

import db  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from services import seed  # noqa: E402
from services.analytics import add_months  # noqa: E402

SPENDING_PERIODS = (1, 3, 6, 12)
HOUSE_HORIZONS = (5, 7, 10, 15)
HOUSE_EXTRAS = (0, 250, 500, 1000)
BUDGET_MONTHS_BACK = 18


def _key(path: str, params: dict | None = None) -> str:
    """Path plus sorted query — the same normalisation the browser applies."""
    if not params:
        return path
    query = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return f"{path}?{query}"


def build() -> dict:
    db.init_db()
    seed.reseed()
    db.set_setting("initialized", "1")
    db.set_setting("is_demo", "1")

    from main import app

    responses: dict[str, object] = {}
    with TestClient(app) as client:
        def grab(path: str, params: dict | None = None) -> object:
            r = client.get(path, params=params)
            if r.status_code != 200:
                raise SystemExit(f"GET {_key(path, params)} -> {r.status_code}: {r.text[:200]}")
            body = r.json()
            responses[_key(path, params)] = body
            return body

        for path in (
            "/api/health", "/api/accounts", "/api/transactions/review",
            "/api/transactions/review/stats", "/api/transactions/categories",
            "/api/rules", "/api/budget/settings", "/api/budgets", "/api/insights",
            "/api/goals/states", "/api/investments", "/api/connections",
            "/api/connections/providers", "/api/imports/presets", "/api/goals/house",
            "/api/budget/overview",
        ):
            grab(path)

        grab("/api/analytics/overview", {"months": 12})
        for months in SPENDING_PERIODS:
            grab("/api/analytics/spending", {"months": months})
        for h in HOUSE_HORIZONS:
            for e in HOUSE_EXTRAS:
                grab("/api/goals/house", {"horizon_years": h, "extra_monthly": e})

        this_month = date.today().replace(day=1)
        for back in range(BUDGET_MONTHS_BACK):
            grab("/api/budget/overview", {"month": add_months(this_month, -back).strftime("%Y-%m")})

        recurring = grab("/api/recurring")
        for series in recurring.get("series", []):
            grab(f"/api/recurring/{series['id']}/transactions")

        # The whole ledger, transfers included, for in-browser filtering.
        ledger: list[dict] = []
        offset = 0
        while True:
            page = client.get("/api/transactions", params={
                "include_transfers": "true", "limit": 1000, "offset": offset,
                "sort": "date", "direction": "desc",
            }).json()
            ledger.extend(page["transactions"])
            if not page["has_more"]:
                break
            offset += 1000

    return {
        "generated": date.today().isoformat(),
        "responses": responses,
        "transactions": ledger,
    }


def main() -> None:
    default = BACKEND.parent / "frontend" / "public" / "demo" / "snapshot.json"
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    out.parent.mkdir(parents=True, exist_ok=True)
    snapshot = build()
    out.write_text(json.dumps(snapshot, separators=(",", ":")))
    print(f"Wrote {len(snapshot['responses'])} responses and "
          f"{len(snapshot['transactions'])} transactions to {out} "
          f"({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
