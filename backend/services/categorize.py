"""Turn raw bank descriptions into merchants and categories.

Real card feeds are hostile to grouping: the same coffee shop arrives as
``SQ *BLUE BOTTLE COFFEE  OAKLAND CA``, ``TST* BLUE BOTTLE #4412`` and
``BLUE BOTTLE COFFEE 0041``. Nothing downstream — not merchant totals, not
subscription detection, not price-creep alerts — works until those collapse to
one key, so normalisation happens once here and is stored on the row.

Precedence, highest first:
  1. user rules in ``category_rules`` (by priority, then id)
  2. built-in merchant keywords
  3. the provider's own category hint
  4. ``Uncategorized``
"""

from __future__ import annotations

import re

import db

# Payment processors and bank-added ceremony that prefix the real merchant.
_PREFIXES = [
    r"^PURCHASE\s+AUTHORIZED\s+ON\s+\d{1,2}/\d{1,2}\s*",
    r"^RECURRING\s+PAYMENT\s+AUTHORIZED\s+ON\s+\d{1,2}/\d{1,2}\s*",
    r"^(CHECKCARD|CHECK\s*CARD)\s+\d{3,4}\s*",
    r"^(DEBIT|CREDIT)\s+CARD\s+(PURCHASE|PAYMENT)\s*",
    r"^POS\s+(DEBIT|PURCHASE)?\s*",
    r"^VISA\s+DDA\s+(PUR|PURCHASE)\s*",
    r"^(ACH|EFT)\s+(DEBIT|CREDIT|WEB|PMT)\s*",
    r"^(SQ|TST|SP|PP|PY|PAYPAL|TOAST|LEVELUP|EB|WL)\s*\*+\s*",
    r"^EXTERNAL\s+(DEPOSIT|WITHDRAWAL)\s*",
    r"^PRE-?AUTH(ORIZED)?\s+",
]

# Trailing noise the token pass cannot see, because it spans tokens.
_SUFFIXES = [
    # The ACH envelope. US banks append DES:/ID:/INDN:/CO ID: to every direct
    # debit, and everything after DES: is routing metadata and *your own name*
    # — never the company's. Left in, it makes every ACH bill look alike:
    # two unrelated debits both "share" INDN:Your Name.
    r"\s*\bDES:.*$",
    r"\s+S\d{10,}.*$",                 # Wells-style trailing sequence blob
    r"\s+(CARD|XXXX|X{2,})\s*\d*\s*$",
    r"\s+\d{2}/\d{2}(/\d{2,4})?\s*$",  # trailing date
]

# Corporate and retail filler that varies between feeds for the same merchant
# ("STARBUCKS STORE 10432" vs "STARBUCKS #567"), so it must not reach the key.
_FILLER = {
    "STORE", "STORES", "LLC", "INC", "CORP", "CORPORATION", "LTD", "LP",
    "COMPANY", "THE", "USA", "US",
}

# Long mixed alphanumeric blobs are machine ids, never merchant names — but
# "mixed" has to mean genuinely digit-heavy. A single trailing digit does not
# make a company name an id, and treating it as one is expensive: ACMEPROPERTY2
# reduced to nothing, leaving a two-letter merchant that then matched a quarter
# of the ledger.
_ID_MIN_DIGITS = 2
_ID_MIN_DIGIT_RATIO = 0.25


def _looks_like_id(token: str) -> bool:
    if len(token) < 6 or not token.isalnum() or not token.isupper():
        return False
    digits = sum(c.isdigit() for c in token)
    if digits < _ID_MIN_DIGITS:
        return False
    return digits / len(token) >= _ID_MIN_DIGIT_RATIO

_US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC",
}

# Cities are stripped only on an exact match against this list. The tempting
# shortcut — "drop one token before the state code" — mangles real names:
# "OR ELSE CAFE NY" would become "OR ELSE". An unknown small city staying in
# the key costs a little cross-city grouping; a mangled name costs correctness.
_CITIES = {
    "NEW YORK", "BROOKLYN", "QUEENS", "BRONX", "MANHATTAN", "STATEN ISLAND",
    "LOS ANGELES", "SAN FRANCISCO", "SAN JOSE", "SAN DIEGO", "SAN MATEO",
    "SAN RAFAEL", "SAN BRUNO", "SANTA CLARA", "SANTA MONICA", "SANTA CRUZ",
    "SANTA ANA", "SANTA BARBARA", "SACRAMENTO", "OAKLAND", "BERKELEY",
    "EMERYVILLE", "ALAMEDA", "FREMONT", "HAYWARD", "PALO ALTO", "MENLO PARK",
    "MOUNTAIN VIEW", "SUNNYVALE", "CUPERTINO", "DALY CITY", "SOUTH SAN FRANCISCO",
    "REDWOOD CITY", "FOSTER CITY", "BURLINGAME", "MILLBRAE", "PACIFICA",
    "WALNUT CREEK", "CONCORD", "RICHMOND", "SAN LEANDRO", "MILPITAS",
    "LONG BEACH", "PASADENA", "GLENDALE", "BURBANK", "ANAHEIM", "IRVINE",
    "TORRANCE", "CULVER CITY", "WEST HOLLYWOOD", "BEVERLY HILLS", "VENICE",
    "CHICAGO", "EVANSTON", "NAPERVILLE", "HOUSTON", "AUSTIN", "DALLAS",
    "SAN ANTONIO", "FORT WORTH", "EL PASO", "PLANO", "ARLINGTON",
    "PHOENIX", "SCOTTSDALE", "TEMPE", "MESA", "TUCSON", "CHANDLER",
    "PHILADELPHIA", "PITTSBURGH", "BOSTON", "CAMBRIDGE", "SOMERVILLE",
    "BROOKLINE", "NEWTON", "QUINCY", "SEATTLE", "BELLEVUE", "REDMOND",
    "TACOMA", "SPOKANE", "KIRKLAND", "PORTLAND", "BEAVERTON", "EUGENE",
    "DENVER", "BOULDER", "AURORA", "COLORADO SPRINGS", "FORT COLLINS",
    "ATLANTA", "MIAMI", "MIAMI BEACH", "ORLANDO", "TAMPA", "JACKSONVILLE",
    "FORT LAUDERDALE", "ST PETERSBURG", "CHARLOTTE", "RALEIGH", "DURHAM",
    "NASHVILLE", "MEMPHIS", "KNOXVILLE", "LOUISVILLE", "LEXINGTON",
    "DETROIT", "ANN ARBOR", "GRAND RAPIDS", "MINNEAPOLIS", "ST PAUL",
    "MILWAUKEE", "MADISON", "INDIANAPOLIS", "COLUMBUS", "CLEVELAND",
    "CINCINNATI", "TOLEDO", "KANSAS CITY", "ST LOUIS", "OMAHA", "DES MOINES",
    "OKLAHOMA CITY", "TULSA", "NEW ORLEANS", "BATON ROUGE", "LITTLE ROCK",
    "BIRMINGHAM", "HUNTSVILLE", "RICHMOND", "VIRGINIA BEACH", "NORFOLK",
    "ALEXANDRIA", "ARLINGTON", "WASHINGTON", "BALTIMORE", "ANNAPOLIS",
    "NEWARK", "JERSEY CITY", "HOBOKEN", "PRINCETON", "TRENTON", "PATERSON",
    "STAMFORD", "HARTFORD", "NEW HAVEN", "BRIDGEPORT", "PROVIDENCE",
    "MANCHESTER", "BURLINGTON", "PORTLAND", "SALT LAKE CITY", "PROVO",
    "BOISE", "LAS VEGAS", "HENDERSON", "RENO", "ALBUQUERQUE", "SANTA FE",
    "HONOLULU", "ANCHORAGE", "BUFFALO", "ROCHESTER", "SYRACUSE", "ALBANY",
    "YONKERS", "WHITE PLAINS", "NEW ROCHELLE", "MOUNT VERNON",
}
_MAX_CITY_TOKENS = 3

# All-caps abbreviations that read wrong title-cased. The vowel heuristic below
# catches most (MKT, AMZN); these are the ones it misses.
_KEEP_CAPS = {"HBO", "AMC", "IKEA", "ATT", "IRS", "DMV", "NYC", "LA", "SF"}


def normalize_merchant(description: str, provider_merchant: str | None = None) -> tuple[str, str]:
    """Returns ``(display_name, grouping_key)``.

    The provider's own counterparty name is trusted when present — Plaid does
    real enrichment — and the description is only parsed when it is not.
    """
    raw = (provider_merchant or description or "").strip()
    if not raw:
        return "Unknown", "unknown"

    s = raw.upper()
    for pat in _PREFIXES:
        s = re.sub(pat, "", s)
    # Merchant names do not contain URLs; the domain is the useful part.
    s = re.sub(r"\b(HTTPS?://|WWW\.)", "", s)
    s = re.sub(r"\.(COM|NET|ORG|CO|IO)\b", "", s)
    for pat in _SUFFIXES:
        s = re.sub(pat, "", s)

    # "*" splits too: "AMAZON.COM*2K4LQ1OG3" must yield the id as its own token
    # so the id filter can see it.
    tokens = [t for t in re.split(r"[\s\-_/|*]+", s) if t]
    kept: list[str] = []
    for tok in tokens:
        bare = tok.strip(".,*#&'\"")
        if not bare or bare in _FILLER:
            continue
        if _looks_like_id(bare):
            continue
        if bare.isdigit() and len(bare) >= 3:
            continue
        kept.append(bare)

    kept = _strip_location(kept)

    if not kept:
        # Everything looked like noise. Fall back to the raw tokens rather than
        # returning nothing, so the transaction is still groupable.
        kept = [t for t in tokens if t][:2] or ["UNKNOWN"]

    cleaned = " ".join(kept[:5])
    key = re.sub(r"[^a-z0-9 ]", "", cleaned.lower())
    key = re.sub(r"\s+", " ", key).strip() or "unknown"
    return _display_name(cleaned), key


def _strip_location(tokens: list[str]) -> list[str]:
    """Remove a trailing ``CITY ST`` block, never emptying the name."""
    out = list(tokens)
    if len(out) >= 2 and out[-1] in _US_STATES:
        out.pop()
    # Longest city match first, so "SALT LAKE CITY" wins over "CITY".
    for span in range(min(_MAX_CITY_TOKENS, len(out) - 1), 0, -1):
        if " ".join(out[-span:]) in _CITIES:
            return out[:-span]
    return out


def _display_name(cleaned: str) -> str:
    words = []
    for w in cleaned.split():
        vowelless = not (set(w) & set("AEIOU"))
        if w.isupper() and (w in _KEEP_CAPS or (len(w) <= 4 and vowelless)):
            words.append(w)
        else:
            words.append(w.capitalize())
    return " ".join(words)


# Keyword -> (category, subcategory). Matched against the normalised key as a
# substring, longest keyword first so "uber eats" beats "uber".
MERCHANT_KEYWORDS: dict[str, tuple[str, str]] = {
    # Transfers and payments must win before anything else reads them as spend.
    "payment thank you": ("Transfer", "Card Payment"),
    "autopay payment": ("Transfer", "Card Payment"),
    "online payment": ("Transfer", "Card Payment"),
    "chase credit crd": ("Transfer", "Card Payment"),
    "capital one mobile pmt": ("Transfer", "Card Payment"),
    "zelle": ("Transfer", "Person to Person"),
    "venmo": ("Transfer", "Person to Person"),
    "cash app": ("Transfer", "Person to Person"),
    "transfer to": ("Transfer", "Internal"),
    "transfer from": ("Transfer", "Internal"),
    "apple savings": ("Transfer", "Internal"),
    "robinhood": ("Transfer", "Investment Contribution"),
    "wealthfront": ("Transfer", "Investment Contribution"),
    "vanguard": ("Transfer", "Investment Contribution"),
    "fidelity": ("Transfer", "Investment Contribution"),
    "coinbase": ("Transfer", "Investment Contribution"),

    # Income
    "payroll": ("Income", "Salary"),
    "direct dep": ("Income", "Salary"),
    "dir dep": ("Income", "Salary"),
    "interest paid": ("Income", "Interest"),
    "interest payment": ("Income", "Interest"),
    "dividend": ("Income", "Dividends"),
    "tax refund": ("Income", "Refund"),
    "irs treas": ("Income", "Refund"),
    "cashback bonus": ("Income", "Rewards"),
    "cash back reward": ("Income", "Rewards"),

    # Housing
    "rent": ("Housing", "Rent"),
    "mortgage": ("Housing", "Mortgage"),
    "pg e": ("Housing", "Utilities"),
    "pge": ("Housing", "Utilities"),
    "con edison": ("Housing", "Utilities"),
    "water dept": ("Housing", "Utilities"),
    "comcast": ("Housing", "Internet"),
    "xfinity": ("Housing", "Internet"),
    "spectrum": ("Housing", "Internet"),
    "optimum": ("Housing", "Internet"),
    "duke energy": ("Housing", "Utilities"),
    "dukeenergy": ("Housing", "Utilities"),
    "dominion energy": ("Housing", "Utilities"),
    "national grid": ("Housing", "Utilities"),
    "verizon": ("Housing", "Phone"),
    "at t": ("Housing", "Phone"),
    "t mobile": ("Housing", "Phone"),
    # The feed writes this as TMOBILE*POSTPAID IVR, one token.
    "tmobile": ("Housing", "Phone"),
    "google fiber": ("Housing", "Internet"),
    "home depot": ("Housing", "Maintenance"),
    "lowes": ("Housing", "Maintenance"),
    "ikea": ("Housing", "Furnishings"),

    # Groceries
    "trader joe": ("Groceries", "Supermarket"),
    "whole foods": ("Groceries", "Supermarket"),
    "safeway": ("Groceries", "Supermarket"),
    "kroger": ("Groceries", "Supermarket"),
    "costco": ("Groceries", "Warehouse"),
    "sams club": ("Groceries", "Warehouse"),
    "wegmans": ("Groceries", "Supermarket"),
    "publix": ("Groceries", "Supermarket"),
    "aldi": ("Groceries", "Supermarket"),
    "sprouts": ("Groceries", "Supermarket"),
    "instacart": ("Groceries", "Delivery"),
    "bi rite": ("Groceries", "Supermarket"),
    "erewhon": ("Groceries", "Supermarket"),

    # Dining — split finely, because this is where leakage hides.
    "uber eats": ("Dining", "Delivery"),
    "doordash": ("Dining", "Delivery"),
    "grubhub": ("Dining", "Delivery"),
    "postmates": ("Dining", "Delivery"),
    "caviar": ("Dining", "Delivery"),
    "seamless": ("Dining", "Delivery"),
    "starbucks": ("Dining", "Coffee"),
    "blue bottle": ("Dining", "Coffee"),
    "peets": ("Dining", "Coffee"),
    "dunkin": ("Dining", "Coffee"),
    "philz": ("Dining", "Coffee"),
    "chipotle": ("Dining", "Fast Food"),
    "sweetgreen": ("Dining", "Fast Food"),
    "mcdonald": ("Dining", "Fast Food"),
    "subway": ("Dining", "Fast Food"),
    "taco bell": ("Dining", "Fast Food"),
    "shake shack": ("Dining", "Fast Food"),
    "in n out": ("Dining", "Fast Food"),
    "panera": ("Dining", "Fast Food"),
    "restaurant": ("Dining", "Restaurants"),
    # Card feeds truncate hard: "LUIGIS ITALIAN RESTAUR" never reaches the
    # full word, so the stem has to be listed in its own right.
    "restaur": ("Dining", "Restaurants"),
    "pizzeria": ("Dining", "Restaurants"),
    "pizza": ("Dining", "Restaurants"),
    "sushi": ("Dining", "Restaurants"),
    "ramen": ("Dining", "Restaurants"),
    "taqueria": ("Dining", "Restaurants"),
    "cuisine": ("Dining", "Restaurants"),
    "bistro": ("Dining", "Restaurants"),
    "grill": ("Dining", "Restaurants"),
    "steakhouse": ("Dining", "Restaurants"),
    "diner": ("Dining", "Restaurants"),
    "eatery": ("Dining", "Restaurants"),
    "noodle": ("Dining", "Restaurants"),
    "bbq": ("Dining", "Restaurants"),
    "deli": ("Dining", "Restaurants"),
    "bakery": ("Dining", "Bakery"),
    "creamery": ("Dining", "Dessert"),
    "gelato": ("Dining", "Dessert"),
    "cafe": ("Dining", "Restaurants"),
    "coffee": ("Dining", "Coffee"),
    "espresso": ("Dining", "Coffee"),
    "bar": ("Dining", "Bars"),
    "taproom": ("Dining", "Bars"),
    "brewing": ("Dining", "Bars"),
    "brewery": ("Dining", "Bars"),
    "tavern": ("Dining", "Bars"),
    "pub": ("Dining", "Bars"),

    # Transportation
    "uber": ("Transportation", "Rideshare"),
    "lyft": ("Transportation", "Rideshare"),
    "shell": ("Transportation", "Gas"),
    "chevron": ("Transportation", "Gas"),
    "exxon": ("Transportation", "Gas"),
    "bp": ("Transportation", "Gas"),
    "arco": ("Transportation", "Gas"),
    "tesla supercharger": ("Transportation", "EV Charging"),
    "chargepoint": ("Transportation", "EV Charging"),
    "bart": ("Transportation", "Transit"),
    "clipper": ("Transportation", "Transit"),
    "mta": ("Transportation", "Transit"),
    "parking": ("Transportation", "Parking"),
    "fastrak": ("Transportation", "Tolls"),
    "ezpass": ("Transportation", "Tolls"),
    "geico": ("Transportation", "Auto Insurance"),
    "progressive": ("Transportation", "Auto Insurance"),
    "state farm": ("Transportation", "Auto Insurance"),
    "jiffy lube": ("Transportation", "Auto Maintenance"),
    "valvoline": ("Transportation", "Auto Maintenance"),

    # Subscriptions — every one of these is a cancellation candidate.
    "netflix": ("Subscriptions", "Streaming"),
    "hulu": ("Subscriptions", "Streaming"),
    "disney plus": ("Subscriptions", "Streaming"),
    "disney": ("Subscriptions", "Streaming"),
    "hbo": ("Subscriptions", "Streaming"),
    "hbo max": ("Subscriptions", "Streaming"),
    "paramount": ("Subscriptions", "Streaming"),
    "peacock": ("Subscriptions", "Streaming"),
    "apple tv": ("Subscriptions", "Streaming"),
    "youtube premium": ("Subscriptions", "Streaming"),
    "youtubepremium": ("Subscriptions", "Streaming"),
    "spotify": ("Subscriptions", "Music"),
    "apple music": ("Subscriptions", "Music"),
    "audible": ("Subscriptions", "Books"),
    "kindle unlimited": ("Subscriptions", "Books"),
    "nytimes": ("Subscriptions", "News"),
    "new york times": ("Subscriptions", "News"),
    "wall street journal": ("Subscriptions", "News"),
    "washington post": ("Subscriptions", "News"),
    "substack": ("Subscriptions", "News"),
    "icloud": ("Subscriptions", "Software"),
    "apple one": ("Subscriptions", "Software"),
    "google storage": ("Subscriptions", "Software"),
    "google one": ("Subscriptions", "Software"),
    "dropbox": ("Subscriptions", "Software"),
    "adobe": ("Subscriptions", "Software"),
    "notion": ("Subscriptions", "Software"),
    "github": ("Subscriptions", "Software"),
    "openai": ("Subscriptions", "Software"),
    "anthropic": ("Subscriptions", "Software"),
    "claude": ("Subscriptions", "Software"),
    "linkedin premium": ("Subscriptions", "Software"),
    "amazon prime": ("Subscriptions", "Shopping"),
    "prime video": ("Subscriptions", "Streaming"),
    "patreon": ("Subscriptions", "Other"),
    "onepassword": ("Subscriptions", "Software"),
    "1password": ("Subscriptions", "Software"),
    "nordvpn": ("Subscriptions", "Software"),

    # Health
    "cvs": ("Health", "Pharmacy"),
    "walgreens": ("Health", "Pharmacy"),
    "rite aid": ("Health", "Pharmacy"),
    "equinox": ("Health", "Fitness"),
    "planet fitness": ("Health", "Fitness"),
    "24 hour fitness": ("Health", "Fitness"),
    "barry": ("Health", "Fitness"),
    "soulcycle": ("Health", "Fitness"),
    "classpass": ("Health", "Fitness"),
    "peloton": ("Health", "Fitness"),
    "dental": ("Health", "Dental"),
    "dentist": ("Health", "Dental"),
    "medical": ("Health", "Doctor"),
    "kaiser": ("Health", "Doctor"),
    "one medical": ("Health", "Doctor"),
    "zocdoc": ("Health", "Doctor"),
    "blue shield": ("Health", "Insurance"),
    "blue cross": ("Health", "Insurance"),
    "hospital": ("Health", "Doctor"),
    "clinic": ("Health", "Doctor"),
    "pediatric": ("Health", "Doctor"),
    "urgent care": ("Health", "Doctor"),
    "physician": ("Health", "Doctor"),
    "orthodont": ("Health", "Dental"),
    "dermatolog": ("Health", "Doctor"),
    "optometr": ("Health", "Vision"),
    "pharmacy": ("Health", "Pharmacy"),

    # Pets. Not a top-level category, because a household's pet spend is real
    # but small — it lands in Other rather than inflating Health.
    # Longest-first matching keeps "animal hospital" away from "hospital".
    "animal hospital": ("Other", "Pets"),
    "veterinar": ("Other", "Pets"),
    "vca": ("Other", "Pets"),
    "trupanion": ("Other", "Pets"),
    "petco": ("Other", "Pets"),
    "petsmart": ("Other", "Pets"),
    "chewy": ("Other", "Pets"),

    # Education
    "technical coll": ("Education", "Tuition"),
    "community college": ("Education", "Tuition"),
    "college": ("Education", "Tuition"),
    "university": ("Education", "Tuition"),
    "tuition": ("Education", "Tuition"),

    # Shopping
    "amazon": ("Shopping", "General"),
    "amzn": ("Shopping", "General"),
    "target": ("Shopping", "General"),
    "walmart": ("Shopping", "General"),
    "best buy": ("Shopping", "Electronics"),
    "apple store": ("Shopping", "Electronics"),
    "newegg": ("Shopping", "Electronics"),
    "nike": ("Shopping", "Clothing"),
    "lululemon": ("Shopping", "Clothing"),
    "uniqlo": ("Shopping", "Clothing"),
    "zara": ("Shopping", "Clothing"),
    "nordstrom": ("Shopping", "Clothing"),
    "sephora": ("Shopping", "Personal Care"),
    "ulta": ("Shopping", "Personal Care"),
    "etsy": ("Shopping", "General"),
    "ebay": ("Shopping", "General"),
    "tiktok shop": ("Shopping", "General"),
    "temu": ("Shopping", "General"),
    "shein": ("Shopping", "Clothing"),
    "wayfair": ("Housing", "Furnishings"),

    # Travel
    "united airlines": ("Travel", "Flights"),
    "delta air": ("Travel", "Flights"),
    "southwest air": ("Travel", "Flights"),
    "alaska air": ("Travel", "Flights"),
    "jetblue": ("Travel", "Flights"),
    "american airlines": ("Travel", "Flights"),
    "airbnb": ("Travel", "Lodging"),
    "vrbo": ("Travel", "Lodging"),
    "marriott": ("Travel", "Lodging"),
    "hilton": ("Travel", "Lodging"),
    "hyatt": ("Travel", "Lodging"),
    "expedia": ("Travel", "Booking"),
    "booking com": ("Travel", "Booking"),
    "chase travel": ("Travel", "Booking"),
    "airlines": ("Travel", "Flights"),
    "airways": ("Travel", "Flights"),
    "hertz": ("Travel", "Car Rental"),
    "enterprise rent": ("Travel", "Car Rental"),

    # Entertainment
    "amc": ("Entertainment", "Movies"),
    "cinemark": ("Entertainment", "Movies"),
    "regal": ("Entertainment", "Movies"),
    "ticketmaster": ("Entertainment", "Events"),
    "stubhub": ("Entertainment", "Events"),
    "eventbrite": ("Entertainment", "Events"),
    "steam games": ("Entertainment", "Games"),
    "playstation": ("Entertainment", "Games"),
    "xbox": ("Entertainment", "Games"),
    "nintendo": ("Entertainment", "Games"),

    # Fees and interest — always worth surfacing, always avoidable.
    "annual membership fee": ("Fees & Interest", "Annual Fee"),
    "annual fee": ("Fees & Interest", "Annual Fee"),
    "foreign transaction fee": ("Fees & Interest", "Foreign Transaction"),
    "interest charge": ("Fees & Interest", "Interest"),
    "purchase interest": ("Fees & Interest", "Interest"),
    "late fee": ("Fees & Interest", "Late Fee"),
    "overdraft": ("Fees & Interest", "Overdraft"),
    "nsf fee": ("Fees & Interest", "Overdraft"),
    "atm fee": ("Fees & Interest", "ATM"),
    "monthly maintenance fee": ("Fees & Interest", "Account Fee"),
    "service charge": ("Fees & Interest", "Account Fee"),
    "wire fee": ("Fees & Interest", "Wire Fee"),
    "cash advance fee": ("Fees & Interest", "Cash Advance"),

    # Other
    "irs": ("Taxes", "Federal"),
    "franchise tax": ("Taxes", "State"),
    "turbotax": ("Taxes", "Preparation"),
    "usps": ("Other", "Postage"),
    "fedex": ("Other", "Shipping"),
    "ups store": ("Other", "Shipping"),
}

# Longest first so the specific keyword wins over the generic one it contains
# ("uber eats" must beat "uber"). Matched on word boundaries rather than as bare
# substrings, because "bar" inside "Barnes & Noble" is not a bar and "rent"
# inside "Enterprise Rent" is not rent.
_SORTED_KEYWORDS = [
    (kw, re.compile(r"\b" + re.escape(kw).replace(r"\ ", r"\s+") + r"\b"), val)
    for kw, val in sorted(MERCHANT_KEYWORDS.items(), key=lambda kv: -len(kv[0]))
]

# The provider's own taxonomy, mapped onto ours. Plaid's personal-finance
# category (`FOOD_AND_DRINK`, `LOAN_PAYMENTS`, ...) arrives title-cased and is
# looked up here after being lowered and underscored, so both spellings of a
# name resolve to the same entry.
PROVIDER_CATEGORY_MAP = {
    "dining": ("Dining", "Restaurants"),
    "food_and_drink": ("Dining", "Restaurants"),
    "restaurants": ("Dining", "Restaurants"),
    "groceries": ("Groceries", "Supermarket"),
    "fuel": ("Transportation", "Gas"),
    "transport": ("Transportation", "Transit"),
    "transportation": ("Transportation", "Transit"),
    "travel": ("Travel", "Booking"),
    "accommodation": ("Travel", "Lodging"),
    "entertainment": ("Entertainment", "General"),
    "shopping": ("Shopping", "General"),
    "general_merchandise": ("Shopping", "General"),
    "clothing": ("Shopping", "Clothing"),
    "electronics": ("Shopping", "Electronics"),
    "health": ("Health", "Doctor"),
    "medical": ("Health", "Doctor"),
    "pharmacy": ("Health", "Pharmacy"),
    "insurance": ("Health", "Insurance"),
    "utilities": ("Housing", "Utilities"),
    "rent_and_utilities": ("Housing", "Utilities"),
    "home_improvement": ("Housing", "Maintenance"),
    "rent": ("Housing", "Rent"),
    "home": ("Housing", "Maintenance"),
    "phone": ("Housing", "Phone"),
    "internet": ("Housing", "Internet"),
    "subscription": ("Subscriptions", "Other"),
    "software": ("Subscriptions", "Software"),
    "income": ("Income", "Salary"),
    "loan_payments": ("Transfer", "Loan Payment"),
    "transfer": ("Transfer", "Internal"),
    "transfer_in": ("Transfer", "Internal"),
    "transfer_out": ("Transfer", "Internal"),
    "bank_fees": ("Fees & Interest", "Account Fee"),
    "interest": ("Fees & Interest", "Interest"),
    "tax": ("Taxes", "Federal"),
    "education": ("Education", "General"),
    "charity": ("Gifts & Donations", "Charity"),
    "gifts": ("Gifts & Donations", "Gifts"),
    "personal_care": ("Shopping", "Personal Care"),
    "office": ("Other", "Office"),
    "service": ("Other", "Services"),
    "general_services": ("Other", "Services"),
    # Plaid folds tax payments, government fees, and donations into one
    # primary, so it cannot be assumed to be any of them specifically.
    "government_and_non_profit": ("Other", "Government"),
}

# Categories excluded from "spending" by definition: moving your own money
# between your own accounts is not an expense.
NON_SPEND_CATEGORIES = {"Transfer", "Income"}

ALL_CATEGORIES = [
    "Housing", "Groceries", "Dining", "Transportation", "Subscriptions",
    "Shopping", "Health", "Travel", "Entertainment", "Education",
    "Gifts & Donations", "Fees & Interest", "Taxes", "Other",
    "Transfer", "Income", "Uncategorized",
]


def _load_rules() -> list[dict]:
    return db.query(
        "SELECT * FROM category_rules ORDER BY priority ASC, id ASC"
    )


def _rule_matches(rule: dict, description: str, merchant: str) -> bool:
    pat = rule["pattern"].lower()
    desc, merch = description.lower(), (merchant or "").lower()
    kind = rule["match_type"]
    if kind == "merchant_contains":
        return pat in merch
    if kind == "description_contains":
        return pat in desc
    if kind == "description_regex":
        try:
            return re.search(rule["pattern"], description, re.I) is not None
        except re.error:
            return False
    return False


# Toast (TST*) is restaurant point-of-sale only. Square (SQ*) and PayPal
# deliberately are not here: they serve every industry, so their prefix says
# nothing about what was bought.
_SINGLE_INDUSTRY_PROCESSOR = re.compile(r"^\s*(TST|TOAST)\s*\*", re.I)


def categorize(
    *,
    description: str,
    merchant: str | None,
    merchant_key: str,
    raw_category: str | None,
    amount: float,
    account_type: str,
    rules: list[dict] | None = None,
) -> tuple[str, str | None, bool]:
    """Returns ``(category, subcategory, is_transfer)``.

    ``rules`` can be passed in so a bulk sync loads them once instead of once
    per transaction.
    """
    rules = _load_rules() if rules is None else rules

    for rule in rules:
        if _rule_matches(rule, description, merchant or ""):
            return rule["category"], rule["subcategory"], bool(rule["is_transfer"])

    haystack = f"{merchant_key} {description.lower()}"
    for _kw, pattern, (cat, sub) in _SORTED_KEYWORDS:
        if pattern.search(haystack):
            # A credit-card payment is a transfer; "payment" arriving on the
            # card and leaving the checking account is the same money twice.
            return cat, sub, cat == "Transfer"

    # A single-industry payment processor says more than the merchant name it
    # wraps. Toast sells point-of-sale to restaurants and nothing else, so
    # TST* is reliable exactly where the keyword list is weakest: the local
    # place no list will ever contain.
    if _SINGLE_INDUSTRY_PROCESSOR.match(description):
        return "Dining", "Restaurants", False

    if raw_category:
        key = raw_category.strip().lower().replace(" ", "_").replace("-", "_")
        if key in PROVIDER_CATEGORY_MAP:
            cat, sub = PROVIDER_CATEGORY_MAP[key]
            return cat, sub, cat == "Transfer"

    # Last resort: an unmatched deposit into a bank account is almost always
    # income, and treating it as Uncategorized spend would corrupt every total.
    if amount > 0 and account_type == "depository":
        return "Income", "Other Income", False

    return "Uncategorized", None, False


def renormalize_merchants() -> int:
    """Recompute merchant names and keys for every stored transaction.

    Merchant keys are stored, not derived on read, so improving the normaliser
    leaves history on the old spelling — and grouping, rules, and subscription
    detection all key off it. This backfills. Categories are left alone; run
    ``recategorize_all`` after it if the keys have moved.
    """
    rows = db.query("SELECT id, description, merchant, merchant_key FROM transactions")
    changed = 0
    with db.tx() as conn:
        for r in rows:
            merchant, key = normalize_merchant(r["description"])
            if merchant != r["merchant"] or key != r["merchant_key"]:
                conn.execute(
                    "UPDATE transactions SET merchant = ?, merchant_key = ? WHERE id = ?",
                    (merchant, key, r["id"]),
                )
                changed += 1
    return changed


def recategorize_all() -> int:
    """Re-run categorisation over every stored transaction.

    Needed whenever rules change: a rule the user adds today should apply to
    the two years of history already imported.
    """
    rules = _load_rules()
    rows = db.query(
        "SELECT t.id, t.description, t.merchant, t.merchant_key, t.raw_category, "
        "       t.amount, a.type AS account_type "
        "FROM transactions t JOIN accounts a ON a.id = t.account_id"
    )
    updated = 0
    with db.tx() as conn:
        for r in rows:
            cat, sub, is_transfer = categorize(
                description=r["description"], merchant=r["merchant"],
                merchant_key=r["merchant_key"] or "", raw_category=r["raw_category"],
                amount=r["amount"], account_type=r["account_type"], rules=rules,
            )
            conn.execute(
                "UPDATE transactions SET category=?, subcategory=?, is_transfer=? WHERE id=?",
                (cat, sub, int(is_transfer), r["id"]),
            )
            updated += 1
    return updated
