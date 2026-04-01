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
    "last_meal_description", "operator_notes",
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
        "last_meal_description", "operator_notes",
    )
    for field in optional_str:
        if row.get(field) == "":
            row[field] = None
    for bool_field in ("cgm_own_device", "apple_watch"):
        if row.get(bool_field) in ("True", "true", "1"):
            row[bool_field] = True
        elif row.get(bool_field) in ("False", "false", "0"):
            row[bool_field] = False
    return PatientRecord(**row)
