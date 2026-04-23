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

from typing import Callable

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from models import (
    PatientRecord,
    PatientRegistrationRequest,
    PatientRegistrationResponse,
    PatientUpdateRequest,
    SessionPayload,
    SessionSummary,
)
import audit
import csv_store
import gcs_client
import session_store
from auth import AdminContext, require_admin

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:     %(name)s: %(message)s",
)
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

    Uphold the invariant "remote patients.csv is the source of truth" by
    coupling the local append to a successful remote upload:

      - Uses `if_generation_match` to defend against concurrent writers.
        On PreconditionFailed: roll back the local row, re-sync from the
        newer remote, re-allocate the label, retry (up to 3x).
      - On any non-retriable GCS failure (creds, network, exhausted
        retries): roll back the local row and raise. The registration
        fails cleanly — local never diverges from remote.

    When GCS is disabled (`GCS_ENABLED=false`, e.g. tests), the OCC layer
    is a no-op and registrations succeed locally without a remote write.

    Returns (label, record). Raises on unrecoverable GCS failure.
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
                # Could not reach GCS at all; fail fast so we never write
                # a local-only row that will be wiped on next startup.
                log.exception("GCS generation probe failed")
                raise HTTPException(
                    status_code=503,
                    detail=gcs_client.friendly_error(e),
                ) from e

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
                return label, record
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
                    log.exception("Re-sync after OCC conflict failed")
                    _rollback_last_row(csv_store.CSV_PATH)
                    raise HTTPException(
                        status_code=503,
                        detail=gcs_client.friendly_error(sync_err),
                    ) from sync_err
            except Exception as e:
                log.exception("GCS patients.csv upload failed")
                _rollback_last_row(csv_store.CSV_PATH)
                raise HTTPException(
                    status_code=503,
                    detail=gcs_client.friendly_error(e),
                ) from e

    log.error(
        "CSV upload exhausted %d retries, last error: %s",
        _MAX_CSV_UPLOAD_RETRIES, last_error,
    )
    raise HTTPException(
        status_code=503,
        detail="Could not save to cloud storage after several attempts. Please retry.",
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
      3. Mirror to GCS with strict coupling for the CSV (remote is source of
         truth): the local append and the `gs://{bucket}/patients.csv`
         upload succeed together or neither persists. Uses optimistic
         concurrency + retry; an unrecoverable failure rolls back the local
         row and returns 503 — preventing ghost rows that would be wiped
         on next startup.
      4. `gs://{bucket}/{label}/metadata.json` is best-effort: failure here
         does NOT fail the registration (the CSV row is the canonical
         record) but surfaces via `response.warnings` for operator awareness.

    Returns the assigned patient_label plus any BMI / metadata warnings.
    Raises 503 if the CSV cannot be durably written to GCS.
    """
    bmi = round(req.weight_kg / (req.height_cm / 100) ** 2, 1)

    warnings: list[str] = []
    if bmi < 15 or bmi > 50:
        warnings.append(f"BMI {bmi} is outside the expected range (15–50)")

    label, record = _allocate_and_upload_with_retry(req, bmi)

    try:
        gcs_client.upload_patient_metadata(record)
    except Exception as e:
        log.exception("GCS metadata.json upload failed for %s", record.patient_label)
        warnings.append(
            f"Patient saved, but metadata file did not sync: {gcs_client.friendly_error(e)}"
        )

    return PatientRegistrationResponse(patient_label=label, warnings=warnings)


def _mutate_with_occ(mutate: Callable[[list[PatientRecord]], PatientRecord]) -> PatientRecord:
    """Run `mutate` on the current record list, persist locally + to GCS, retry on conflict.

    Uses snapshot-based rollback (vs. the append-only row rollback used by
    registration) so edits and deletes — which rewrite the file — can be
    undone if the GCS upload fails. Upholds the same invariant: no local
    write survives without a matching remote write.

    `mutate(records)` must modify `records` in place and return the affected
    PatientRecord. Raises HTTPException(503) on unrecoverable GCS failure.
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
                log.exception("GCS generation probe failed")
                raise HTTPException(
                    status_code=503, detail=gcs_client.friendly_error(e),
                ) from e

            snapshot = csv_store.snapshot()
            records = csv_store.read_all()
            try:
                affected = mutate(records)
            except HTTPException:
                raise
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e)) from e

            csv_store.rewrite_all(records)

            try:
                gcs_client.upload_patients_csv(
                    csv_store.CSV_PATH, if_generation_match=generation
                )
                return affected
            except PreconditionFailed as e:
                last_error = e
                csv_store.restore(snapshot)
                log.info(
                    "CSV upload conflict on mutate (attempt %d/%d), re-syncing",
                    attempt + 1, _MAX_CSV_UPLOAD_RETRIES,
                )
                try:
                    gcs_client.download_patients_csv(csv_store.CSV_PATH)
                except Exception as sync_err:
                    log.exception("Re-sync after OCC conflict failed")
                    csv_store.restore(snapshot)
                    raise HTTPException(
                        status_code=503,
                        detail=gcs_client.friendly_error(sync_err),
                    ) from sync_err
            except Exception as e:
                log.exception("GCS patients.csv upload failed during mutation")
                csv_store.restore(snapshot)
                raise HTTPException(
                    status_code=503, detail=gcs_client.friendly_error(e),
                ) from e

    log.error(
        "CSV mutation upload exhausted %d retries, last error: %s",
        _MAX_CSV_UPLOAD_RETRIES, last_error,
    )
    raise HTTPException(
        status_code=503,
        detail="Could not save to cloud storage after several attempts. Please retry.",
    )


def _post_mutation_mirror(record: PatientRecord, warnings: list[str]) -> None:
    """Best-effort per-patient metadata + audit log GCS mirroring. Never raises."""
    try:
        gcs_client.upload_patient_metadata(record)
    except Exception as e:
        log.exception("GCS metadata.json upload failed for %s", record.patient_label)
        warnings.append(
            f"Patient saved, but metadata file did not sync: {gcs_client.friendly_error(e)}"
        )
    try:
        audit.mirror_to_gcs()
    except Exception as e:
        log.exception("GCS audit_log.jsonl upload failed")
        warnings.append(f"Audit log did not sync: {gcs_client.friendly_error(e)}")


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


class AdminMutationResponse(PatientRegistrationResponse):
    """Same shape as registration response — label + warnings."""
    pass


def _validate_diabetes_consistency(rec: PatientRecord) -> None:
    """Re-enforce the diabetes-field conditional rules from PatientRegistrationRequest."""
    diabetic = rec.metabolic_group in ("T1DM", "T2DM")
    if diabetic:
        missing = [
            name for name, val in (
                ("diabetes_duration_years", rec.diabetes_duration_years),
                ("insulin_use", rec.insulin_use),
            ) if val is None
        ]
        if missing:
            raise ValueError(
                f"Required for {rec.metabolic_group}: {', '.join(missing)}"
            )
    else:
        present = [
            name for name, val in (
                ("diabetes_duration_years", rec.diabetes_duration_years),
                ("insulin_use", rec.insulin_use),
            ) if val is not None
        ]
        if present:
            raise ValueError(f"Must be empty for normoglycemic: {', '.join(present)}")


@app.patch("/api/patients/{label}", response_model=AdminMutationResponse)
def update_patient(
    label: str,
    patch: PatientUpdateRequest,
    admin: AdminContext = Depends(require_admin),
):
    """Edit any field on an existing patient. Re-validates + recomputes BMI."""
    patch_data = patch.model_dump(exclude_unset=True)
    if not patch_data:
        raise HTTPException(status_code=422, detail="No fields provided to update.")

    before_dump: dict = {}

    def mutate(records: list[PatientRecord]) -> PatientRecord:
        nonlocal before_dump
        idx = csv_store.find_index(records, label)
        if idx < 0:
            raise HTTPException(status_code=404, detail=f"Patient {label} not found")
        current = records[idx]
        before_dump = current.model_dump(mode="json")
        merged = {**before_dump, **patch_data}
        # Recompute BMI if height or weight moved.
        if "height_cm" in patch_data or "weight_kg" in patch_data:
            merged["bmi"] = round(
                merged["weight_kg"] / (merged["height_cm"] / 100) ** 2, 1
            )
        # Guard against label collisions if caller renames.
        new_label = merged["patient_label"]
        if new_label != label:
            for i, r in enumerate(records):
                if i != idx and r.patient_label == new_label:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Label {new_label} is already in use.",
                    )
        updated = PatientRecord(**merged)
        _validate_diabetes_consistency(updated)
        records[idx] = updated
        return updated

    record = _mutate_with_occ(mutate)
    after_dump = record.model_dump(mode="json")
    audit.append_entry(
        user=admin.user,
        action="update",
        label=record.patient_label,
        diff=audit.compute_diff(before_dump, after_dump),
    )

    warnings: list[str] = []
    if record.bmi < 15 or record.bmi > 50:
        warnings.append(f"BMI {record.bmi} is outside the expected range (15–50)")
    _post_mutation_mirror(record, warnings)
    return AdminMutationResponse(patient_label=record.patient_label, warnings=warnings)


@app.delete("/api/patients/{label}", response_model=AdminMutationResponse)
def delete_patient(label: str, admin: AdminContext = Depends(require_admin)):
    """Soft-delete: set deleted_at=now(). Row stays in the CSV (tombstone)."""
    def mutate(records: list[PatientRecord]) -> PatientRecord:
        idx = csv_store.find_index(records, label)
        if idx < 0:
            raise HTTPException(status_code=404, detail=f"Patient {label} not found")
        current = records[idx]
        if current.deleted_at is not None:
            raise HTTPException(status_code=409, detail=f"Patient {label} is already deleted.")
        current.deleted_at = datetime.now(timezone.utc)
        records[idx] = current
        return current

    record = _mutate_with_occ(mutate)
    audit.append_entry(
        user=admin.user,
        action="delete",
        label=record.patient_label,
        diff={"deleted_at": [None, record.deleted_at.isoformat()]},
    )
    warnings: list[str] = []
    _post_mutation_mirror(record, warnings)
    return AdminMutationResponse(patient_label=record.patient_label, warnings=warnings)


@app.post("/api/patients", response_model=AdminMutationResponse)
def add_patient_manual(
    req: PatientRegistrationRequest,
    admin: AdminContext = Depends(require_admin),
):
    """Manual add from the edit screen. Auto-generates a label like register."""
    bmi = round(req.weight_kg / (req.height_cm / 100) ** 2, 1)
    warnings: list[str] = []
    if bmi < 15 or bmi > 50:
        warnings.append(f"BMI {bmi} is outside the expected range (15–50)")

    def mutate(records: list[PatientRecord]) -> PatientRecord:
        label = csv_store.next_label(req.metabolic_group)
        record = PatientRecord(
            patient_label=label,
            registered_at_utc=datetime.now(timezone.utc),
            bmi=bmi,
            **req.model_dump(),
        )
        records.append(record)
        return record

    record = _mutate_with_occ(mutate)
    audit.append_entry(
        user=admin.user,
        action="create",
        label=record.patient_label,
        diff={"*": [None, record.model_dump(mode="json")]},
    )
    _post_mutation_mirror(record, warnings)
    return AdminMutationResponse(patient_label=record.patient_label, warnings=warnings)


# ---------------------------------------------------------------------------
# Session Recording (DEV-31)
#
# One CSV per session at gs://{bucket}/{patient_label}/{session_date}/session_{ts}.csv.
# Backend keeps no local copy — GCS is canonical. Drafts live in the browser's
# localStorage; only finalized sessions hit these endpoints.
# ---------------------------------------------------------------------------


def _audit_session(user: str, action: str, label: str, diff: dict) -> None:
    """Append a session audit entry + best-effort GCS mirror."""
    audit.append_entry(user=user, action=action, label=label, diff=diff)
    try:
        audit.mirror_to_gcs()
    except Exception:
        log.exception("Audit mirror failed (non-fatal)")


@app.post("/api/sessions")
def create_session(payload: SessionPayload):
    """Upload a finalized session CSV. Any operator; no admin token.

    Validates the patient exists, serializes the payload into the agreed CSV
    shape, and uploads to GCS. GCS failure → 503 (client retains the draft
    and can retry). Audit entry + mirror are best-effort post-success.
    """
    if not csv_store.read_one(payload.patient_label):
        raise HTTPException(
            status_code=404, detail=f"Patient {payload.patient_label} not found"
        )

    blob_path = session_store.session_blob_path(
        payload.patient_label, payload.started_at_utc
    )
    csv_content = session_store.format_session_csv(payload)
    try:
        gcs_client.upload_session_csv(blob_path, csv_content)
    except Exception as e:
        log.exception("Session upload failed for %s", blob_path)
        raise HTTPException(
            status_code=503, detail=gcs_client.friendly_error(e)
        ) from e

    _audit_session(
        user=payload.operator,
        action="session_create",
        label=payload.patient_label,
        diff={
            "blob_path": [None, blob_path],
            "event_count": [0, len(payload.events)],
        },
    )
    return {"blob_path": blob_path, "event_count": len(payload.events)}


@app.get("/api/sessions")
def list_sessions(patient_label: str = Query(...)):
    """List sessions for one patient. Returns summary metadata per session.

    Summaries are parsed from each CSV's `#` metadata line, so the payload is
    small even if a patient has many sessions. Sessions that fail to parse are
    skipped (logged) rather than breaking the whole list.
    """
    blob_paths = gcs_client.list_sessions_for_patient(patient_label)
    summaries: list[SessionSummary] = []
    for path in blob_paths:
        raw = gcs_client.download_session_csv(path)
        if raw is None:
            continue
        try:
            summaries.append(session_store.parse_session_summary(path, raw))
        except Exception:
            log.exception("Skipping corrupt session CSV: %s", path)
    summaries.sort(key=lambda s: s.started_at_utc)
    return {"patient_label": patient_label, "sessions": [s.model_dump(mode="json") for s in summaries]}


@app.get("/api/sessions/{patient_label}/{date}/{filename}")
def get_session(patient_label: str, date: str, filename: str):
    """Fetch a parsed session. Returns metadata + full event list."""
    blob_path = f"{patient_label}/{date}/{filename}"
    raw = gcs_client.download_session_csv(blob_path)
    if raw is None:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        parsed = session_store.parse_session_csv(raw)
    except Exception as e:
        log.exception("Failed to parse session CSV %s", blob_path)
        raise HTTPException(
            status_code=500, detail=f"Corrupt session CSV: {e}"
        ) from e
    return {"blob_path": blob_path, **parsed}


@app.patch("/api/sessions/{patient_label}/{date}/{filename}")
def update_session(
    patient_label: str,
    date: str,
    filename: str,
    payload: SessionPayload,
    admin: AdminContext = Depends(require_admin),
):
    """Admin-only full rewrite of a session CSV."""
    blob_path = f"{patient_label}/{date}/{filename}"
    if payload.patient_label != patient_label:
        raise HTTPException(
            status_code=422,
            detail="patient_label in body must match the URL path.",
        )

    before_raw = gcs_client.download_session_csv(blob_path)
    if before_raw is None:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        before_summary = session_store.parse_session_summary(blob_path, before_raw)
    except Exception:
        before_summary = None

    csv_content = session_store.format_session_csv(payload)
    try:
        gcs_client.upload_session_csv(blob_path, csv_content)
    except Exception as e:
        log.exception("Session update upload failed for %s", blob_path)
        raise HTTPException(
            status_code=503, detail=gcs_client.friendly_error(e)
        ) from e

    _audit_session(
        user=admin.user,
        action="session_update",
        label=patient_label,
        diff={
            "blob_path": blob_path,
            "event_count": [
                before_summary.event_count if before_summary else None,
                len(payload.events),
            ],
        },
    )
    return {"blob_path": blob_path, "event_count": len(payload.events)}


@app.delete("/api/sessions/{patient_label}/{date}/{filename}")
def delete_session(
    patient_label: str,
    date: str,
    filename: str,
    admin: AdminContext = Depends(require_admin),
):
    """Admin-only hard delete of a session blob."""
    blob_path = f"{patient_label}/{date}/{filename}"
    try:
        gcs_client.delete_session_csv(blob_path)
    except Exception as e:
        log.exception("Session delete failed for %s", blob_path)
        raise HTTPException(
            status_code=503, detail=gcs_client.friendly_error(e)
        ) from e

    _audit_session(
        user=admin.user,
        action="session_delete",
        label=patient_label,
        diff={"blob_path": [blob_path, None]},
    )
    return {"blob_path": blob_path}
