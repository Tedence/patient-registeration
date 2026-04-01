# Patient Registration App — System Plan

**Author**: Matan Orr
**Date**: March 2026
**Status**: Draft

---

## 1. Purpose

A locally-hosted browser app that registers patients and assigns them a `patient_label`. A patient registers once. That label follows them through every session, TDMS file, and pipeline run forever.

**Scope: registration and demographics only.** No session management, no event logging, no meal tracking.

---

## 2. Architecture

```
Browser (localhost:3000)          FastAPI (localhost:8000)          patients.csv
┌──────────────────┐   POST      ┌──────────────────┐   append    ┌──────────────┐
│ React form       │ ──────────→ │ Pydantic validate │ ─────────→ │ local file   │
│ + patient list   │ ←────────── │ + label generate  │            │ append-only  │
└──────────────────┘   JSON      └──────────────────┘            └──────────────┘
```

| Component | Tech | Why |
|-----------|------|-----|
| Frontend | React (Vite) | Fast, you know it |
| Backend | FastAPI | Typed, Python, matches pipeline stack |
| Storage | CSV (append-only) | Zero infra. Migrates to TimescaleDB in Phase 2 |
| Validation | Pydantic | Schema enforcement before write |

---

## 3. Demographics Schema

### Auto-Generated (operator never touches these)

| Field | Type | Logic |
|-------|------|-------|
| `patient_label` | string | `GY_{seq:02d}` — auto-incremented from CSV |
| `registered_at_utc` | datetime | Server clock at submission |

### Required Fields

| Field | Type | Validation | Why |
|-------|------|-----------|-----|
| `age` | int | 18–65 | Protocol inclusion criterion |
| `sex` | enum | `male`, `female` | Biological covariate |
| `height_cm` | int | 100–220 | BMI |
| `weight_kg` | float | 30–300 | BMI |
| `bmi` | float | Auto-calc: `weight / (height/100)^2` | Key covariate |
| `metabolic_group` | enum | `T1DM`, `T2DM`, `normoglycemic` | Protocol stratification |
| `diabetes_duration_years` | int \| null | Required if T1DM/T2DM | Disease progression context |
| `diabetes_medication` | string \| null | Required if T1DM/T2DM | Affects glucose dynamics |
| `insulin_use` | enum \| null | `pump`, `injections`, `none` | Required if T1DM/T2DM |
| `smoking_status` | enum | `current`, `former`, `never` | Vascular confounder |
| `cgm_device_type` | enum | `libre`, `medtronic`, `dexcom`, `other` | Determines CGM parser in pipeline |
| `cgm_own_device` | bool | | Study-placed CGM needs ≥1hr warm-up |
| `dominant_hand` | enum | `left`, `right` | Apple Watch goes on non-dominant wrist |

### Optional Fields

| Field | Type | Why |
|-------|------|-----|
| `hba1c_percent` | float \| null | Gold standard glucose control baseline |
| `hba1c_date` | date \| null | Recency of HbA1c measurement |
| `blood_pressure_systolic` | int \| null | Cardiovascular baseline |
| `blood_pressure_diastolic` | int \| null | Cardiovascular baseline |
| `resting_heart_rate` | int \| null | Cardiovascular baseline |
| `known_conditions` | string \| null | Free text — comorbidities |
| `current_medications` | string \| null | Free text — all meds, not just diabetes |
| `ethnicity` | string \| null | Free text — potential covariate |
| `skin_condition_notes` | string \| null | Sensor placement issues |
| `operator_notes` | string \| null | Catch-all |

---

## 4. Features

### 4.1 Registration Form

- Two sections: **Required → Optional → Review → Submit**
- BMI auto-calculates as operator types height/weight
- Conditional fields: diabetes-specific fields hidden when `normoglycemic` selected
- Inline validation (age range, required fields, numeric bounds)
- Review screen before submit — operator sees everything, confirms, done
- On submit: patient_label shown prominently — operator communicates this to Nadav for TDMS

### 4.2 Patient List

- Table of all registered patients
- Columns: patient_label, age, sex, metabolic_group, registered_at
- Click row to view full demographics (read-only)
- Search/filter by metabolic group

### 4.3 Patient Label Generation

```
Format: GY_{next_sequence:02d}
Sequence: max existing label + 1, read from CSV on startup
Examples: GY_01, GY_02, ..., GY_25, GY_26 (if study expands)
```

This label is the `patient_label` that Nadav enters into LabVIEW → TDMS file properties → ETL pipeline UUID v5 derivation.

### 4.4 Exclusion Check

Soft validation on submit:

| Check | Behavior |
|-------|----------|
| Age outside 18–65 | **Block** — cannot register |
| BMI extreme (< 15 or > 50) | **Warn** — operator can override |

---

## 5. CSV Output

File: `data/patients.csv`

```csv
patient_label,registered_at_utc,age,sex,height_cm,weight_kg,bmi,metabolic_group,diabetes_duration_years,diabetes_medication,insulin_use,smoking_status,cgm_device_type,cgm_own_device,dominant_hand,hba1c_percent,hba1c_date,blood_pressure_systolic,blood_pressure_diastolic,resting_heart_rate,known_conditions,current_medications,ethnicity,skin_condition_notes,operator_notes
GY_01,2026-04-27T08:15:00Z,34,male,178,82,25.9,T1DM,12,Humalog + Lantus,injections,never,libre,true,right,7.2,2026-03-01,120,80,68,,,,,
```

**Rules:**
- Append-only. Never edit existing rows.
- If a correction is needed: register again with a note in `operator_notes`. Deduplicate downstream.
- Manual backup to GCS before each session day.

---

## 6. Data Flow

```
Operator fills form → Submit
    → Backend validates (Pydantic)
    → patient_label auto-generated (GY_XX)
    → Row appended to patients.csv
    → Confirmation screen: "Patient GY_01 registered"
    → Operator tells Nadav: "label is GY_01"
    → Nadav enters into LabVIEW
    → TDMS file gets patient_label property
    → ETL pipeline: uuid5("patient:GY_01") → patient_id
    → demographics from CSV → metadata.json → TimescaleDB (Phase 2)
```

---

## 7. Directory Structure

```
patient-registration/
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── RegistrationForm.jsx
│   │   ├── PatientList.jsx
│   │   └── ReviewScreen.jsx
│   └── package.json
├── backend/
│   ├── main.py              # FastAPI: 3 endpoints
│   ├── models.py             # Pydantic schema
│   └── csv_store.py          # Read/append CSV
├── data/
│   └── patients.csv
├── tests/
│   ├── test_registration.py
│   └── test_validation.py
├── Makefile                  # make run, make test
└── README.md
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/patients` | List all patients |
| `GET` | `/api/patients/{label}` | Get one patient |
| `POST` | `/api/register` | Register new patient |

---

## 8. Implementation Estimate

| Task | Time |
|------|------|
| Pydantic models + CSV writer + FastAPI endpoints | 3 hours |
| React registration form with validation | 4 hours |
| Patient list view | 2 hours |
| Tedence branding | 1 hour |
| Tests | 2 hours |
| **Total** | **~1.5 days** |

---

## 9. Phase 2 Migration

CSV → TimescaleDB `patients` table. One-time import script. CSV remains as backup. No schema changes needed — the CSV columns map 1:1 to database columns.
