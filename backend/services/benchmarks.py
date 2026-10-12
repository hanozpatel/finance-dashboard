"""What households in your state spend, per category — the yardstick for budgets.

A budget on its own answers "am I spending what I planned?". It cannot answer
"is what I planned reasonable?", and that second question is the one people
actually have when they set a grocery budget for the first time. This module
supplies the outside reference: BEA's 2025 spending per person, by state,
grouped into this app's categories (see ``scripts/build_state_benchmarks.py``
for exactly which lines go where and why).

Two adjustments turn BEA's figure into something comparable with one month of
your own spending:

* **Annual → monthly**, by dividing by twelve. BEA publishes years.
* **Per person → per household**, by multiplying by household size. This is a
  simplification — two people do not buy twice the internet — and it is labelled
  as one, but it is far closer than comparing a couple's groceries against one
  person's, which would make every couple look extravagant.

The data is bundled as JSON rather than fetched, so the comparison works
offline and the numbers are reviewable in the repository.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import db

_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "state_benchmarks.json"

DEFAULT_AREA = "US"
DEFAULT_HOUSEHOLD = 1
MAX_HOUSEHOLD = 10


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(_DATA_FILE.read_text())


def metadata() -> dict:
    d = _data()
    return {
        "source": d["source"],
        "source_url": d["source_url"],
        "year": d["year"],
        "lines": d["lines"],
        "not_comparable": d["not_comparable"],
    }


def areas() -> list[dict]:
    """The national figure first, then states and DC alphabetically."""
    d = _data()["areas"]
    states = sorted((a for code, a in d.items() if code != "US"), key=lambda a: a["name"])
    return [{"code": "US", "name": "United States (national average)"}] + [
        {"code": a["code"], "name": a["name"]} for a in states
    ]


def area(code: str | None) -> dict:
    d = _data()["areas"]
    return d.get((code or "").upper()) or d[DEFAULT_AREA]


def comparable_categories() -> list[str]:
    return list(_data()["lines"])


def monthly(code: str | None, household_size: int) -> dict[str, float]:
    """Each comparable category's average monthly spend for a household here."""
    per_person = area(code)["annual_per_person"]
    return {c: round(v / 12 * household_size, 2) for c, v in per_person.items()}


# --------------------------------------------------------------------------
# The user's own settings
# --------------------------------------------------------------------------

def settings() -> dict:
    code = (db.get_setting("residence_state") or DEFAULT_AREA).upper()
    if code not in _data()["areas"]:
        code = DEFAULT_AREA
    try:
        household = int(db.get_setting("household_size") or DEFAULT_HOUSEHOLD)
    except ValueError:
        household = DEFAULT_HOUSEHOLD
    household = max(1, min(MAX_HOUSEHOLD, household))
    return {
        "state": code,
        "state_name": area(code)["name"],
        "household_size": household,
        # Whether the user has actually chosen, so the UI can ask rather than
        # silently comparing them against the national figure forever.
        "state_chosen": db.get_setting("residence_state") is not None,
    }


def save_settings(state: str | None = None, household_size: int | None = None) -> dict:
    if state is not None:
        code = state.strip().upper()
        if code not in _data()["areas"]:
            raise ValueError(f"'{state}' is not a state this app has figures for.")
        db.set_setting("residence_state", code)
    if household_size is not None:
        if not 1 <= household_size <= MAX_HOUSEHOLD:
            raise ValueError(f"Household size must be between 1 and {MAX_HOUSEHOLD}.")
        db.set_setting("household_size", str(household_size))
    # Your own choice now: clearing the demo data must not take it away.
    db.execute("DELETE FROM settings WHERE key = 'residence_seeded'")
    return settings()
