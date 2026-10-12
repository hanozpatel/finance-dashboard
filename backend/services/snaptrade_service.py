"""SnapTrade client — brokerage accounts Plaid will not give us.

Robinhood publishes no developer API of its own, and the unofficial libraries
want a password and an MFA seed. Plaid's investments product is the usual
answer and did not work here, so this is the second route: SnapTrade
specialises in brokerages, connects Robinhood over OAuth read-only, and its
Personal tier is free for one household with no business registration.

Three things about SnapTrade shape this module.

*There are two key types, and they work differently.* A **Personal** key (the
free tier, ids prefixed ``PERS-``) *is* the user: there is nobody to register,
and no call takes a user id or secret. A **Commercial** key identifies an
application whose end users are registered separately, each getting a
(userId, userSecret) pair — this app would have exactly one, registered once
and encrypted into the settings table.

Calling the commercial flow with a personal key fails with a bare 403 and the
message "Authentication credentials were not provided", because
``registerSnapTradeUser`` does not accept personal keys at all. So the mode is
decided up front and every call is shaped to it.

*Linking happens on SnapTrade's own page.* There is no embeddable widget: the
API returns a one-time portal URL, the browser opens it, and the brokerage
login happens there. Nothing comes back to us automatically, so the accounts
are imported on return rather than pushed.

*Positions are per share.* ``average_purchase_price`` is the cost of one share,
where this app stores the cost basis of the whole position, so it is multiplied
out here rather than downstream.
"""

from __future__ import annotations

import decimal
import os
from collections.abc import Mapping

import db
from services import crypto_service

_IMPORT_ERROR: str | None = None
try:
    from snaptrade_client import SnapTrade, SnapTradeAuth
except Exception as e:  # pragma: no cover - exercised only on a broken install
    _IMPORT_ERROR = f"{type(e).__name__}: {e}"

# Where the SnapTrade-issued identity lives. The user id is ours to choose; the
# secret is SnapTrade's and is encrypted with everything else.
_USER_ID_KEY = "snaptrade_user_id"
_USER_SECRET_KEY = "snaptrade_user_secret_enc"
DEFAULT_USER_ID = "finance-dashboard-local"

PERSONAL = "personal"
COMMERCIAL = "commercial"

# SnapTrade prefixes personal client ids. The prefix is the only thing that
# distinguishes the two key types from the outside, so SNAPTRADE_MODE exists as
# an override for anyone whose id does not follow it.
_PERSONAL_ID_PREFIX = "PERS"


def auth_mode() -> str:
    explicit = os.getenv("SNAPTRADE_MODE", "").strip().lower()
    if explicit in (PERSONAL, COMMERCIAL):
        return explicit
    return PERSONAL if config()["client_id"].upper().startswith(_PERSONAL_ID_PREFIX) else COMMERCIAL


class SnapTradeError(RuntimeError):
    pass


def config() -> dict:
    return {
        "client_id": os.getenv("SNAPTRADE_CLIENT_ID", "").strip(),
        "consumer_key": os.getenv("SNAPTRADE_CONSUMER_KEY", "").strip(),
    }


def is_configured() -> bool:
    c = config()
    return _IMPORT_ERROR is None and bool(c["client_id"] and c["consumer_key"])


def configuration_problem() -> str | None:
    if _IMPORT_ERROR:
        return f"The snaptrade-python-sdk package failed to import ({_IMPORT_ERROR})."
    c = config()
    if not c["client_id"] or not c["consumer_key"]:
        return "SNAPTRADE_CLIENT_ID and SNAPTRADE_CONSUMER_KEY are not set."
    return None


def _client():
    problem = configuration_problem()
    if problem:
        raise SnapTradeError(problem)
    c = config()
    issue = (SnapTradeAuth.personal_api_key if auth_mode() == PERSONAL
             else SnapTradeAuth.commercial_api_key)
    return SnapTrade(auth=issue(consumer_key=c["consumer_key"], client_id=c["client_id"]))


def _user_kwargs() -> dict:
    """The user identity to sign a call with — nothing at all, on a personal key.

    A personal key authenticates as the person who owns it. Passing a user id
    and secret alongside one is not merely redundant, it selects the commercial
    security scheme and the request is rejected.
    """
    if auth_mode() == PERSONAL:
        return {}
    user_id, secret = ensure_user()
    return {"user_id": user_id, "user_secret": secret}


def _plain(value):
    """Plain Python out of the SDK's schema objects.

    Responses come back as frozendict and Decimal subclasses that look like
    dicts and numbers until something tries to store or serialise them.
    """
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, (int, float)):
        return value
    return str(value)


def _body(response) -> object:
    return _plain(getattr(response, "body", response))


def _fail(e: Exception) -> SnapTradeError:
    """SnapTrade puts the reason in the response body, not the exception."""
    body = getattr(e, "body", None) or getattr(e, "reason", None)
    if body:
        return SnapTradeError(f"SnapTrade error: {str(body)[:400]}")
    return SnapTradeError(f"SnapTrade error: {type(e).__name__}: {e}")


# --------------------------------------------------------------------------
# The one user
# --------------------------------------------------------------------------

def is_ready() -> bool:
    """Whether calls can be made — a personal key needs no setup beyond itself."""
    if not is_configured():
        return False
    return auth_mode() == PERSONAL or registered_user() is not None


def registered_user() -> tuple[str, str] | None:
    """The stored (user_id, user_secret), or None if we have not registered."""
    user_id = db.get_setting(_USER_ID_KEY)
    secret = db.get_setting(_USER_SECRET_KEY)
    if not user_id or not secret:
        return None
    return user_id, crypto_service.decrypt(secret)


def ensure_user() -> tuple[str, str]:
    """Register with SnapTrade once, then reuse that identity forever.

    Commercial keys only. Re-registering the same id would issue a new secret
    and orphan every brokerage connection made under the old one, so an
    existing registration is always preferred over a fresh one.
    """
    if auth_mode() == PERSONAL:
        raise SnapTradeError(
            "A personal key is already a user; registration is a commercial-key step."
        )
    existing = registered_user()
    if existing:
        return existing

    try:
        response = _client().authentication.register_snap_trade_user(
            body={"userId": DEFAULT_USER_ID}
        )
    except Exception as e:
        raise _fail(e) from e

    payload = _body(response)
    user_id = payload.get("userId") or DEFAULT_USER_ID
    secret = payload.get("userSecret")
    if not secret:
        raise SnapTradeError("SnapTrade registered the user but returned no secret.")

    db.set_setting(_USER_ID_KEY, user_id)
    db.set_setting(_USER_SECRET_KEY, crypto_service.encrypt(secret))
    return user_id, secret


def connection_portal_url(broker: str | None = None) -> str:
    """A one-time URL where the brokerage login actually happens.

    ``connection_type="read"`` is what keeps this read-only: SnapTrade can also
    issue trading connections, and this app has no business holding one.
    """
    try:
        response = _client().authentication.login_snap_trade_user(
            broker=broker or None,
            connection_type="read",
            immediate_redirect=False,
            **_user_kwargs(),
        )
    except Exception as e:
        raise _fail(e) from e

    payload = _body(response)
    url = payload.get("redirectURI") if isinstance(payload, dict) else None
    if not url:
        raise SnapTradeError(
            "SnapTrade did not return a connection URL. This usually means the "
            "credentials are for a different environment than the account."
        )
    return url


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def _symbol_of(position: dict) -> dict:
    """The security behind a position, whichever shape it arrives in.

    SnapTrade nests the universal symbol one or two levels deep depending on
    the endpoint, and option positions carry a different key entirely.
    """
    node = position.get("symbol") or position.get("option_symbol") or {}
    if isinstance(node, dict) and isinstance(node.get("symbol"), dict):
        node = node["symbol"]
    return node if isinstance(node, dict) else {}


def list_accounts(institution: str | None = None) -> list[dict]:
    """Every brokerage account on the SnapTrade user, in this app's shape."""
    try:
        response = _client().account_information.list_user_accounts(**_user_kwargs())
    except Exception as e:
        raise _fail(e) from e

    out = []
    for a in _body(response) or []:
        balance = (a.get("balance") or {}).get("total") or {}
        name = a.get("name") or a.get("institution_name") or "Brokerage account"
        number = str(a.get("number") or "")
        out.append({
            "provider_account_id": a["id"],
            "authorization_id": a.get("brokerage_authorization"),
            "institution": institution or a.get("institution_name") or "Brokerage",
            "name": name,
            "mask": number[-4:] or None,
            "type": "investment",
            "subtype": "brokerage",
            "currency": (balance.get("currency") or "USD"),
            "balance_current": round(float(balance.get("amount") or 0.0), 2),
            "balance_available": None,
            "credit_limit": None,
        })
    return out


def get_positions(account_id: str) -> list[dict]:
    """Positions for one account, priced and with a whole-position cost basis."""
    try:
        response = _client().account_information.get_all_account_positions(
            account_id=account_id, **_user_kwargs()
        )
    except Exception as e:
        raise _fail(e) from e

    out = []
    for p in _body(response) or []:
        symbol = _symbol_of(p)
        units = float(p.get("units") or p.get("fractional_units") or 0.0)
        price = float(p.get("price") or 0.0)
        average = p.get("average_purchase_price")
        security_type = symbol.get("type") or {}
        out.append({
            "provider_account_id": account_id,
            "symbol": symbol.get("symbol") or symbol.get("raw_symbol"),
            "name": symbol.get("description") or symbol.get("symbol") or "Unknown security",
            "security_type": (security_type.get("code") if isinstance(security_type, dict)
                              else security_type) or None,
            "quantity": units,
            "price": price,
            "value": round(units * price, 2),
            # SnapTrade prices the average *per share*; this app stores what the
            # whole position cost.
            "cost_basis": round(float(average) * units, 2) if average is not None else None,
        })
    return out


def list_connections() -> list[dict]:
    """The brokerage logins behind the accounts, for naming and disconnecting."""
    try:
        response = _client().connections.list_brokerage_authorizations(**_user_kwargs())
    except Exception as e:
        raise _fail(e) from e

    out = []
    for c in _body(response) or []:
        brokerage = c.get("brokerage") or {}
        out.append({
            "authorization_id": c["id"],
            "institution": brokerage.get("display_name") or brokerage.get("name") or "Brokerage",
            "disabled": bool(c.get("disabled")),
            "created": c.get("created_date"),
        })
    return out
