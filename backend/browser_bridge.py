"""Run the API inside a web browser, with no server.

The GitHub Pages build of the app loads this module into Pyodide — CPython
compiled to WebAssembly — and sends every API request straight into the FastAPI
app as an ASGI call. Nothing goes over a network: the "backend" is a function
call in the same browser tab, and the database is a SQLite file in that
browser's own storage. Nobody, including whoever hosts the page, can see it.

Two things differ from a normal server, and both are handled here so the rest
of the codebase does not know it is in a browser:

* **There are no threads.** FastAPI runs ``def`` endpoints in a threadpool;
  Pyodide cannot start threads. Since a browser tab is single-threaded anyway,
  those calls are run inline instead.
* **Persistence is explicit.** The database lives in Emscripten's IndexedDB
  filesystem, which only reaches disk when the page asks it to. The JavaScript
  side syncs after every request that can write.

What does *not* work here, by design: Plaid and SnapTrade. Both require a server
holding secret API keys, and Plaid refuses calls made from a browser. The
in-browser app imports bank CSV exports instead; the installable version keeps
automatic sync.
"""

from __future__ import annotations

import os

# Before the app is imported: where the data lives, and how SQLite journals it.
os.environ.setdefault("FINANCE_DB_PATH", "/data/finance.db")
os.environ.setdefault("FINANCE_JOURNAL_MODE", "MEMORY")
os.environ.setdefault("FINANCE_RUNTIME", "browser")
for _var in ("PLAID_CLIENT_ID", "PLAID_SECRET", "SNAPTRADE_CLIENT_ID", "SNAPTRADE_CONSUMER_KEY"):
    os.environ.setdefault(_var, "")


async def _inline(func, *args, **kwargs):
    """Stand-in for run_in_threadpool: a browser tab has one thread."""
    return func(*args, **kwargs)


def _patch_threadpools() -> None:
    import fastapi.concurrency
    import fastapi.dependencies.utils
    import fastapi.routing
    import starlette.concurrency
    import starlette.datastructures

    for module in (starlette.concurrency, starlette.datastructures, fastapi.concurrency,
                   fastapi.routing, fastapi.dependencies.utils):
        if hasattr(module, "run_in_threadpool"):
            module.run_in_threadpool = _inline


_patch_threadpools()

import db  # noqa: E402
import main  # noqa: E402

_started = False


def start(fresh: bool = False) -> dict:
    """Create the schema and, on a genuinely first visit, the demo data.

    ``fresh`` is set after "delete all my data": the visitor asked for an empty
    app, and re-seeding the demo the moment they reload would undo that.
    """
    global _started
    os.makedirs(os.path.dirname(db.DB_PATH), exist_ok=True)
    db.init_db()
    if fresh and not db.get_setting("initialized"):
        db.set_setting("initialized", "1")
    if not _started:
        main._first_run_seed()
        _started = True
    return {
        "accounts": db.query_one("SELECT COUNT(*) AS n FROM accounts")["n"],
        "transactions": db.query_one("SELECT COUNT(*) AS n FROM transactions")["n"],
        "is_demo": db.get_setting("is_demo") == "1",
    }


async def handle(method: str, path: str, query: str, headers: list, body: bytes) -> tuple:
    """One HTTP request through the ASGI app; returns (status, headers, body)."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": [(str(k).lower().encode("latin-1"), str(v).encode("latin-1")) for k, v in headers],
        "client": ("127.0.0.1", 0),
        "server": ("localhost", 80),
    }
    pending = [{"type": "http.request", "body": bytes(body or b""), "more_body": False}]

    async def receive():
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    response = {"status": 500, "headers": [], "body": []}

    async def send(message):
        if message["type"] == "http.response.start":
            response["status"] = message["status"]
            response["headers"] = [(k.decode("latin-1"), v.decode("latin-1"))
                                   for k, v in message.get("headers", [])]
        elif message["type"] == "http.response.body":
            response["body"].append(message.get("body", b""))

    await main.app(scope, receive, send)
    return response["status"], response["headers"], b"".join(response["body"])


def export_database() -> bytes:
    """The whole database as bytes, for the in-app backup download."""
    conn = db.connect()
    conn.commit()
    with open(db.DB_PATH, "rb") as fh:
        return fh.read()
