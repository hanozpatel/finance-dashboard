"""The bridge the web build uses to run this backend inside a browser.

Pyodide itself is exercised by the end-to-end browser test, not here. What is
pinned here is everything the bridge decides on its own: that a request goes
through the real ASGI app intact, that writes land, that multipart uploads
survive the trip, that "start fresh" really starts empty, and that the backup
is a genuine SQLite file.

Each case runs in a subprocess, because importing the bridge patches FastAPI's
threadpool process-wide — correct in a browser, and not something the rest of
the suite should inherit.
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(body: str) -> dict:
    db_path = os.path.join(tempfile.mkdtemp(prefix="finance-bridge-"), "finance.db")
    script = textwrap.dedent(f"""
        import asyncio, json, sys
        sys.path.insert(0, {BACKEND!r})
        import browser_bridge
        call = lambda *a: asyncio.run(browser_bridge.handle(*a))
        out = {{}}
    """) + textwrap.dedent(body) + "\nprint(json.dumps(out))\n"
    env = {**os.environ, "FINANCE_DB_PATH": db_path, "FINANCE_JOURNAL_MODE": "MEMORY",
           "PLAID_CLIENT_ID": "", "PLAID_SECRET": "",
           "SNAPTRADE_CLIENT_ID": "", "SNAPTRADE_CONSUMER_KEY": ""}
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          env=env, cwd=BACKEND, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_first_visit_gets_the_demo_and_requests_work():
    out = _run("""
        out["start"] = browser_bridge.start()
        status, headers, body = call("GET", "/api/health", "", [], b"")
        out["status"] = status
        out["health"] = json.loads(body)
        out["json"] = any(k == "content-type" and "json" in v for k, v in headers)
    """)
    assert out["start"]["is_demo"] is True and out["start"]["transactions"] > 1000
    assert out["status"] == 200 and out["json"]
    assert out["health"]["is_demo"] is True


def test_query_strings_and_writes_go_through_the_real_app():
    out = _run("""
        browser_bridge.start()
        s, _, b = call("GET", "/api/transactions", "search=starbucks&limit=3", [], b"")
        out["search"] = (s, json.loads(b)["total_count"], len(json.loads(b)["transactions"]))
        s, _, b = call("PUT", "/api/budget/settings", "", [("content-type", "application/json")],
                       json.dumps({"state": "TX", "household_size": 2}).encode())
        out["write"] = s
        s, _, b = call("GET", "/api/budget/settings", "", [], b"")
        out["after"] = json.loads(b)["state"]
        s, _, b = call("PUT", "/api/budget/settings", "", [("content-type", "application/json")],
                       json.dumps({"state": "ZZ"}).encode())
        out["bad"] = (s, json.loads(b)["detail"])
    """)
    status, total, page = out["search"]
    assert status == 200 and total > 3 and page == 3
    assert out["write"] == 200 and out["after"] == "TX"
    assert out["bad"][0] == 400 and "not a state" in out["bad"][1]


def test_a_csv_upload_survives_the_trip():
    """Multipart bodies are built by the browser and must parse unchanged."""
    out = _run("""
        browser_bridge.start()
        boundary = "----bridgetest"
        csv = b"Date,Description,Amount\\n10/01/2026,LOCAL BAKERY,-12.50\\n10/02/2026,PAYROLL,2400.00\\n"
        body = (f"--{boundary}\\r\\nContent-Disposition: form-data; name=\\"file\\"; filename=\\"bank.csv\\"\\r\\n"
                f"Content-Type: text/csv\\r\\n\\r\\n").encode() + csv + f"\\r\\n--{boundary}--\\r\\n".encode()
        s, _, b = call("POST", "/api/imports/preview", "",
                       [("content-type", f"multipart/form-data; boundary={boundary}")], body)
        out["preview"] = (s, json.loads(b).get("row_count"))
    """)
    assert out["preview"] == [200, 2]


def test_starting_fresh_after_a_delete_does_not_reseed_the_demo():
    out = _run("""
        out["start"] = browser_bridge.start(fresh=True)
    """)
    assert out["start"] == {"accounts": 0, "transactions": 0, "is_demo": False}


def test_the_backup_is_a_real_sqlite_database():
    out = _run("""
        browser_bridge.start()
        data = browser_bridge.export_database()
        out["header"] = data[:15].decode()
        out["size"] = len(data)
    """)
    assert out["header"] == "SQLite format 3"
    assert out["size"] > 100_000


def test_bank_providers_are_off_in_the_browser():
    """Plaid and SnapTrade need a server holding secret keys; none exists here."""
    out = _run("""
        browser_bridge.start()
        s, _, b = call("GET", "/api/connections/providers", "", [], b"")
        p = json.loads(b)
        out["plaid"] = p["plaid"]["configured"]
        out["snaptrade"] = p["snaptrade"]["configured"]
    """)
    assert out["plaid"] is False and out["snaptrade"] is False
