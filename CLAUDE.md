# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Patient registration system for Tedence metabolic research lab. Operators register study participants, system auto-assigns labels (NG_01, T1_01, T2_01...) and stores records in append-only CSV.

## Commands

```bash
# Run both backend + frontend
make run

# Backend only (port 8000)
make backend

# Frontend only (Vite dev server, port 5173)
make frontend

# Tests
make test
# Single test file
cd .. && python -m pytest register_app/tests/test_validation.py -v
# Single test
cd .. && python -m pytest register_app/tests/test_registration.py::TestRegister::test_first_normoglycemic_gets_ng01 -v

# Frontend lint
cd frontend && npm run lint
```

## Architecture

**Backend** (FastAPI + Pydantic): `backend/main.py` defines 3 endpoints (`POST /api/register`, `GET /api/patients`, `GET /api/patients/{label}`). `models.py` has Pydantic schemas with conditional validation — diabetes fields required for T1DM/T2DM, forbidden for normoglycemic. `csv_store.py` handles CSV persistence with thread-safe locking and auto-incrementing label generation per metabolic group prefix.

**Frontend** (React 19 + Vite): `frontend/src/` — `RegistrationForm.jsx` (multi-step form), `ReviewScreen.jsx` (confirm before submit), `PatientList.jsx` (view registered patients), `App.jsx` (routing between views).

**Storage**: `data/patients.csv` — append-only, auto-created on first registration. Tests monkeypatch `csv_store.CSV_PATH` to use temp files.

**GCS mirror** (`backend/gcs_client.py`): after every successful registration, the full `patients.csv` is uploaded to `gs://{GCS_BUCKET}/patients.csv` and a per-patient `metadata.json` to `gs://{GCS_BUCKET}/{patient_label}/metadata.json`. Failures are non-fatal and surface in `response.warnings`. Env vars: `GCS_BUCKET` (default `tedence-gav-yam`), `GCS_ENABLED` (set to `false` to disable — tests do this via `conftest.py`), `GOOGLE_APPLICATION_CREDENTIALS` (service account JSON path).

## Key Domain Logic

- Label format: `{prefix}_{nn}` where prefix is NG/T1/T2 per metabolic group, nn is zero-padded sequence number
- BMI auto-calculated server-side; soft warning if <15 or >50
- Validation bounds: age 18-65, height 100-220cm, weight 30-300kg
- CORS allows localhost:3000 and localhost:5173

## Test Pattern

Tests use `FastAPI.TestClient`, `tmp_path` fixture for isolated CSV, `monkeypatch` to swap `CSV_PATH`. Helper `_valid_payload(**overrides)` builds normoglycemic base payloads.
