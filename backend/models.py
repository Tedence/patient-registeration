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
