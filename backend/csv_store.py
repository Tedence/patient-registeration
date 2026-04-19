import csv
import re
import threading
from pathlib import Path

from models import PatientRecord

CSV_PATH = Path(__file__).parent.parent / "data" / "patients.csv"

COLUMNS = [
    "patient_label", "registered_at_utc", "age", "sex", "height_cm",
    "weight_kg", "bmi", "metabolic_group", "diabetes_duration_years",
    "diabetes_medication", "insulin_use", "smoking_status",
    "cgm_device_type", "cgm_own_device", "apple_watch",
    "first_name", "surname", "blood_type", "last_meal_time",
    "last_meal_description", "operator_notes", "deleted_at",
]

_lock = threading.Lock()


def _read_rows(path: Path | None = None) -> list[dict]:
    p = path or CSV_PATH
    if not p.exists():
        return []
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


LABEL_PREFIXES = {
    "normoglycemic": "NG",
    "T1DM": "T1",
    "T2DM": "T2",
}


def next_label(metabolic_group: str, path: Path | None = None) -> str:
    prefix = LABEL_PREFIXES[metabolic_group]
    rows = _read_rows(path)
    max_n = 0
    for row in rows:
        m = re.match(rf"{prefix}_(\d+)", row.get("patient_label", ""))
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"{prefix}_{max_n + 1:02d}"


def append_patient(record: PatientRecord, path: Path | None = None) -> None:
    p = path or CSV_PATH
    write_header = not p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if write_header:
            writer.writeheader()
        row = record.model_dump()
        row["registered_at_utc"] = record.registered_at_utc.isoformat()
        writer.writerow(row)


def read_all(path: Path | None = None) -> list[PatientRecord]:
    rows = _read_rows(path)
    return [_row_to_record(r) for r in rows]


def read_one(label: str, path: Path | None = None) -> PatientRecord | None:
    for row in _read_rows(path):
        if row.get("patient_label") == label:
            return _row_to_record(row)
    return None


def register_patient(record: PatientRecord, path: Path | None = None) -> None:
    """Thread-safe label generation + append."""
    with _lock:
        append_patient(record, path)


def _row_to_record(row: dict) -> PatientRecord:
    optional_str = (
        "diabetes_duration_years", "diabetes_medication", "insulin_use",
        "first_name", "surname", "blood_type", "last_meal_time",
        "last_meal_description", "operator_notes", "deleted_at",
    )
    for field in optional_str:
        if row.get(field) == "" or row.get(field) is None:
            row[field] = None
    for bool_field in ("cgm_own_device", "apple_watch"):
        if row.get(bool_field) in ("True", "true", "1"):
            row[bool_field] = True
        elif row.get(bool_field) in ("False", "false", "0"):
            row[bool_field] = False
    return PatientRecord(**row)


def snapshot(path: Path | None = None) -> bytes:
    """Return raw CSV bytes for rollback purposes. Empty bytes if missing."""
    p = path or CSV_PATH
    if not p.exists():
        return b""
    return p.read_bytes()


def restore(data: bytes, path: Path | None = None) -> None:
    """Overwrite CSV with bytes from a prior snapshot (or delete if empty)."""
    p = path or CSV_PATH
    if not data:
        if p.exists():
            p.unlink()
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def rewrite_all(records: list[PatientRecord], path: Path | None = None) -> None:
    """Atomic rewrite of the CSV from the full record list.

    Writes to a sibling temp file and renames — guarantees readers never see
    a half-written file. Caller must hold `_lock`.
    """
    p = path or CSV_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for rec in records:
            row = rec.model_dump()
            row["registered_at_utc"] = rec.registered_at_utc.isoformat()
            if rec.deleted_at is not None:
                row["deleted_at"] = rec.deleted_at.isoformat()
            writer.writerow(row)
    tmp.replace(p)


def find_index(records: list[PatientRecord], label: str) -> int:
    """Index of the record with the given label, or -1 if missing."""
    for i, r in enumerate(records):
        if r.patient_label == label:
            return i
    return -1
