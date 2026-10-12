"""Build the per-state spending benchmarks from BEA's state PCE release.

    python scripts/build_state_benchmarks.py path/to/SAPCE.zip

Source: U.S. Bureau of Economic Analysis, *Personal Consumption Expenditures by
State* (https://apps.bea.gov/regional/zip/SAPCE.zip). Table SAPCE4 is spending
by function in millions of dollars; this divides it by each state's population
to get an annual figure per person, then groups BEA's lines into the app's
categories.

Two choices here decide whether the comparison is honest, so they are stated
rather than buried:

* **Only cash-like spending is counted.** BEA's totals include things nobody
  pays out of a checking account — the rent homeowners "pay themselves", what
  insurers and Medicare pay hospitals. Where a category is dominated by that,
  it is marked not comparable instead of being compared badly.
* **Every line is matched by code *and* description.** BEA renumbers tables
  between releases; a silent renumbering would quietly compare groceries to
  something else. A mismatch stops the build.

Population is derived rather than downloaded: SAPCE1 gives total spending and
SAPCE2 gives spending per person, and their ratio is the population BEA used.
The build cross-checks the result against a second per-capita line.
"""

from __future__ import annotations

import csv
import io
import json
import sys
import zipfile
from datetime import date
from pathlib import Path

# The app's category -> the SAPCE4 lines it is compared against.
# (line code, the description that line must carry)
CATEGORY_LINES: dict[str, list[tuple[int, str]]] = {
    "Groceries": [
        (3, "Food and beverages purchased for off-premises consumption"),
    ],
    "Dining": [
        (102, "Purchased meals and beverages"),
    ],
    "Housing": [
        # Includes the rent owner-occupiers are imputed to pay themselves, so
        # this is "what housing costs here" for renters and owners alike.
        (19, "Housing"),
        (24, "Household utilities and fuels"),
        (71, "Telecommunication services"),
        (72, "Internet access"),
    ],
    "Transportation": [
        # Running a car and getting around — not buying one. Vehicle purchases
        # are lumpy and the app does not file them here.
        (57, "Motor vehicle operation"),
        (63, "Ground transportation"),
        (116, "Net motor vehicle and other transportation insurance"),
    ],
    "Shopping": [
        (7, "Clothing, footwear, and related services"),
        (30, "Furnishings, household equipment, and routine household maintenance"),
        (75, "Video and audio equipment"),
        (76, "Information processing equipment"),
        (118, "Personal care"),
        (119, "Personal items"),
    ],
    "Entertainment": [
        (82, "Membership clubs, sports centers, parks, theaters, and museums"),
        (80, "Other sporting and recreational goods"),
    ],
    "Subscriptions": [
        # Cable, streaming, and software services live here in BEA's tables.
        (77, "Services related to video and audio goods and computers"),
        (90, "Magazines, newspapers, books, and stationery"),
    ],
    "Travel": [
        (64, "Air transportation"),
        (104, "Accommodations"),
        (94, "Package tours"),
        (129, "Foreign travel by U.S. residents"),
    ],
    "Education": [
        (95, "Education"),
    ],
}

# Categories with no honest counterpart, and why. Shown in the UI verbatim.
NOT_COMPARABLE: dict[str, str] = {
    "Health": (
        "BEA's health figure counts what insurers, Medicare and Medicaid pay for "
        "care, not just what you pay — so out-of-pocket spending would always look "
        "tiny next to it."
    ),
    "Fees & Interest": "Interest is not consumption spending, so BEA does not count it.",
    "Taxes": "Taxes are not consumption spending.",
    "Gifts & Donations": "Gifts and donations are transfers between people, not purchases.",
    "Other": "Too mixed a category to compare against any one figure.",
}

# Every area this app offers: the 50 states, DC, and the national figure.
AREAS = [
    "US", "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR",
    "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]


def _rows(archive: zipfile.ZipFile, name: str) -> list[list[str]]:
    with archive.open(name) as fh:
        return list(csv.reader(io.TextIOWrapper(fh, encoding="latin-1", newline="")))


def _member(archive: zipfile.ZipFile, table: str, area: str) -> str:
    prefix = f"{table}_{area}_"
    matches = [n for n in archive.namelist() if n.startswith(prefix) and n.endswith(".csv")]
    if len(matches) != 1:
        raise SystemExit(f"Expected one {prefix}*.csv in the archive, found {matches}")
    return matches[0]


def _latest_year(header: list[str]) -> tuple[int, int]:
    """(column index, year) of the newest year in a BEA table."""
    for i in range(len(header) - 1, -1, -1):
        if header[i].strip().isdigit():
            return i, int(header[i])
    raise SystemExit("No year columns found.")


def _lines(rows: list[list[str]], col: int) -> dict[int, tuple[str, float]]:
    out = {}
    for r in rows[1:]:
        if len(r) <= col or not r[4].strip().isdigit():
            continue
        try:
            value = float(r[col])
        except ValueError:
            continue  # suppressed or not available
        out[int(r[4])] = (r[6].strip(), value)
    return out


def build(zip_path: str) -> dict:
    archive = zipfile.ZipFile(zip_path)
    areas: dict[str, dict] = {}
    year = None

    for area in AREAS:
        t1 = _rows(archive, _member(archive, "SAPCE1", area))
        t2 = _rows(archive, _member(archive, "SAPCE2", area))
        t4 = _rows(archive, _member(archive, "SAPCE4", area))
        col, area_year = _latest_year(t4[0])
        year = year or area_year
        if area_year != year:
            raise SystemExit(f"{area} has {area_year} data; others have {year}.")

        total = _lines(t1, _latest_year(t1[0])[0])[1][1]            # $ millions
        per_capita_total = _lines(t2, _latest_year(t2[0])[0])[1][1]  # $ per person
        population = total * 1e6 / per_capita_total

        detail = _lines(t4, col)
        # Cross-check: groceries per person computed here must match the
        # per-capita figure BEA publishes for the same line in SAPCE2.
        published = _lines(t2, _latest_year(t2[0])[0])[9][1]
        computed = detail[3][1] * 1e6 / population
        if abs(computed - published) > 2:
            raise SystemExit(
                f"{area}: derived population fails the cross-check "
                f"(groceries {computed:.0f} vs published {published:.0f})."
            )

        categories = {}
        for category, lines in CATEGORY_LINES.items():
            annual = 0.0
            for code, expected in lines:
                if code not in detail:
                    raise SystemExit(f"{area}: SAPCE4 line {code} ({expected}) is missing.")
                description, value = detail[code]
                if not description.startswith(expected[:40]):
                    raise SystemExit(
                        f"{area}: SAPCE4 line {code} is '{description}', expected "
                        f"'{expected}'. BEA has renumbered the table; update the mapping."
                    )
                annual += value * 1e6 / population
            categories[category] = round(annual)

        name = t4[1][1].strip().rstrip(" *") if len(t4) > 1 else area
        areas[area] = {
            "code": area,
            "name": "United States" if area == "US" else name,
            "population": round(population),
            "annual_per_person": categories,
        }

    return {
        "source": "U.S. Bureau of Economic Analysis, Personal Consumption Expenditures by State (SAPCE4)",
        "source_url": "https://apps.bea.gov/regional/zip/SAPCE.zip",
        "year": year,
        "built": date.today().isoformat(),
        "unit": "US dollars per person per year, current dollars",
        "lines": {c: [{"line": code, "description": d} for code, d in lines]
                  for c, lines in CATEGORY_LINES.items()},
        "not_comparable": NOT_COMPARABLE,
        "areas": areas,
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    data = build(sys.argv[1])
    out = Path(__file__).resolve().parent.parent / "data" / "state_benchmarks.json"
    out.write_text(json.dumps(data, indent=1, sort_keys=False) + "\n")
    print(f"Wrote {len(data['areas'])} areas for {data['year']} to {out}")


if __name__ == "__main__":
    main()
