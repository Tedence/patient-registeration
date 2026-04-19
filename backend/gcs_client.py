"""
GCS mirror for patient registrations.

Every successful registration writes two artifacts into the ETL archive bucket
(`gs://tedence-gav-yam/` by default):

1. The full `patients.csv` at the bucket root (overwritten each time — small file,
   atomic blob write keeps this safe).
2. A per-patient `metadata.json` under `{patient_label}/metadata.json`, matching
   the folder layout documented in `gcs.md`.

On backend startup, `download_patients_csv()` pulls the remote CSV over the
local copy so the remote remains the source of truth across restarts.

Config is driven by env vars:
  - GCS_ENABLED  ("false"/"0"/"no" disables all GCS I/O; default "true")
  - GCS_BUCKET   (target bucket name; default "tedence-gav-yam")
  - GOOGLE_APPLICATION_CREDENTIALS  (standard ADC service-account path)

The bucket handle is built lazily and cached so importing this module never
requires credentials — keeps tests and offline dev clean.
"""

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from models import PatientRecord

log = logging.getLogger("register_app.gcs")

_DEFAULT_BUCKET = "tedence-gav-yam"
_PATIENTS_CSV_BLOB = "patients.csv"

_cached_bucket = None
_cache_initialized = False


def _enabled() -> bool:
    """Return True unless GCS_ENABLED is set to a falsy string.

    Tests flip this off via `tests/conftest.py` so no network calls happen
    during the test suite.
    """
    return os.getenv("GCS_ENABLED", "true").lower() not in ("false", "0", "no")


def _bucket():
    """Return a cached `google.cloud.storage.Bucket`, or None when GCS is off.

    Lazily imports `google.cloud.storage` and constructs the client on first
    call so this module can be imported in environments without the SDK or
    credentials (e.g. tests with `GCS_ENABLED=false`).

    Returns `None` when GCS is disabled. Any exception raised during client
    construction propagates to the caller, who is expected to surface it as
    a non-fatal warning.
    """
    global _cached_bucket, _cache_initialized
    if _cache_initialized:
        return _cached_bucket

    if not _enabled():
        _cache_initialized = True
        return None

    from google.cloud import storage

    client = storage.Client()
    bucket_name = os.getenv("GCS_BUCKET", _DEFAULT_BUCKET)
    bucket = client.bucket(bucket_name)

    _cached_bucket = bucket
    _cache_initialized = True
    return _cached_bucket


def _reset_cache() -> None:
    """Clear the cached bucket handle.

    Intended for tests that want to swap `GCS_ENABLED` or `GCS_BUCKET` between
    cases and force `_bucket()` to re-evaluate.
    """
    global _cached_bucket, _cache_initialized
    _cached_bucket = None
    _cache_initialized = False


def get_patients_csv_generation() -> int | None:
    """Return the current generation number of the remote patients.csv.

    Used for optimistic-concurrency uploads: the caller captures the
    generation before building a new CSV, then passes it to
    `upload_patients_csv(..., if_generation_match=...)`. If another process
    has uploaded in the meantime, the conditional upload fails and the
    caller must re-sync + retry.

    Returns:
        int  — the current generation (monotonically increasing per write).
        0    — remote blob does not exist yet (valid precondition for
               create-if-absent).
        None — GCS disabled.
    """
    bucket = _bucket()
    if bucket is None:
        return None
    from google.api_core.exceptions import NotFound

    blob = bucket.blob(_PATIENTS_CSV_BLOB)
    try:
        blob.reload()  # populate .generation
    except NotFound:
        return 0
    return blob.generation


def upload_patients_csv(
    local_path: Path, if_generation_match: int | None = None
) -> None:
    """Upload the full local patients.csv to `gs://{bucket}/patients.csv`.

    No-op when GCS is disabled. Overwrites the remote blob atomically (GCS
    blob writes are all-or-nothing).

    When `if_generation_match` is provided, the upload is conditional: it
    succeeds only if the remote blob's current generation equals that value.
    Pass `0` to require the blob does not yet exist. On mismatch the GCS
    SDK raises `google.api_core.exceptions.PreconditionFailed` (HTTP 412),
    which the caller should treat as a concurrent-writer signal and retry.
    """
    bucket = _bucket()
    if bucket is None:
        return
    blob = bucket.blob(_PATIENTS_CSV_BLOB)
    kwargs = {"content_type": "text/csv"}
    if if_generation_match is not None:
        kwargs["if_generation_match"] = if_generation_match
    blob.upload_from_filename(str(local_path), **kwargs)


def _count_csv_rows(path: Path) -> int:
    """Count data rows in a CSV (excludes header). Returns 0 if file missing."""
    if not path.exists():
        return 0
    with open(path, newline="") as f:
        return max(0, sum(1 for _ in f) - 1)


def download_patients_csv(local_path: Path) -> bool:
    """Pull remote patients.csv over the local copy. Remote is source of truth.

    Called from the FastAPI lifespan on backend startup so in-memory state and
    label generation always begin from the canonical remote CSV.

    Safety net: if a local file exists, it is copied to
    `patients.csv.bak.{UTC_TIMESTAMP}` before being overwritten. When the
    local row count exceeds the remote row count — a signal that offline
    registrations never made it to GCS — a warning is logged so operators
    can reconcile from the backup.

    Returns:
        True  — remote blob existed and was downloaded.
        False — GCS disabled OR remote blob does not exist yet (first-run).

    No-op on the local file when False is returned; any existing local CSV
    is left untouched.
    """
    bucket = _bucket()
    if bucket is None:
        return False
    blob = bucket.blob(_PATIENTS_CSV_BLOB)
    if not blob.exists():
        return False
    local_path.parent.mkdir(parents=True, exist_ok=True)

    if local_path.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = local_path.with_suffix(f".csv.bak.{ts}")
        shutil.copy2(local_path, backup)
        local_rows = _count_csv_rows(local_path)
    else:
        backup = None
        local_rows = 0

    blob.download_to_filename(str(local_path))
    remote_rows = _count_csv_rows(local_path)

    if local_rows > remote_rows:
        log.warning(
            "Local CSV had %d rows but remote only %d — likely unsynced offline "
            "registrations. Backup preserved at %s",
            local_rows, remote_rows, backup,
        )

    return True


def upload_patient_metadata(record: PatientRecord) -> None:
    """Write the patient record as `{patient_label}/metadata.json` in GCS.

    Serializes the full Pydantic record (`mode="json"` so datetimes become ISO
    strings) and uploads as pretty-printed UTF-8 JSON. `ensure_ascii=False`
    preserves non-ASCII characters (Hebrew names, notes).

    No-op when GCS is disabled.
    """
    bucket = _bucket()
    if bucket is None:
        return
    payload = record.model_dump(mode="json")
    blob = bucket.blob(f"{record.patient_label}/metadata.json")
    blob.upload_from_string(
        json.dumps(payload, indent=2, ensure_ascii=False),
        content_type="application/json",
    )
