# 🏥 Patient Registration App

Patient registration system for the Tedence metabolic research lab. Operators register study participants, the system auto-assigns labels (NG_01, T1_01, T2_01...) and stores records in CSV.

## Stack

- **Backend**: FastAPI + Pydantic (Python)
- **Frontend**: React 19 + Vite
- **Storage**: Append-only CSV (`data/patients.csv`)

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