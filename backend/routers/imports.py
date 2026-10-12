"""CSV import — the only path to Apple Savings and Apple Card data.

Two steps on purpose. The preview shows the detected column mapping *and the
parsed result* before anything is written, because the one error that silently
ruins a year of analysis is an inverted sign, and the only reliable way to catch
it is to let a human look at three rows and say "yes, coffee was an expense".
"""

from __future__ import annotations

import os
import time
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

import db
from services import csv_service, recurring, sync_service

router = APIRouter(prefix="/api/imports", tags=["imports"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
STALE_UPLOAD_SECONDS = 6 * 3600


def _reap_stale_uploads() -> None:
    """Delete pending uploads nobody committed.

    These files are raw statements. Leaving them on disk indefinitely because a
    user closed the tab mid-import is a privacy leak with no upside.
    """
    if not os.path.isdir(UPLOAD_DIR):
        return
    cutoff = time.time() - STALE_UPLOAD_SECONDS
    for name in os.listdir(UPLOAD_DIR):
        path = os.path.join(UPLOAD_DIR, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass


@router.post("/preview")
async def preview(file: UploadFile = File(...)):
    content = await file.read()
    if not content:
        raise HTTPException(400, "That file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "That file is larger than 25 MB.")

    try:
        result = csv_service.sniff(content, file.filename or "upload.csv")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(400, f"Could not read that CSV: {type(e).__name__}: {e}") from e

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    _reap_stale_uploads()
    token = uuid.uuid4().hex
    with open(os.path.join(UPLOAD_DIR, token), "wb") as fh:
        fh.write(content)

    result["upload_token"] = token
    result["accounts"] = db.query(
        "SELECT id, name, institution, type, subtype, mask FROM accounts "
        "WHERE is_active = 1 ORDER BY institution, name"
    )
    return result


@router.post("/commit")
async def commit(
    account_id: int = Form(...),
    upload_token: str = Form(...),
    mapping_json: str = Form(...),
):
    import json

    # The token becomes a filename, so it is validated before anything else
    # touches the disk or the database — a malformed path must never get as far
    # as being joined, regardless of whether the rest of the request is valid.
    if not upload_token.isalnum():
        raise HTTPException(400, "Invalid upload token.")

    if not db.query_one("SELECT id FROM accounts WHERE id = ?", (account_id,)):
        raise HTTPException(404, f"Account {account_id} not found.")

    path = os.path.join(UPLOAD_DIR, upload_token)
    if not os.path.isfile(path):
        raise HTTPException(
            410, "That upload has expired. Preview the file again to re-import it."
        )

    try:
        mapping = json.loads(mapping_json)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"mapping_json is not valid JSON: {e}") from e

    with open(path, "rb") as fh:
        content = fh.read()

    try:
        rows, problems = csv_service.parse(content, mapping)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    if not rows:
        raise HTTPException(
            400,
            "No rows could be parsed. " + (problems[0] if problems else "Check the mapping."),
        )

    counts = sync_service.insert_transactions(account_id, rows, source="csv")
    sync_service.snapshot_balances()
    derived = recurring.refresh()

    try:
        os.remove(path)
    except OSError:
        pass

    return {
        **counts,
        "rows_parsed": len(rows),
        "problems": problems[:20],
        "problem_count": len(problems),
        "recurring": derived,
        # Re-importing overlapping statements is the normal case for Apple, so
        # say plainly that the duplicates were recognised rather than dropped.
        "note": (
            f"{counts['skipped']} row(s) were already present and were skipped."
            if counts["skipped"] else None
        ),
    }


@router.get("/presets")
def presets():
    return {
        "presets": [{"id": k, "label": v["label"], "mapping": v["mapping"]}
                    for k, v in csv_service.PRESETS.items()],
        "apple_note": (
            "Apple Card: Wallet → Card → Card Balance → a month → Export Transactions. "
            "Apple Savings issues PDF statements only, so its balance and interest are "
            "best kept as a manual account updated when you check it."
        ),
    }
