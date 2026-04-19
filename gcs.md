# GCS Bucket Layout — Tedence ETL Pipeline

**Date**: April 12, 2026
**Status**: Active

---

## Buckets

| Bucket | Purpose | Region |
|---|---|---|
| `gs://tedence-gav-yam/` | New pipeline archive (Gav Yam + future collections) | `me-west1` |

---

## `gs://tedence-gav-yam/` — Archive Layout

```
gs://tedence-gav-yam/
│
├── channel_configs/                              # Channel manifests (per collection setup)
│   ├── hadassah_standard.json
│   └── gav_yam_belt.json
│
└── {patient_label}/                              # e.g. "NG_01" — from filename, human-readable
    │
    ├── cgm/                                      # Patient-level CGM archive
    │   ├── cgm_raw_2026_03_24.xlsx               # Raw CGM file(s), never modified
    │   └── cgm_raw_2026_04_07.xlsx               # Multiple files if sensor swapped
    │
    └── {YYYY_MM_DD}/                             # Date-only session folder, e.g. "2026_03_24"
        ├── {original_filename}.tdms              # Original filename retained, never modified
        │                                         # Multiple files may coexist (different _xx suffix)
        ├── metadata.json                         # Written LAST — existence = processing complete
        ├── quality_report.json                   # Saturation + sampling rate assessment
        └── processed/
            ├── emf_500hz.parquet                 # Butterworth LP 250Hz → decimated to 500Hz
            ├── cgm_clean.parquet                 # Sliced to session window, UTC, no interpolation
            └── saturation_flags.parquet          # Per-sample flags at 500Hz
```

---

## Path Construction

All paths are built by `GCSPaths` in `gcs.py` from `(patient_label, date_folder)`:

| Component | Source | Example |
|---|---|---|
| `patient_label` | TDMS filename | `NG_01` |
| `date_folder` | TDMS filename date components | `2026_03_24` |
| `original_filename` | TDMS filename (unchanged) | `NG_01_2026_03_24_09_30_00_05.tdms` |

Full blob path example:
```
NG_01/2026_03_24/NG_01_2026_03_24_09_30_00_05.tdms
```

---
