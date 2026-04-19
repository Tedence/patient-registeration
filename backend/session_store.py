"""Session CSV format, parse, and blob-path helpers.

Session recording stores one CSV per session at
`gs://{bucket}/{patient_label}/{session_date}/session_{yyyy-mm-dd-hh-mm-ss}.csv`.

CSV layout (single file, no sidecar metadata):
  Line 1: `# k=v,k=v,...` — session-level metadata (patient_label, operator,
          cgm_device, started/ended_at_utc). Skipped by the DictReader below.
  Line 2: column header
  Line 3+: events (see SESSION_COLUMNS)

Backend keeps no local copy — GCS is the canonical store for sessions. These
helpers are pure functions: format in/out, no I/O, no locking.
"""

import csv
from datetime import datetime
from io import StringIO

from models import SessionEvent, SessionPayload, SessionSummary

SESSION_COLUMNS = [
    "ts_utc",
    "kind",
    "intervention_type",
    "phase",
    "intervention_id",
    "text",
    "operator",
]

_META_FIELDS = (
    "patient_label",
    "operator",
    "cgm_device",
    "started_at_utc",
    "ended_at_utc",
)


def session_blob_path(patient_label: str, started_at_utc: datetime) -> str:
    """Return the GCS blob key for a session. Date folder = start date.

    Timestamps in the filename use dashes (not colons) so the path stays
    filesystem-safe if someone mirrors the bucket locally.
    """
    date = started_at_utc.strftime("%Y-%m-%d")
    ts = started_at_utc.strftime("%Y-%m-%d-%H-%M-%S")
    return f"{patient_label}/{date}/session_{ts}.csv"


def format_session_csv(session: SessionPayload) -> str:
    """Serialize a SessionPayload into the wire CSV format."""
    out = StringIO()
    meta_parts = [
        f"{k}={getattr(session, k).isoformat() if isinstance(getattr(session, k), datetime) else getattr(session, k)}"
        for k in _META_FIELDS
    ]
    out.write("# " + ",".join(meta_parts) + "\n")

    writer = csv.DictWriter(out, fieldnames=SESSION_COLUMNS)
    writer.writeheader()
    for ev in session.events:
        row = {
            "ts_utc": ev.ts_utc.isoformat(),
            "kind": ev.kind,
            "intervention_type": ev.intervention_type or "",
            "phase": ev.phase or "",
            "intervention_id": ev.intervention_id or "",
            "text": ev.text,
            "operator": ev.operator,
        }
        writer.writerow(row)
    return out.getvalue()


def _parse_meta_line(line: str) -> dict[str, str]:
    if not line.startswith("#"):
        raise ValueError("session CSV is missing the `#` metadata line")
    meta: dict[str, str] = {}
    for kv in line.lstrip("#").strip().split(","):
        if not kv:
            continue
        k, _, v = kv.partition("=")
        meta[k.strip()] = v.strip()
    return meta


def parse_session_csv(raw: str) -> dict:
    """Parse a session CSV into a dict matching SessionPayload's shape.

    Returns a plain dict (not a Pydantic model) so callers can merge in
    `blob_path` before validation. Empty strings in optional columns are
    coerced to None for clean JSON round-trips.
    """
    lines = raw.splitlines()
    if not lines:
        raise ValueError("session CSV is empty")
    meta = _parse_meta_line(lines[0])

    reader = csv.DictReader(lines[1:])
    events: list[dict] = []
    for row in reader:
        for k in ("intervention_type", "phase", "intervention_id"):
            if row.get(k) == "":
                row[k] = None
        events.append(row)

    return {
        **meta,
        "events": events,
    }


def parse_session_summary(blob_path: str, raw: str) -> SessionSummary:
    """Build a SessionSummary from a session CSV. Counts events cheaply."""
    lines = raw.splitlines()
    if not lines:
        raise ValueError("session CSV is empty")
    meta = _parse_meta_line(lines[0])
    # Subtract header row from the non-meta remainder.
    event_count = max(0, len(lines) - 2)
    return SessionSummary(
        blob_path=blob_path,
        patient_label=meta.get("patient_label", ""),
        operator=meta.get("operator", ""),
        cgm_device=meta.get("cgm_device", ""),
        started_at_utc=meta["started_at_utc"],
        ended_at_utc=meta["ended_at_utc"],
        event_count=event_count,
    )


def build_session_event(row: dict) -> SessionEvent:
    """Lenient helper for tests / repl — validates a single parsed row."""
    return SessionEvent(**row)
