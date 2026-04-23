from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PatientRegistrationRequest(BaseModel):
    age: int = Field(ge=3, le=120)
    sex: Literal["male", "female"]
    height_cm: int = Field(ge=100, le=220)
    weight_kg: float = Field(ge=30, le=300)
    metabolic_group: Literal["T1DM", "T2DM", "normoglycemic"]
    diabetes_duration_years: int | None = None
    diabetes_medication: str | None = None
    insulin_use: Literal["pump", "injections", "none"] | None = None
    smoking_status: Literal["current", "former", "never"]
    cgm_device_type: Literal["libre", "medtronic", "dexcom", "other"]
    cgm_own_device: bool
    apple_watch: bool
    # Optional fields
    first_name: str | None = None
    surname: str | None = None
    blood_type: Literal["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"] | None = None
    last_meal_time: str | None = None
    last_meal_description: str | None = None
    operator_notes: str | None = None

    @model_validator(mode="after")
    def validate_diabetes_fields(self):
        diabetic = self.metabolic_group in ("T1DM", "T2DM")
        fields = {
            "diabetes_duration_years": self.diabetes_duration_years,
            "diabetes_medication": self.diabetes_medication,
            "insulin_use": self.insulin_use,
        }
        if diabetic:
            required_fields = {
                "diabetes_duration_years": self.diabetes_duration_years,
                "insulin_use": self.insulin_use,
            }
            missing = [k for k, v in required_fields.items() if v is None]
            if missing:
                raise ValueError(
                    f"Required for {self.metabolic_group}: {', '.join(missing)}"
                )
        else:
            not_allowed = {
                "diabetes_duration_years": self.diabetes_duration_years,
                "insulin_use": self.insulin_use,
            }
            present = [k for k, v in not_allowed.items() if v is not None]
            if present:
                raise ValueError(
                    f"Must be empty for normoglycemic: {', '.join(present)}"
                )
        return self


class PatientRecord(BaseModel):
    patient_label: str
    registered_at_utc: datetime
    bmi: float
    age: int
    sex: Literal["male", "female"]
    height_cm: int
    weight_kg: float
    metabolic_group: Literal["T1DM", "T2DM", "normoglycemic"]
    diabetes_duration_years: int | None = None
    diabetes_medication: str | None = None
    insulin_use: Literal["pump", "injections", "none"] | None = None
    smoking_status: Literal["current", "former", "never"]
    cgm_device_type: Literal["libre", "medtronic", "dexcom", "other"]
    cgm_own_device: bool
    apple_watch: bool
    first_name: str | None = None
    surname: str | None = None
    blood_type: Literal["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"] | None = None
    last_meal_time: str | None = None
    last_meal_description: str | None = None
    operator_notes: str | None = None
    deleted_at: datetime | None = None


class PatientUpdateRequest(BaseModel):
    """Partial patient update — any subset of editable fields.

    All fields optional; only provided fields are patched. Validation of
    diabetes-conditional rules happens post-merge in the endpoint.
    """
    patient_label: str | None = None
    registered_at_utc: datetime | None = None
    age: int | None = Field(default=None, ge=3, le=120)
    sex: Literal["male", "female"] | None = None
    height_cm: int | None = Field(default=None, ge=100, le=220)
    weight_kg: float | None = Field(default=None, ge=30, le=300)
    metabolic_group: Literal["T1DM", "T2DM", "normoglycemic"] | None = None
    diabetes_duration_years: int | None = None
    diabetes_medication: str | None = None
    insulin_use: Literal["pump", "injections", "none"] | None = None
    smoking_status: Literal["current", "former", "never"] | None = None
    cgm_device_type: Literal["libre", "medtronic", "dexcom", "other"] | None = None
    cgm_own_device: bool | None = None
    apple_watch: bool | None = None
    first_name: str | None = None
    surname: str | None = None
    blood_type: Literal["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"] | None = None
    last_meal_time: str | None = None
    last_meal_description: str | None = None
    operator_notes: str | None = None


class PatientRegistrationResponse(BaseModel):
    patient_label: str
    warnings: list[str] = []


class SessionEvent(BaseModel):
    """One row of a session CSV.

    Two shapes share the table:
      - `kind="note"` → `intervention_type`, `phase`, `intervention_id` all null
      - `kind="intervention"` → all three are required. start/stop rows pair
        via shared `intervention_id`; concurrent interventions are allowed
        (each pair has its own id).
    """
    ts_utc: datetime
    kind: Literal["note", "intervention"]
    intervention_type: Literal["food", "ensure", "insulin"] | None = None
    phase: Literal["start", "stop"] | None = None
    intervention_id: str | None = None
    text: str = ""
    operator: str

    @model_validator(mode="after")
    def validate_shape(self):
        intervention_fields = (self.intervention_type, self.phase, self.intervention_id)
        if self.kind == "intervention":
            if any(v is None for v in intervention_fields):
                raise ValueError(
                    "intervention events require intervention_type, phase, and intervention_id"
                )
        else:
            if any(v is not None for v in intervention_fields):
                raise ValueError("note events must not carry intervention fields")
        return self


class SessionPayload(BaseModel):
    """Full session upload body. Serialized to one CSV at
    `gs://{bucket}/{patient_label}/{session_date}/session_{start_ts}.csv`.
    """
    patient_label: str
    operator: str
    cgm_device: Literal["libre", "medtronic", "dexcom", "other"]
    started_at_utc: datetime
    ended_at_utc: datetime
    events: list[SessionEvent] = []

    @model_validator(mode="after")
    def validate_times(self):
        if self.ended_at_utc < self.started_at_utc:
            raise ValueError("ended_at_utc must be >= started_at_utc")
        return self


class SessionSummary(BaseModel):
    """Lightweight list entry — parsed from the `#` metadata line only."""
    blob_path: str
    patient_label: str
    operator: str
    cgm_device: str
    started_at_utc: datetime
    ended_at_utc: datetime
    event_count: int
