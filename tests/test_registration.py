import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import csv_store
from main import app


@pytest.fixture(autouse=True)
def tmp_csv(tmp_path, monkeypatch):
    csv_path = tmp_path / "patients.csv"
    monkeypatch.setattr(csv_store, "CSV_PATH", csv_path)
    return csv_path


@pytest.fixture
def client():
    return TestClient(app)


def _valid_payload(**overrides):
    data = {
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
    data.update(overrides)
    return data


class TestRegister:
    def test_first_normoglycemic_gets_ng01(self, client):
        r = client.post("/api/register", json=_valid_payload())
        assert r.status_code == 200
        assert r.json()["patient_label"] == "NG_01"

    def test_second_normoglycemic_gets_ng02(self, client):
        client.post("/api/register", json=_valid_payload())
        r = client.post("/api/register", json=_valid_payload())
        assert r.json()["patient_label"] == "NG_02"

    def test_t1dm_gets_t1_prefix(self, client):
        r = client.post("/api/register", json=_valid_payload(
            metabolic_group="T1DM",
            diabetes_duration_years=10,
            insulin_use="pump",
        ))
        assert r.json()["patient_label"] == "T1_01"

    def test_sequences_independent(self, client):
        client.post("/api/register", json=_valid_payload())
        client.post("/api/register", json=_valid_payload(
            metabolic_group="T1DM",
            diabetes_duration_years=10,
            insulin_use="pump",
        ))
        r = client.post("/api/register", json=_valid_payload())
        assert r.json()["patient_label"] == "NG_02"

    def test_bmi_warning(self, client):
        r = client.post("/api/register", json=_valid_payload(
            height_cm=180, weight_kg=300,
        ))
        assert r.status_code == 200
        assert len(r.json()["warnings"]) > 0

    def test_age_rejected(self, client):
        r = client.post("/api/register", json=_valid_payload(age=70))
        assert r.status_code == 422


class TestList:
    def test_list_empty(self, client):
        r = client.get("/api/patients")
        assert r.json() == []

    def test_list_after_register(self, client):
        client.post("/api/register", json=_valid_payload())
        r = client.get("/api/patients")
        assert len(r.json()) == 1
        assert r.json()[0]["patient_label"] == "NG_01"

    def test_filter_metabolic_group(self, client):
        client.post("/api/register", json=_valid_payload())
        client.post("/api/register", json=_valid_payload(
            metabolic_group="T1DM",
            diabetes_duration_years=10,
            diabetes_medication="Humalog",
            insulin_use="pump",
        ))
        r = client.get("/api/patients?metabolic_group=T1DM")
        assert len(r.json()) == 1
        assert r.json()[0]["metabolic_group"] == "T1DM"


class TestGetOne:
    def test_not_found(self, client):
        r = client.get("/api/patients/NG_99")
        assert r.status_code == 404

    def test_found(self, client):
        client.post("/api/register", json=_valid_payload())
        r = client.get("/api/patients/NG_01")
        assert r.status_code == 200
        assert r.json()["patient_label"] == "NG_01"
        assert r.json()["bmi"] == 25.9
