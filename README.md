# 🏥 Patient Registration App

Patient registration system for the Tedence metabolic research lab. Operators register study participants, the system auto-assigns labels (NG_01, T1_01, T2_01...) and stores records in CSV.

## Stack

- **Backend**: FastAPI + Pydantic (Python)
- **Frontend**: React 19 + Vite
- **Storage**: Append-only CSV (`data/patients.csv`) + GCS mirror to `gs://tedence-gav-yam/`

## Quick Start

```bash
# from repo root
make -C register_app run     # starts both backend & frontend
```

Or run separately:

```bash
# Backend (port 8000)
cd register_app/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (port 3000)
cd register_app/frontend
npm install
npm run dev
```

## ☁️ GCS Integration

On every successful registration, the backend mirrors data into the ETL archive bucket:

1. **Full `patients.csv`** → `gs://tedence-gav-yam/patients.csv` (overwritten with the complete local file)
2. **Per-patient `metadata.json`** → `gs://tedence-gav-yam/{patient_label}/metadata.json`

Upload failures are **non-fatal** — registration still succeeds locally and the error surfaces in `response.warnings`.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `GCS_ENABLED` | `true` | Set to `false` to skip all GCS calls (tests set this automatically). |
| `GCS_BUCKET` | `tedence-gav-yam` | Target bucket name. |
| `GOOGLE_APPLICATION_CREDENTIALS` | — | Path to a service account JSON. Not required if using user ADC (see below). |

### One-time setup for operators

```bash
# 1. Install backend deps (pulls in google-cloud-storage)
cd register_app/backend
pip install -r requirements.txt

# 2. Authenticate with Google (pick ONE):

# Option A — user credentials via gcloud (easiest for local dev)
gcloud auth application-default login

# Option B — service account JSON
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/tedence-sa.json

# 3. Run the backend with GCS enabled
GCS_ENABLED=true GCS_BUCKET=tedence-gav-yam uvicorn main:app --reload --port 8000
```

### Verify it works

```bash
# Register a test patient
curl -X POST http://127.0.0.1:8000/api/register \
  -H "Content-Type: application/json" \
  -d '{"age":30,"sex":"female","height_cm":170,"weight_kg":65,"metabolic_group":"normoglycemic","smoking_status":"never","cgm_device_type":"libre","cgm_own_device":false,"apple_watch":false}'

# Expected: {"patient_label":"NG_0X","warnings":[]}

# Confirm upload
gcloud storage ls gs://tedence-gav-yam/patients.csv gs://tedence-gav-yam/NG_0X/
gcloud storage cat gs://tedence-gav-yam/NG_0X/metadata.json
```

If `warnings` contains a `GCS ... upload failed: ...` message, check credentials and bucket permissions (you need `roles/storage.objectUser` on `tedence-gav-yam`).

## API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/api/register` | Register new patient |
| GET | `/api/patients` | List all (optional `?metabolic_group=` filter) |
| GET | `/api/patients/{label}` | Get single patient by label |

Swagger docs at `http://localhost:8000/docs`

## Data Captured

- **Required**: age, sex, height, weight, metabolic group (T1DM/T2DM/normoglycemic), smoking status, CGM device info, Apple Watch
- **Conditional**: diabetes duration, medication, insulin delivery (T1DM/T2DM only)
- **Optional**: name, blood type, last meal, operator notes
- **Auto-generated**: patient label, BMI, timestamp

## Validation

- Age: 18–65, Height: 100–220cm, Weight: 30–300kg
- BMI soft warning if <15 or >50
- Diabetes fields enforced conditionally per metabolic group

## Tests

```bash
make -C register_app test
# or
python -m pytest register_app/tests/ -v
```

## Project Structure

```
register_app/
├── backend/
│   ├── main.py           # FastAPI endpoints
│   ├── models.py          # Pydantic schemas
│   ├── csv_store.py       # CSV persistence
│   ├── gcs_client.py      # GCS mirror (patients.csv + metadata.json)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── RegistrationForm.jsx
│   │   ├── PatientList.jsx
│   │   └── ReviewScreen.jsx
│   └── package.json
├── data/patients.csv
├── tests/
└── Makefile
```