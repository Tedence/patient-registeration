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


def friendly_error(e: BaseException) -> str:
    """Translate a raw GCS/network exception into one short operator-facing line.

    Raw exceptions from google-cloud-storage embed URLs, JSON blobs, and
    Python tracebacks — useful for server logs, intimidating for the
    operator running the registration UI. This function maps the common
    categories to short, actionable messages. The full exception should
    still be logged separately for debugging.
    """
    name = type(e).__name__
    text = str(e)

    if name == "NotFound" or "bucket does not exist" in text or '"code": 404' in text:
        return "Cloud storage bucket is missing. Contact admin."
    if name == "Forbidden" or '"code": 403' in text or "does not have" in text:
        return "No permission to write to cloud storage. Contact admin."
    if name == "PreconditionFailed" or '"code": 412' in text:
        return "Another operator is writing right now. Please retry."
    if name in ("DefaultCredentialsError", "RefreshError") or "credentials" in text.lower():
        return "Cloud storage credentials expired. Run `gcloud auth application-default login`."
    if name in ("ConnectionError", "Timeout", "ServiceUnavailable") or "connection" in text.lower():
        return "Cloud storage unreachable. Check your internet connection and retry."
    return "Cloud storage write failed. Contact admin if this persists."


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


def _maybe_inject_failure(operation: str) -> None:
    """Dev/demo failure injection — gated by GCS_FAIL_MODE env var.

    Recognized modes (applied to the matching operation):
      - `missing`    → NotFound ("bucket does not exist")
      - `creds`      → DefaultCredentialsError
      - `network`    → ConnectionError
      - `conflict`   → PreconditionFailed (only applied to csv upload)
      - `metadata`   → InternalServerError (only applied to metadata upload)

    `operation` is "csv" or "metadata". Ignored in production unless
    GCS_FAIL_MODE is explicitly set.
    """
    mode = os.getenv("GCS_FAIL_MODE", "").lower()
    if not mode:
        return
    from google.api_core import exceptions as gexc
    from google.auth import exceptions as authexc

    if mode == "missing":
        raise gexc.NotFound("The specified bucket does not exist.")
    if mode == "creds":
        raise authexc.DefaultCredentialsError("Your default credentials were not found.")
    if mode == "network":
        raise ConnectionError("connection refused")
    if mode == "conflict" and operation == "csv":
        raise gexc.PreconditionFailed("Precondition Failed: generation mismatch")
    if mode == "metadata" and operation == "metadata":
        raise gexc.InternalServerError("500 backend error uploading metadata")
    if mode == "session" and operation == "session":
        raise gexc.InternalServerError("500 backend error uploading session csv")


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
    _maybe_inject_failure("csv")
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


def upload_session_csv(blob_path: str, csv_content: str) -> None:
    """Upload a session CSV string to `gs://{bucket}/{blob_path}`.

    No-op when GCS is disabled (tests). Overwrites atomically — session
    updates are full-file rewrites by design.
    """
    bucket = _bucket()
    if bucket is None:
        return
    _maybe_inject_failure("session")
    blob = bucket.blob(blob_path)
    blob.upload_from_string(csv_content, content_type="text/csv")


def download_session_csv(blob_path: str) -> str | None:
    """Fetch a session CSV as text. Returns None if missing or GCS disabled."""
    bucket = _bucket()
    if bucket is None:
        return None
    from google.api_core.exceptions import NotFound

    blob = bucket.blob(blob_path)
    try:
        return blob.download_as_text()
    except NotFound:
        return None


def list_sessions_for_patient(patient_label: str) -> list[str]:
    """List session blob paths under `{patient_label}/`.

    Filters to the `session_*.csv` naming convention so `metadata.json` and
    anything else the bucket might accumulate are excluded.
    """
    bucket = _bucket()
    if bucket is None:
        return []
    prefix = f"{patient_label}/"
    paths: list[str] = []
    for blob in bucket.list_blobs(prefix=prefix):
        name = blob.name
        # Expect {label}/{date}/session_*.csv (3 path parts, 2 slashes).
        parts = name.split("/")
        if len(parts) == 3 and parts[2].startswith("session_") and parts[2].endswith(".csv"):
            paths.append(name)
    return paths


def delete_session_csv(blob_path: str) -> None:
    """Delete a session blob. Missing blob is not an error (idempotent)."""
    bucket = _bucket()
    if bucket is None:
        return
    from google.api_core.exceptions import NotFound

    try:
        bucket.blob(blob_path).delete()
    except NotFound:
        return


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
    _maybe_inject_failure("metadata")
    payload = record.model_dump(mode="json")
    blob = bucket.blob(f"{record.patient_label}/metadata.json")
    blob.upload_from_string(
        json.dumps(payload, indent=2, ensure_ascii=False),
        content_type="application/json",
    )
