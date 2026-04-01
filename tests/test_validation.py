import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from models import PatientRegistrationRequest


def _base(**overrides):
    defaults = {
        "age": 34,
        "sex": "male",
        "height_cm": 178,
        "weight_kg": 82,
        "metabolic_group": "normoglycemic",
        "smoking_status": "never",
        "cgm_device_type": "libre",
        "cgm_own_device": True,
        "apple_watch": False,
    }
    defaults.update(overrides)
    return defaults


class TestNormoglycemic:
    def test_valid(self):
        PatientRegistrationRequest(**_base())

    def test_rejects_diabetes_fields(self):
        with pytest.raises(ValidationError, match="normoglycemic"):
            PatientRegistrationRequest(**_base(diabetes_duration_years=5))


class TestDiabetic:
    def test_valid_t1dm(self):
        PatientRegistrationRequest(**_base(
            metabolic_group="T1DM",
            diabetes_duration_years=12,
            diabetes_medication="Humalog",
            insulin_use="injections",
        ))

    def test_valid_t2dm(self):
        PatientRegistrationRequest(**_base(
            metabolic_group="T2DM",
            diabetes_duration_years=5,
            diabetes_medication="Metformin",
            insulin_use="none",
        ))

    def test_t1dm_without_medication_ok(self):
        PatientRegistrationRequest(**_base(
            metabolic_group="T1DM",
            diabetes_duration_years=12,
            insulin_use="injections",
        ))

    def test_missing_insulin_use(self):
        with pytest.raises(ValidationError, match="insulin_use"):
            PatientRegistrationRequest(**_base(
                metabolic_group="T1DM",
                diabetes_duration_years=12,
                diabetes_medication="Humalog",
            ))

    def test_missing_all_diabetes_fields(self):
        with pytest.raises(ValidationError, match="T2DM"):
            PatientRegistrationRequest(**_base(metabolic_group="T2DM"))


class TestBounds:
    def test_age_too_young(self):
        with pytest.raises(ValidationError):
            PatientRegistrationRequest(**_base(age=17))

    def test_age_too_old(self):
        with pytest.raises(ValidationError):
            PatientRegistrationRequest(**_base(age=66))

    def test_age_boundary_low(self):
        PatientRegistrationRequest(**_base(age=18))

    def test_age_boundary_high(self):
        PatientRegistrationRequest(**_base(age=65))

    def test_height_too_low(self):
        with pytest.raises(ValidationError):
            PatientRegistrationRequest(**_base(height_cm=99))

    def test_weight_too_high(self):
        with pytest.raises(ValidationError):
            PatientRegistrationRequest(**_base(weight_kg=301))
