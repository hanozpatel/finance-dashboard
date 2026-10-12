"""CSV import — Apple Savings/Card, and a fallback for any institution.

Apple is the reason this exists. Apple Card and Apple Savings are issued by
Goldman Sachs and are not reachable through Plaid or any other aggregator —
Apple does not permit third-party aggregation at all. A periodic
export from the Wallet app is the only way to get that data, so the importer has
to handle it well rather than treat it as a degraded path.

Every bank formats exports differently, so nothing is hardcoded to one shape:
the header row is located by scoring candidate lines, columns are matched by
normalised name, and the sign convention is inferred and then shown to the user
for confirmation before anything is written.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime

# Apple Card's export puts purchases in as *positive* numbers, the opposite of
# most bank exports, which is exactly the kind of thing that silently inverts a
# year of spending if it is not detected.
PRESETS = {
    "apple_card": {
        "label": "Apple Card / Apple Savings (Wallet export)",
        "signals": ["clearing date", "purchased by", "amount (usd)"],
        "mapping": {
            "date": "Transaction Date",
            "description": "Description",
            "merchant": "Merchant",
            "category": "Category",
            "amount": "Amount (USD)",
            "sign": "positive_is_spend",
        },
    },
    "chase": {
        "label": "Chase (CSV export)",
        "signals": ["transaction date", "post date", "memo"],
        "mapping": {
            "date": "Transaction Date",
            "description": "Description",
            "category": "Category",
            "amount": "Amount",
            "sign": "negative_is_spend",
        },
    },
    "bofa": {
        "label": "Bank of America (CSV export)",
        "signals": ["running bal", "running bal."],
        "mapping": {
            "date": "Date",
            "description": "Description",
            "amount": "Amount",
            "sign": "negative_is_spend",
        },
    },
}

_DATE_CANDIDATES = [
    "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%m-%d-%Y",
    "%d-%b-%Y", "%b %d, %Y", "%d %b %Y", "%Y-%m-%d %H:%M:%S",
]

_FIELD_ALIASES = {
    # Transaction date is preferred over posting/clearing date: it is when the
    # money was actually spent, which is what monthly totals should reflect.
    "date": ["transactiondate", "transdate", "date", "posteddate", "postdate",
             "postingdate", "clearingdate", "effectivedate"],
    "description": ["description", "payee", "name", "details", "transactiondescription",
                    "memo", "originaldescription"],
    "merchant": ["merchant", "counterparty", "merchantname"],
    "category": ["category", "categoryname"],
    "amount": ["amount", "amountusd", "transactionamount", "value", "netamount"],
    "debit": ["debit", "withdrawal", "withdrawals", "debitamount", "amountdebit"],
    "credit": ["credit", "deposit", "deposits", "creditamount", "amountcredit"],
}


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (h or "").lower())


def _find_header_row(rows: list[list[str]]) -> int:
    """Score each early row by how many known column names it contains.

    Bank exports routinely precede the header with blank lines, a title, or an
    account summary, so taking row 0 as the header fails on real files.
    """
    known = {a for aliases in _FIELD_ALIASES.values() for a in aliases}
    best_idx, best_score = 0, -1
    for i, row in enumerate(rows[:25]):
        if not row:
            continue
        score = sum(1 for cell in row if _norm(cell) in known)
        # A header has several named columns and no parseable amounts.
        if score > best_score and score >= 2:
            best_idx, best_score = i, score
    return best_idx


def parse_amount(raw) -> float | None:
    """Parse money as written by banks: ``$1,234.56``, ``(12.34)``, ``-$5``."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s in {"-", "--"}:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    s = s.replace("$", "").replace(",", "").replace(" ", "").strip()
    if s.startswith("+"):
        s = s[1:]
    try:
        value = float(s)
    except ValueError:
        return None
    return -value if negative else value


def parse_date(raw) -> str | None:
    s = str(raw or "").strip()
    if not s:
        return None
    for fmt in _DATE_CANDIDATES:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _detect_preset(headers: list[str]) -> str | None:
    joined = " ".join(h.lower() for h in headers)
    for name, preset in PRESETS.items():
        if all(sig in joined for sig in preset["signals"]):
            return name
    return None


def _guess_mapping(headers: list[str]) -> dict:
    by_norm = {_norm(h): h for h in headers}
    mapping: dict = {}
    for field, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            if alias in by_norm:
                mapping[field] = by_norm[alias]
                break
    return mapping


def sniff(content: bytes, filename: str = "") -> dict:
    """Inspect an upload and propose a mapping. Writes nothing."""
    text = content.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:8000], delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","

    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise ValueError("The file is empty.")

    header_idx = _find_header_row(rows)
    headers = [h.strip() for h in rows[header_idx]]
    data_rows = rows[header_idx + 1:]

    preset_name = _detect_preset(headers)
    if preset_name:
        mapping = dict(PRESETS[preset_name]["mapping"])
        # Only keep columns the file actually has, so a preset that drifts does
        # not silently map to a missing column.
        mapping = {k: v for k, v in mapping.items()
                   if k == "sign" or v in headers}
    else:
        mapping = _guess_mapping(headers)

    records = [dict(zip(headers, r)) for r in data_rows if len(r) >= len(headers) - 1]

    # Infer the sign convention from the data when no preset decided it. Most
    # rows in any statement are spending, so whichever sign dominates is spend.
    if "sign" not in mapping and mapping.get("amount"):
        amounts = [parse_amount(r.get(mapping["amount"])) for r in records[:400]]
        amounts = [a for a in amounts if a]
        positives = sum(1 for a in amounts if a > 0)
        mapping["sign"] = (
            "positive_is_spend" if amounts and positives / len(amounts) > 0.7
            else "negative_is_spend"
        )
    mapping.setdefault("sign", "negative_is_spend")

    # Preview exactly what would be imported, so the sign can be eyeballed.
    preview, problems = _convert(records[:10], mapping)

    return {
        "filename": filename,
        "delimiter": delimiter,
        "header_row": header_idx,
        "headers": headers,
        "row_count": len(records),
        "detected_preset": preset_name,
        "detected_preset_label": PRESETS[preset_name]["label"] if preset_name else None,
        "mapping": mapping,
        "sample_raw": records[:5],
        "sample_parsed": preview,
        "problems": problems[:5],
        "presets": [{"id": k, "label": v["label"]} for k, v in PRESETS.items()],
    }


def _convert(records: list[dict], mapping: dict) -> tuple[list[dict], list[str]]:
    """Map raw rows to canonical transactions, collecting per-row problems."""
    out: list[dict] = []
    problems: list[str] = []
    flip = mapping.get("sign") == "positive_is_spend"

    date_col = mapping.get("date")
    desc_col = mapping.get("description")
    amount_col = mapping.get("amount")
    debit_col, credit_col = mapping.get("debit"), mapping.get("credit")

    if not date_col:
        raise ValueError("No date column was identified — pick one and retry.")
    if not amount_col and not (debit_col or credit_col):
        raise ValueError("No amount column was identified — pick one and retry.")

    for i, r in enumerate(records, start=1):
        iso = parse_date(r.get(date_col))
        if not iso:
            problems.append(f"Row {i}: could not read the date {r.get(date_col)!r}.")
            continue

        if amount_col:
            amount = parse_amount(r.get(amount_col))
        else:
            # Separate debit/credit columns: a debit is always an outflow.
            debit = parse_amount(r.get(debit_col)) if debit_col else None
            credit = parse_amount(r.get(credit_col)) if credit_col else None
            if debit:
                amount = -abs(debit)
            elif credit:
                amount = abs(credit)
            else:
                amount = None
        if amount is None:
            problems.append(f"Row {i}: could not read the amount.")
            continue
        if flip:
            amount = -amount

        description = (r.get(desc_col) or "").strip() if desc_col else ""
        merchant = (r.get(mapping["merchant"]) or "").strip() if mapping.get("merchant") else None
        category = (r.get(mapping["category"]) or "").strip() if mapping.get("category") else None

        out.append({
            "date": iso,
            "amount": round(amount, 2),
            "description": description or merchant or "Imported transaction",
            "provider_merchant": merchant or None,
            "raw_category": category or None,
        })
    return out, problems


def parse(content: bytes, mapping: dict) -> tuple[list[dict], list[str]]:
    """Full parse of an upload under a confirmed mapping."""
    text = content.decode("utf-8-sig", errors="replace")
    delimiter = mapping.get("delimiter") or ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter)
            if any(c.strip() for c in r)]
    if not rows:
        return [], ["The file is empty."]

    header_idx = mapping.get("header_row")
    if header_idx is None:
        header_idx = _find_header_row(rows)
    headers = [h.strip() for h in rows[header_idx]]
    records = [dict(zip(headers, r)) for r in rows[header_idx + 1:]
               if len(r) >= len(headers) - 1]
    return _convert(records, mapping)
