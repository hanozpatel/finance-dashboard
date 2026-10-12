"""Per-state defaults for the house plan.

Property tax is the reason this exists. It varies by more than a factor of
seven across the country — 0.29% in Hawaii against 2.23% in New Jersey — which
on an $800,000 house is a difference of about $1,300 *per month*. Carrying a
single national default silently makes the plan wrong for almost everyone.

Every figure here is a **starting estimate**, not a quote:

* Property tax rates are effective statewide averages. Your county and city
  levies are what actually apply, and in some states (Texas, Illinois, New York)
  the spread within the state is larger than the spread between states.
* Median prices and insurance premiums move constantly and vary enormously
  within a state; treat them as an order of magnitude.
* California's Proposition 13 assesses at purchase price and caps increases at
  2% a year, so its effective *statewide* rate understates what a new buyer
  pays. New buyers should expect closer to 1.1-1.25% of purchase price.

The UI labels all of this as an estimate and every value stays editable.
"""

from __future__ import annotations

# (code, name, effective property tax %, median home price, avg annual
#  homeowners insurance, typical buyer closing cost % of price, notes)
_ROWS: list[tuple[str, str, float, int, int, float, str]] = [
    ("AL", "Alabama",              0.40,  228_000, 2_200, 2.5, ""),
    ("AK", "Alaska",               1.07,  372_000, 1_400, 2.5, ""),
    ("AZ", "Arizona",              0.63,  431_000, 1_900, 2.5, ""),
    ("AR", "Arkansas",             0.62,  208_000, 3_400, 2.5, ""),
    ("CA", "California",           0.71,  786_000, 1_800, 2.5,
     "Proposition 13 assesses at purchase price and caps annual increases at 2%. "
     "The statewide effective rate understates a new purchase — budget 1.1-1.25% "
     "of what you actually pay."),
    ("CO", "Colorado",             0.51,  548_000, 3_200, 2.5, ""),
    ("CT", "Connecticut",          1.79,  400_000, 1_900, 3.0, ""),
    ("DE", "Delaware",             0.58,  373_000, 1_100, 4.5,
     "Delaware charges a 4% realty transfer tax, usually split with the seller. "
     "Closing costs here are among the highest in the country."),
    ("DC", "District of Columbia", 0.57,  610_000, 1_400, 4.0,
     "Recordation tax plus a deed transfer tax; first-time buyers may qualify for "
     "a reduced recordation rate."),
    ("FL", "Florida",              0.82,  405_000, 6_000, 3.0,
     "Homeowners insurance is the highest in the country and rising; get a real "
     "quote before committing, and check flood-zone requirements separately."),
    ("GA", "Georgia",              0.90,  348_000, 2_400, 2.5, ""),
    ("HI", "Hawaii",               0.29,  845_000, 1_600, 2.5, ""),
    ("ID", "Idaho",                0.63,  461_000, 1_900, 2.5, ""),
    ("IL", "Illinois",             2.07,  270_000, 2_500, 3.0,
     "Among the highest property taxes in the country, and Cook County runs well "
     "above the state average."),
    ("IN", "Indiana",              0.83,  238_000, 2_000, 2.5, ""),
    ("IA", "Iowa",                 1.50,  222_000, 2_600, 2.5, ""),
    ("KS", "Kansas",               1.34,  225_000, 4_200, 2.5, ""),
    ("KY", "Kentucky",             0.85,  213_000, 2_700, 2.5, ""),
    ("LA", "Louisiana",            0.56,  213_000, 6_400, 2.5,
     "Insurance is severe and hurricane deductibles are separate from the base "
     "premium. Flood coverage is usually a distinct policy."),
    ("ME", "Maine",                1.24,  383_000, 1_500, 2.5, ""),
    ("MD", "Maryland",             1.05,  406_000, 1_700, 3.5,
     "State transfer tax plus county recordation; first-time buyers get a partial "
     "exemption."),
    ("MA", "Massachusetts",        1.14,  611_000, 1_800, 3.0, ""),
    ("MI", "Michigan",             1.38,  245_000, 2_100, 2.5, ""),
    ("MN", "Minnesota",            1.11,  343_000, 2_600, 2.5, ""),
    ("MS", "Mississippi",          0.75,  180_000, 3_800, 2.5, ""),
    ("MO", "Missouri",             0.98,  248_000, 3_100, 2.5, ""),
    ("MT", "Montana",              0.74,  456_000, 2_800, 2.5, ""),
    ("NE", "Nebraska",             1.63,  257_000, 5_200, 2.5, ""),
    ("NV", "Nevada",               0.55,  460_000, 1_500, 2.5, ""),
    ("NH", "New Hampshire",        1.93,  478_000, 1_300, 2.5, ""),
    ("NJ", "New Jersey",           2.23,  520_000, 1_500, 3.0,
     "The highest effective property tax rate in the country."),
    ("NM", "New Mexico",           0.73,  305_000, 2_600, 2.5, ""),
    ("NY", "New York",             1.64,  470_000, 1_900, 4.0,
     "New York City adds a mortgage recording tax and, above $1M, a mansion tax. "
     "Upstate effective rates run well above the state average."),
    ("NC", "North Carolina",       0.80,  340_000, 2_100, 2.5, ""),
    ("ND", "North Dakota",         0.98,  270_000, 3_000, 2.5, ""),
    ("OH", "Ohio",                 1.53,  235_000, 1_600, 2.5, ""),
    ("OK", "Oklahoma",             0.90,  214_000, 5_800, 2.5,
     "Hail and wind exposure make premiums among the highest in the country."),
    ("OR", "Oregon",               0.93,  500_000, 1_400, 2.5, ""),
    ("PA", "Pennsylvania",         1.49,  268_000, 1_400, 3.5,
     "A 2% realty transfer tax, normally split with the seller."),
    ("RI", "Rhode Island",         1.40,  460_000, 1_900, 3.0, ""),
    ("SC", "South Carolina",       0.57,  300_000, 2_200, 2.5, ""),
    ("SD", "South Dakota",         1.17,  300_000, 3_200, 2.5, ""),
    ("TN", "Tennessee",            0.67,  325_000, 2_400, 2.5, ""),
    ("TX", "Texas",                1.68,  305_000, 4_400, 2.5,
     "No state income tax, paid for by high property tax. Rates vary sharply by "
     "district — check the specific parcel, not the state average."),
    ("UT", "Utah",                 0.57,  525_000, 1_600, 2.5, ""),
    ("VT", "Vermont",              1.83,  400_000, 1_100, 2.5, ""),
    ("VA", "Virginia",             0.82,  405_000, 1_700, 2.5, ""),
    ("WA", "Washington",           0.87,  620_000, 1_600, 3.0,
     "A real estate excise tax applies on sale; the seller normally pays it."),
    ("WV", "West Virginia",        0.57,  165_000, 1_600, 2.5, ""),
    ("WI", "Wisconsin",            1.61,  310_000, 1_600, 2.5, ""),
    ("WY", "Wyoming",              0.61,  365_000, 1_800, 2.5, ""),
]

STATES: dict[str, dict] = {
    code: {
        "code": code,
        "name": name,
        "property_tax_rate": tax,
        "median_home_price": price,
        "insurance_annual": insurance,
        "closing_cost_pct": closing,
        "note": note or None,
    }
    for code, name, tax, price, insurance, closing, note in _ROWS
}


def get(code: str | None) -> dict | None:
    return STATES.get((code or "").strip().upper()) or None


def all_states() -> list[dict]:
    return sorted(STATES.values(), key=lambda s: s["name"])


def defaults_for(code: str) -> dict:
    """The fields a state selection should overwrite, and nothing else.

    Deliberately narrow: price, income, and rate are the user's own situation,
    and a state change must not quietly rewrite them.
    """
    state = get(code)
    if not state:
        return {}
    return {
        "property_tax_rate": state["property_tax_rate"],
        "insurance_annual": state["insurance_annual"],
        "closing_cost_pct": state["closing_cost_pct"],
    }
