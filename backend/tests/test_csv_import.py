"""CSV import against the real export shapes of each institution.

The Apple Card cases matter most: its export signs purchases *positive*, so a
wrong guess here would invert every expense in the app.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services import csv_service as c


APPLE_CARD = b'''Transaction Date,Clearing Date,Description,Merchant,Category,Type,Amount (USD),Purchased By
09/08/2026,09/09/2026,BLUE BOTTLE COFFEE,Blue Bottle Coffee,Restaurants,Purchase,6.75,Alex
09/05/2026,09/06/2026,WHOLE FOODS MKT,Whole Foods,Grocery,Purchase,112.40,Alex
09/02/2026,09/02/2026,ACH Deposit Internet transfer from account,,Payment,Payment,-450.00,Alex
'''

CHASE = b'''Transaction Date,Post Date,Description,Category,Type,Amount,Memo
09/08/2026,09/09/2026,NETFLIX.COM,Entertainment,Sale,-22.99,
09/06/2026,09/07/2026,TRADER JOE S #123,Groceries,Sale,-84.21,
09/01/2026,09/01/2026,Payment Thank You - Mobile,,Payment,1250.00,
'''

BOFA_WITH_PREAMBLE = b'''Description,,Summary Amt.
Beginning balance as of 09/01/2026,,"4,210.55"
Total credits,,"6,000.00"

Date,Description,Amount,Running Bal.
09/08/2026,"CHECKCARD 0908 SAFEWAY #1234 SAN FRANCISCO CA",-64.18,"4,146.37"
09/05/2026,"ACME CORP DES:PAYROLL DIRECT DEP","3,000.00","7,146.37"
09/03/2026,"Zelle payment to Sam",-200.00,"4,210.55"
'''

DEBIT_CREDIT_COLUMNS = b'''Date,Description,Debit,Credit
09/08/2026,COSTCO WHOLESALE,214.55,
09/04/2026,REFUND - RETURNED ITEM,,45.00
'''


def test_apple_card_preset_detected_and_signs_inverted():
    s = c.sniff(APPLE_CARD, "apple.csv")
    assert s["detected_preset"] == "apple_card"
    assert s["mapping"]["sign"] == "positive_is_spend"
    assert s["mapping"]["date"] == "Transaction Date"   # not Clearing Date
    assert s["row_count"] == 3

    rows, problems = c.parse(APPLE_CARD, {**s["mapping"], "header_row": s["header_row"]})
    assert problems == []
    coffee = next(r for r in rows if "BLUE BOTTLE" in r["description"])
    # A $6.75 purchase must land as an outflow.
    assert coffee["amount"] == -6.75
    assert coffee["date"] == "2026-09-08"
    assert coffee["provider_merchant"] == "Blue Bottle Coffee"
    # ...and the card payment as an inflow to the card.
    payment = next(r for r in rows if r["raw_category"] == "Payment")
    assert payment["amount"] == 450.00


def test_chase_preset_keeps_native_signs():
    s = c.sniff(CHASE, "chase.csv")
    assert s["detected_preset"] == "chase"
    assert s["mapping"]["sign"] == "negative_is_spend"
    rows, problems = c.parse(CHASE, {**s["mapping"], "header_row": s["header_row"]})
    assert problems == []
    assert next(r for r in rows if "NETFLIX" in r["description"])["amount"] == -22.99
    assert next(r for r in rows if "Payment Thank" in r["description"])["amount"] == 1250.00


def test_header_row_found_past_a_preamble():
    s = c.sniff(BOFA_WITH_PREAMBLE, "bofa.csv")
    assert s["headers"] == ["Date", "Description", "Amount", "Running Bal."]
    # Blank lines are dropped before indexing, so this is the index into the
    # filtered rows — the only contract that matters is that parse() agrees.
    assert s["header_row"] == 3
    assert s["row_count"] == 3
    rows, problems = c.parse(BOFA_WITH_PREAMBLE,
                             {**s["mapping"], "header_row": s["header_row"]})
    assert problems == []
    assert next(r for r in rows if "SAFEWAY" in r["description"])["amount"] == -64.18
    # Quoted thousands separators must survive.
    assert next(r for r in rows if "PAYROLL" in r["description"])["amount"] == 3000.00


def test_separate_debit_and_credit_columns():
    s = c.sniff(DEBIT_CREDIT_COLUMNS, "split.csv")
    rows, problems = c.parse(DEBIT_CREDIT_COLUMNS,
                             {**s["mapping"], "header_row": s["header_row"]})
    assert problems == []
    assert next(r for r in rows if "COSTCO" in r["description"])["amount"] == -214.55
    assert next(r for r in rows if "REFUND" in r["description"])["amount"] == 45.00


def test_amount_formats_banks_actually_use():
    assert c.parse_amount("$1,234.56") == 1234.56
    assert c.parse_amount("(12.34)") == -12.34     # accounting negative
    assert c.parse_amount("-$5.00") == -5.00
    assert c.parse_amount("+250") == 250.0
    assert c.parse_amount("") is None
    assert c.parse_amount("-") is None
    assert c.parse_amount("n/a") is None
    assert c.parse_amount(None) is None


def test_date_formats():
    assert c.parse_date("2026-09-08") == "2026-09-08"
    assert c.parse_date("09/08/2026") == "2026-09-08"
    assert c.parse_date("9/8/26") == "2026-09-08"
    assert c.parse_date("Sep 8, 2026") == "2026-09-08"
    assert c.parse_date("garbage") is None


def test_unparseable_rows_are_reported_not_dropped_silently():
    broken = b'''Date,Description,Amount
not-a-date,SOMETHING,-10.00
09/08/2026,FINE,-20.00
09/09/2026,NO AMOUNT,
'''
    s = c.sniff(broken, "broken.csv")
    rows, problems = c.parse(broken, {**s["mapping"], "header_row": s["header_row"]})
    assert len(rows) == 1 and rows[0]["description"] == "FINE"
    assert len(problems) == 2
    assert any("date" in p for p in problems)
    assert any("amount" in p for p in problems)


def test_empty_file_raises_clearly():
    with pytest.raises(ValueError, match="empty"):
        c.sniff(b"", "empty.csv")


def test_missing_amount_column_raises_actionable_error():
    with pytest.raises(ValueError, match="amount column"):
        c.parse(b"Date,Notes\n09/08/2026,hello\n", {"date": "Date", "header_row": 0})


def test_semicolon_delimiter():
    data = b'Date;Description;Amount\n09/08/2026;SOME SHOP;-12,00\n'
    s = c.sniff(data, "eu.csv")
    assert s["delimiter"] == ";"
