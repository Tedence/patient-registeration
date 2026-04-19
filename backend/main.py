from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from models import PatientRegistrationRequest, PatientRegistrationResponse, PatientRecord
import csv_store
import gcs_client

app = FastAPI(title="Patient Registration API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/register", response_model=PatientRegistrationResponse)
def register_patient(req: PatientRegistrationRequest):
    bmi = round(req.weight_kg / (req.height_cm / 100) ** 2, 1)

    warnings: list[str] = []
    if bmi < 15 or bmi > 50:
        warnings.append(f"BMI {bmi} is outside the expected range (15–50)")

    with csv_store._lock:
        label = csv_store.next_label(req.metabolic_group)
        record = PatientRecord(
            patient_label=label,
            registered_at_utc=datetime.now(timezone.utc),
            bmi=bmi,
            **req.model_dump(),
        )
        csv_store.append_patient(record)

    try:
        gcs_client.upload_patients_csv(csv_store.CSV_PATH)
    except Exception as e:
        warnings.append(f"GCS patients.csv upload failed: {e}")

    try:
        gcs_client.upload_patient_metadata(record)
    except Exception as e:
        warnings.append(f"GCS metadata.json upload failed: {e}")

    return PatientRegistrationResponse(patient_label=label, warnings=warnings)


@app.get("/api/patients")
def list_patients(metabolic_group: str | None = Query(None)):
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
    patient = csv_store.read_one(label)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {label} not found")
    return patient.model_dump()
