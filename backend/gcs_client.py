import json
import os
from pathlib import Path

from models import PatientRecord

_DEFAULT_BUCKET = "tedence-gav-yam"
_PATIENTS_CSV_BLOB = "patients.csv"

_cached_bucket = None
_cache_initialized = False


def _enabled() -> bool:
    return os.getenv("GCS_ENABLED", "true").lower() not in ("false", "0", "no")


def _bucket():
    global _cached_bucket, _cache_initialized
    if _cache_initialized:
        return _cached_bucket

    _cache_initialized = True
    if not _enabled():
        return None

    from google.cloud import storage

    client = storage.Client()
    bucket_name = os.getenv("GCS_BUCKET", _DEFAULT_BUCKET)
    _cached_bucket = client.bucket(bucket_name)
    return _cached_bucket


def _reset_cache() -> None:
    global _cached_bucket, _cache_initialized
    _cached_bucket = None
    _cache_initialized = False


def upload_patients_csv(local_path: Path) -> None:
    bucket = _bucket()
    if bucket is None:
        return
    blob = bucket.blob(_PATIENTS_CSV_BLOB)
    blob.upload_from_filename(str(local_path), content_type="text/csv")


def upload_patient_metadata(record: PatientRecord) -> None:
    bucket = _bucket()
    if bucket is None:
        return
    payload = record.model_dump(mode="json")
    blob = bucket.blob(f"{record.patient_label}/metadata.json")
    blob.upload_from_string(
        json.dumps(payload, indent=2, ensure_ascii=False),
        content_type="application/json",
    )
