"""
FastAPI entrypoint for the patient registration service.

Three endpoints power the React frontend:
  - POST /api/register        register a new patient, auto-assign label, mirror to GCS
  - GET  /api/patients        list all patients (optional metabolic_group filter)
  - GET  /api/patients/{label} fetch a single patient by label

Persistence is dual-layer:
  - Local:  `data/patients.csv` (append-only, thread-safe via csv_store._lock)
  - Remote: `gs://tedence-gav-yam/` — full CSV at root + per-patient metadata.json

The remote bucket is the source of truth across restarts: the lifespan hook
below pulls the remote CSV over the local copy before any requests are served.
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from models import PatientRegistrationRequest, PatientRegistrationResponse, PatientRecord
import csv_store
import gcs_client

log = logging.getLogger("register_app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Sync local patients.csv from GCS before accepting any requests.

    Runs once on backend startup. Failures here are non-fatal — the server
    still starts and falls back to whatever local CSV exists. Shutdown is a
    no-op (nothing to tear down).
    """
    try:
        synced = gcs_client.download_patients_csv(csv_store.CSV_PATH)
        if synced:
            log.info("Synced patients.csv from GCS (remote is source of truth)")
        else:
            log.info("Skipped GCS sync (disabled or remote blob missing)")
    except Exception as e:
        log.warning("GCS startup sync failed, using local patients.csv: %s", e)
    yield


app = FastAPI(title="Patient Registration API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


_MAX_CSV_UPLOAD_RETRIES = 3


def _allocate_and_upload_with_retry(req: PatientRegistrationRequest, bmi: float):
    """Allocate a label, append locally, upload to GCS with OCC. Retry on conflict.

    Uses `if_generation_match` to defend against two operators racing to
    register patients against the same remote CSV generation (see critical
    issue #2 in the branch review). On a precondition failure:
      - roll back our last local row,
      - re-sync local CSV from the now-newer remote,
      - re-allocate the label against the fresh state,
      - retry.

    After `_MAX_CSV_UPLOAD_RETRIES` conflicts we bail out and return a
    warning, but the most recent local append is preserved (non-fatal per
    the project's failure semantics).

    Returns (label, record, warning_or_None).
    """
    try:
        from google.api_core.exceptions import PreconditionFailed
    except ImportError:
        PreconditionFailed = ()  # type: ignore[assignment]

    last_error: Exception | None = None

    for attempt in range(_MAX_CSV_UPLOAD_RETRIES):
        with csv_store._lock:
            try:
                generation = gcs_client.get_patients_csv_generation()
            except Exception as e:
                generation = None
                last_error = e

            label = csv_store.next_label(req.metabolic_group)
            record = PatientRecord(
                patient_label=label,
                registered_at_utc=datetime.now(timezone.utc),
                bmi=bmi,
                **req.model_dump(),
            )
            csv_store.append_patient(record)

            try:
                gcs_client.upload_patients_csv(
                    csv_store.CSV_PATH, if_generation_match=generation
                )
                return label, record, None
            except PreconditionFailed as e:
                last_error = e
                _rollback_last_row(csv_store.CSV_PATH)
                log.info(
                    "CSV upload conflict (attempt %d/%d), re-syncing and retrying",
                    attempt + 1, _MAX_CSV_UPLOAD_RETRIES,
                )
                try:
                    gcs_client.download_patients_csv(csv_store.CSV_PATH)
                except Exception as sync_err:
                    last_error = sync_err
                    break
            except Exception as e:
                last_error = e
                return label, record, f"GCS patients.csv upload failed: {e}"

    return label, record, (
        f"GCS patients.csv upload failed after {_MAX_CSV_UPLOAD_RETRIES} "
        f"conflict retries: {last_error}"
    )


def _rollback_last_row(path) -> None:
    """Remove the last data row from a CSV. Used after an OCC upload conflict.

    Keeps the header intact so the next append sees a non-empty file. Safe
    even when the CSV has only a header (nothing to remove).
    """
    if not path.exists():
        return
    with open(path, "r", newline="") as f:
        lines = f.readlines()
    if len(lines) <= 1:
        return
    with open(path, "w", newline="") as f:
        f.writelines(lines[:-1])


@app.post("/api/register", response_model=PatientRegistrationResponse)
def register_patient(req: PatientRegistrationRequest):
    """Register a new patient and mirror the registration to GCS.

    Flow:
      1. Compute BMI server-side (kg / m²) and emit a soft warning if outside
         15–50 — Pydantic validation has already enforced hard bounds on age,
         height, weight, and the metabolic-group-conditional diabetes fields.
      2. Under `csv_store._lock`, allocate the next label (NG_/T1_/T2_ prefix
         + zero-padded sequence) and append the full record to patients.csv.
         The lock guarantees label uniqueness under concurrent requests.
      3. Outside the lock, mirror to GCS:
           - overwrite `gs://{bucket}/patients.csv` with the full local file
           - write `gs://{bucket}/{label}/metadata.json` for this patient
         Both uploads are wrapped independently: if either fails the request
         still returns 200, the local write is preserved, and the error text
         flows back via `response.warnings`.

    Returns the assigned patient_label plus any BMI / GCS warnings.
    """
    bmi = round(req.weight_kg / (req.height_cm / 100) ** 2, 1)

    warnings: list[str] = []
    if bmi < 15 or bmi > 50:
        warnings.append(f"BMI {bmi} is outside the expected range (15–50)")

    label, record, csv_warning = _allocate_and_upload_with_retry(req, bmi)
    if csv_warning:
        warnings.append(csv_warning)

    try:
        gcs_client.upload_patient_metadata(record)
    except Exception as e:
        warnings.append(f"GCS metadata.json upload failed: {e}")

    return PatientRegistrationResponse(patient_label=label, warnings=warnings)


@app.get("/api/patients")
def list_patients(metabolic_group: str | None = Query(None)):
    """Return a lightweight summary of every registered patient.

    Only the fields needed for the frontend list view are returned (label,
    age, sex, metabolic_group, registered_at). Full records are available via
    `GET /api/patients/{label}`.

    When `metabolic_group` is provided (NG / T1DM / T2DM), rows are filtered
    in-process after reading the full CSV — fine at expected patient volume.
    """
    patients = csv_store.read_all()
    if metabolic_group:
        patients = [p for p in patients if p.metabolic_group == metabolic_group]
    return [
        {
            "patient_label": p.patient_label,
            "age": p.age,
            "sex": p.sex,
            "metabolic_group": p.metabolic_group,
            "registered_at_utc": p.registered_at_utc.isoformat(),
        }
        for p in patients
    ]


@app.get("/api/patients/{label}")
def get_patient(label: str):
    """Return the full PatientRecord for a single label, or 404 if unknown."""
    patient = csv_store.read_one(label)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {label} not found")
    return patient.model_dump()
