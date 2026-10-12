"""AES-256-GCM for provider access tokens at rest.

A Plaid access token reads every transaction on your Chase card and every
position in your brokerage, and it sits in a SQLite file in your home
directory. Encrypting it means a copied database file is not by itself enough.

The key comes from ``FINANCE_MASTER_KEY``. If that is unset, a key is generated
and stored in the database, which a stolen database decrypts on its own — the
/api/health endpoint reports this so the UI can warn about it.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import db

_KEY_SETTING = "generated_master_key"
NONCE_BYTES = 12


def _load_key() -> tuple[bytes, bool]:
    """Returns (key, came_from_env)."""
    env = os.getenv("FINANCE_MASTER_KEY", "").strip()
    if env:
        try:
            key = base64.b64decode(env)
        except Exception as e:
            raise RuntimeError("FINANCE_MASTER_KEY is not valid base64") from e
        if len(key) != 32:
            raise RuntimeError(
                f"FINANCE_MASTER_KEY must decode to 32 bytes, got {len(key)}"
            )
        return key, True

    stored = db.get_setting(_KEY_SETTING)
    if stored:
        return base64.b64decode(stored), False

    key = os.urandom(32)
    db.set_setting(_KEY_SETTING, base64.b64encode(key).decode())
    return key, False


def key_is_ephemeral() -> bool:
    """True when the key lives in the database rather than the environment."""
    try:
        _, from_env = _load_key()
        return not from_env
    except RuntimeError:
        return True


def encrypt(plaintext: str) -> str:
    """Returns base64(nonce || ciphertext||tag)."""
    if plaintext is None:
        raise ValueError("nothing to encrypt")
    key, _ = _load_key()
    nonce = os.urandom(NONCE_BYTES)
    blob = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + blob).decode()


def decrypt(token: str) -> str:
    key, _ = _load_key()
    raw = base64.b64decode(token)
    nonce, blob = raw[:NONCE_BYTES], raw[NONCE_BYTES:]
    return AESGCM(key).decrypt(nonce, blob, None).decode()
