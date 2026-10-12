"""Plaid client — every linked institution now goes through here.

Banks and cards connect through Plaid (Teller filled this role until it
withdrew its API in July 2026). Plaid's Trial plan — auto-approved for most
signups since 15 April 2026 — covers up to 10 Production Items and includes both
the ``transactions`` and ``investments`` products, which is ample for one
household's banks and cards.

Four Plaid-specific facts shape this module.

*Products are fixed at link time.* An Item created with ``transactions`` cannot
later be asked for holdings, so the link token is built per *kind* of
institution (``bank`` or ``investments``) and the choice is recorded on the
connection so syncing knows which endpoints the Item will answer.

*Signs are inverted from this app's convention.* Plaid reports an outflow as a
positive amount and a credit card's balance as a positive amount owed. Both are
flipped here, once, so nothing downstream carries a provider branch.

*``/transactions/sync`` is a cursor, not a date range.* The first call returns
the Item's whole history; later calls return only what changed, including
corrections and deletions. The cursor is stored per connection.

*Holdings and securities arrive as two parallel lists* joined on
``security_id`` — that join happens here.
"""

from __future__ import annotations

import os
import time
from datetime import date, timedelta

# Imported lazily so a missing or broken plaid install degrades to "not
# configured" instead of taking down the whole API at startup.
_IMPORT_ERROR: str | None = None
try:
    import plaid
    from plaid.api import plaid_api
    from plaid.model.accounts_get_request import AccountsGetRequest
    from plaid.model.country_code import CountryCode
    from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
    from plaid.model.investments_transactions_get_request import (
        InvestmentsTransactionsGetRequest,
    )
    from plaid.model.item_public_token_exchange_request import (
        ItemPublicTokenExchangeRequest,
    )
    from plaid.model.link_token_create_request import LinkTokenCreateRequest
    from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
    from plaid.model.link_token_transactions import LinkTokenTransactions
    from plaid.model.products import Products
    from plaid.model.transactions_sync_request import TransactionsSyncRequest
except Exception as e:  # pragma: no cover - exercised only on a broken install
    _IMPORT_ERROR = f"{type(e).__name__}: {e}"


# What each kind of link asks Plaid for. A bank Item and a brokerage Item are
# separate Items even at the same institution, because the product set is
# immutable once the Item exists.
LINK_KINDS = {
    "bank": {
        "products": ["transactions"],
        "label": "Bank or credit card",
        "purpose": "Checking, savings, and credit cards",
    },
    "investments": {
        "products": ["investments"],
        "label": "Brokerage",
        "purpose": "Brokerage holdings and investment activity",
    },
}

# How much history to ask for on a bank link. Plaid defaults to 90 days unless
# asked; the app's trends and recurring detection want considerably more, and
# the banks themselves cap it at whatever they expose (usually 12-24 months).
TRANSACTION_DAYS_REQUESTED = 730


class PlaidError(RuntimeError):
    pass


class PlaidNotReady(PlaidError):
    """Plaid has the Item but is still pulling its first batch of history."""


def config() -> dict:
    return {
        "client_id": os.getenv("PLAID_CLIENT_ID", "").strip(),
        "secret": os.getenv("PLAID_SECRET", "").strip(),
        "env": os.getenv("PLAID_ENV", "sandbox").strip().lower() or "sandbox",
    }


def is_configured() -> bool:
    c = config()
    return _IMPORT_ERROR is None and bool(c["client_id"] and c["secret"])


def configuration_problem() -> str | None:
    if _IMPORT_ERROR:
        return f"The plaid package failed to import ({_IMPORT_ERROR})."
    c = config()
    if not c["client_id"] or not c["secret"]:
        return "PLAID_CLIENT_ID and PLAID_SECRET are not set."
    if c["env"] not in ("sandbox", "development", "production"):
        return f"PLAID_ENV must be sandbox, development, or production (got '{c['env']}')."
    return None


def _host() -> str:
    env = config()["env"]
    mapping = {
        "sandbox": plaid.Environment.Sandbox,
        "production": plaid.Environment.Production,
    }
    # Plaid retired the shared Development environment; keep it working for
    # anyone whose account still has it rather than failing outright.
    if env == "development" and hasattr(plaid.Environment, "Development"):
        return plaid.Environment.Development
    return mapping.get(env, plaid.Environment.Sandbox)


def _api():
    problem = configuration_problem()
    if problem:
        raise PlaidError(problem)
    c = config()
    configuration = plaid.Configuration(
        host=_host(),
        api_key={"clientId": c["client_id"], "secret": c["secret"]},
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


def _error_code(e: Exception) -> str:
    """Plaid's machine-readable error code, or '' if this isn't a Plaid error."""
    body = getattr(e, "body", None)
    if not body:
        return ""
    text = str(body)
    for code in ("PRODUCT_NOT_READY", "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION",
                 "ITEM_LOGIN_REQUIRED", "INVALID_ACCESS_TOKEN", "PRODUCTS_NOT_SUPPORTED"):
        if code in text:
            return code
    return ""


def _unwrap(e: Exception) -> PlaidError:
    """Plaid puts the useful message in the response body, not the exception."""
    code = _error_code(e)
    if code == "ITEM_LOGIN_REQUIRED":
        return PlaidError(
            "The institution requires you to log in again. Re-link this "
            "connection from the Accounts tab."
        )
    body = getattr(e, "body", None)
    if body:
        return PlaidError(f"Plaid error: {str(body)[:400]}")
    return PlaidError(f"Plaid error: {type(e).__name__}: {e}")


# --------------------------------------------------------------------------
# Linking
# --------------------------------------------------------------------------

def create_link_token(kind: str = "bank", user_id: str = "finance-dashboard-local") -> str:
    """A short-lived token the browser hands to Plaid Link.

    Only the products that ``kind`` needs are requested, so linking a checking
    account never asks for brokerage consent and vice versa.
    """
    spec = LINK_KINDS.get(kind)
    if not spec:
        raise PlaidError(
            f"Unknown link kind '{kind}'. Expected one of: {', '.join(LINK_KINDS)}."
        )
    try:
        kwargs = dict(
            user=LinkTokenCreateRequestUser(client_user_id=user_id),
            client_name="Finance Dashboard",
            products=[Products(p) for p in spec["products"]],
            country_codes=[CountryCode("US")],
            language="en",
        )
        if "transactions" in spec["products"]:
            kwargs["transactions"] = LinkTokenTransactions(
                days_requested=TRANSACTION_DAYS_REQUESTED
            )
        return _api().link_token_create(LinkTokenCreateRequest(**kwargs)).to_dict()["link_token"]
    except PlaidError:
        raise
    except Exception as e:
        raise _unwrap(e) from e


def exchange_public_token(public_token: str) -> dict:
    try:
        resp = _api().item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=public_token)
        ).to_dict()
        return {"access_token": resp["access_token"], "item_id": resp["item_id"]}
    except PlaidError:
        raise
    except Exception as e:
        raise _unwrap(e) from e


# --------------------------------------------------------------------------
# Normalisation — pure, so the sign conventions are testable without a network
# --------------------------------------------------------------------------

# Plaid's account types against the three this app stores. A loan is a
# liability and shares every behaviour with a card here, so it lands in
# ``credit``; the Plaid subtype is kept verbatim either way.
_TYPE_MAP = {
    "depository": "depository",
    "credit": "credit",
    "loan": "credit",
    "investment": "investment",
    "brokerage": "investment",  # legacy spelling, still returned by some Items
}


def normalize_account(a: dict, institution: str) -> dict:
    """One Plaid account in the app's shape, with balances already signed.

    Plaid reports a credit card's ``current`` as the amount owed, positive. The
    app stores liabilities negative, so cards and loans are forced to
    ``-abs(current)`` no matter how the institution signed it.
    """
    balances = a.get("balances") or {}
    raw_type = str(a.get("type") or "depository").lower()
    account_type = _TYPE_MAP.get(raw_type, "depository")
    current = balances.get("current")
    available = balances.get("available")
    limit = balances.get("limit")

    if account_type == "credit":
        owed = abs(current or 0.0)
        balance_current = -owed
        # Plaid usually reports the limit directly. When it doesn't, a card's
        # "available" is the remaining credit, so the limit is owed plus left.
        credit_limit = limit if limit is not None else (
            owed + available if available is not None else None
        )
    else:
        balance_current = current or 0.0
        credit_limit = limit

    return {
        "provider_account_id": a["account_id"],
        "institution": institution,
        "name": a.get("official_name") or a.get("name") or "Account",
        "mask": a.get("mask"),
        "type": account_type,
        "subtype": str(a["subtype"]) if a.get("subtype") else None,
        "currency": balances.get("iso_currency_code") or "USD",
        "balance_current": round(balance_current, 2),
        "balance_available": round(available, 2) if available is not None else None,
        "credit_limit": round(credit_limit, 2) if credit_limit is not None else None,
    }


def normalize_transaction(t: dict) -> dict:
    """One Plaid transaction in the app's shape.

    The sign flip is the important part: Plaid reports money *leaving* the
    account as a positive amount, which is the opposite of this app's
    convention, and getting it backwards would invert every spending chart.
    """
    category = None
    pfc = t.get("personal_finance_category") or {}
    if pfc.get("primary"):
        category = str(pfc["primary"]).replace("_", " ").title()
    elif t.get("category"):
        category = str(t["category"][0])

    return {
        "provider_txn_id": t["transaction_id"],
        "provider_account_id": t.get("account_id"),
        # Plaid: outflow positive. Here: outflow negative.
        "amount": round(-float(t.get("amount") or 0.0), 2),
        "date": str(t.get("date") or "")[:10],
        "description": t.get("name") or t.get("merchant_name") or "Transaction",
        "provider_merchant": t.get("merchant_name"),
        "raw_category": category,
        "pending": 1 if t.get("pending") else 0,
    }


# --------------------------------------------------------------------------
# Reading an Item
# --------------------------------------------------------------------------

def list_accounts(access_token: str, institution: str | None = None) -> list[dict]:
    """Every account on the Item, with balances.

    ``/accounts/get`` returns Plaid's cached balances, which refresh on Plaid's
    own schedule. That is deliberate: ``/accounts/balance/get`` forces a live
    call to the bank and is billed per call, and a dashboard that syncs on every
    page load does not need to pay for that.
    """
    try:
        resp = _api().accounts_get(AccountsGetRequest(access_token=access_token)).to_dict()
    except PlaidError:
        raise
    except Exception as e:
        raise _unwrap(e) from e

    name = institution or (resp.get("item", {}).get("institution_name")) or "Unknown institution"
    return [normalize_account(a, name) for a in resp.get("accounts", [])]


def sync_transactions(access_token: str, cursor: str | None = None) -> dict:
    """Everything that changed on the Item since ``cursor``.

    Returns added and modified transactions already normalised, the ids of
    transactions the bank retracted, and the cursor to store for next time. With
    no cursor this is the Item's entire available history.
    """
    api = _api()
    start_cursor = cursor

    # Plaid invalidates a pagination run if the underlying data changes mid-way
    # and expects the whole run to restart from the cursor it began with.
    for attempt in range(3):
        added: list[dict] = []
        modified: list[dict] = []
        removed: list[str] = []
        next_cursor = start_cursor
        try:
            while True:
                kwargs = {"access_token": access_token, "count": 500}
                if next_cursor:
                    kwargs["cursor"] = next_cursor
                resp = api.transactions_sync(TransactionsSyncRequest(**kwargs)).to_dict()
                added.extend(normalize_transaction(t) for t in resp.get("added", []))
                modified.extend(normalize_transaction(t) for t in resp.get("modified", []))
                removed.extend(
                    r["transaction_id"] for r in resp.get("removed", [])
                    if r.get("transaction_id")
                )
                next_cursor = resp.get("next_cursor") or next_cursor
                if not resp.get("has_more"):
                    break
            return {"added": added, "modified": modified, "removed": removed,
                    "cursor": next_cursor}
        except Exception as e:
            code = _error_code(e)
            if code == "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION" and attempt < 2:
                continue
            if code == "PRODUCT_NOT_READY":
                # Plaid is still doing the initial pull. It usually takes a few
                # seconds, so wait briefly rather than failing the whole link.
                if attempt < 2:
                    time.sleep(4)
                    continue
                raise PlaidNotReady(
                    "Plaid is still fetching this institution's history. The "
                    "connection is saved — press Sync again in a minute."
                ) from e
            raise _unwrap(e) from e

    raise PlaidError("Plaid kept changing the transaction feed mid-sync. Try again.")


def get_holdings(access_token: str) -> list[dict]:
    """Holdings joined to their securities, priced and valued."""
    try:
        resp = _api().investments_holdings_get(
            InvestmentsHoldingsGetRequest(access_token=access_token)
        ).to_dict()
    except PlaidError:
        raise
    except Exception as e:
        raise _unwrap(e) from e

    securities = {s["security_id"]: s for s in resp.get("securities", [])}
    out = []
    for h in resp.get("holdings", []):
        sec = securities.get(h.get("security_id"), {})
        quantity = h.get("quantity") or 0.0
        price = h.get("institution_price") or sec.get("close_price") or 0.0
        value = h.get("institution_value")
        if value is None:
            value = quantity * price
        out.append({
            "provider_account_id": h.get("account_id"),
            "symbol": sec.get("ticker_symbol"),
            "name": sec.get("name") or sec.get("ticker_symbol") or "Unknown security",
            "security_type": sec.get("type"),
            "quantity": quantity,
            "price": price,
            "value": round(value, 2),
            "cost_basis": h.get("cost_basis"),
        })
    return out


def get_investment_transactions(access_token: str, days: int = 730) -> list[dict]:
    """Buys, sells, dividends, and fees over the requested window.

    Plaid caps each response at 500 rows and reports the true total, so the
    offset loop is driven by that total rather than by a short page.
    """
    end = date.today()
    start = end - timedelta(days=days)
    api = _api()
    collected: list[dict] = []
    offset, total = 0, None

    try:
        while total is None or offset < total:
            from plaid.model.investments_transactions_get_request_options import (
                InvestmentsTransactionsGetRequestOptions,
            )
            resp = api.investments_transactions_get(
                InvestmentsTransactionsGetRequest(
                    access_token=access_token,
                    start_date=start,
                    end_date=end,
                    options=InvestmentsTransactionsGetRequestOptions(
                        count=500, offset=offset
                    ),
                )
            ).to_dict()
            total = resp.get("total_investment_transactions", 0)
            batch = resp.get("investment_transactions", [])
            if not batch:
                break
            securities = {s["security_id"]: s for s in resp.get("securities", [])}
            for t in batch:
                sec = securities.get(t.get("security_id"), {})
                collected.append({
                    "provider_txn_id": t["investment_transaction_id"],
                    "provider_account_id": t.get("account_id"),
                    "date": str(t.get("date"))[:10],
                    "symbol": sec.get("ticker_symbol"),
                    "name": t.get("name") or sec.get("name") or "Investment transaction",
                    "type": t.get("type"),
                    "subtype": t.get("subtype"),
                    "quantity": t.get("quantity"),
                    "price": t.get("price"),
                    "amount": t.get("amount"),
                    "fees": t.get("fees"),
                })
            offset += len(batch)
    except PlaidError:
        raise
    except Exception as e:
        raise _unwrap(e) from e

    return collected
