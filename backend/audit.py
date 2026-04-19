"""Append-only audit log for admin mutations.

Each line of `data/audit_log.jsonl` records one mutation:
  {"ts": ISO, "user": "...", "action": "create|update|delete",
   "label": "...", "diff": {"field": [old, new]}}

Local file is canonical; GCS mirror is best-effort (upload failures surface as
warnings, not 503s — the CSV itself is the durable record).
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("register_app.audit")

AUDIT_PATH = Path(__file__).parent.parent / "data" / "audit_log.jsonl"


def compute_diff(before: dict, after: dict) -> dict[str, list[Any]]:
    """Return {field: [old, new]} for every field whose value changed."""
    diff: dict[str, list[Any]] = {}
    keys = set(before) | set(after)
    for k in keys:
        b = before.get(k)
        a = after.get(k)
        if b != a:
            diff[k] = [b, a]
    return diff


def append_entry(
    user: str,
    action: str,
    label: str,
    diff: dict,
    path: Path | None = None,
) -> None:
    """Append one JSONL entry to the local audit log."""
    p = path or AUDIT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": user,
        "action": action,
        "label": label,
        "diff": diff,
    }
    with open(p, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def mirror_to_gcs(path: Path | None = None) -> None:
    """Best-effort upload of the full audit log to gs://{bucket}/audit_log.jsonl.

    Import locally to avoid a circular dep with gcs_client.
    """
    import gcs_client

    p = path or AUDIT_PATH
    if not p.exists():
        return
    bucket = gcs_client._bucket()
    if bucket is None:
        return
    blob = bucket.blob("audit_log.jsonl")
    blob.upload_from_filename(str(p), content_type="application/x-ndjson")
