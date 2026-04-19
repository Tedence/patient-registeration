# DEV-31 — Session Recording Feature (implementation notes)

Branch: `DEV-31-session-recording-feature` (cut from master @ `5dc56fb`)
Spec source: `.agent/System/19-04-matan-app-plan.md` §1 + operator Q&A

## Goal
Operators log timestamped notes + timed clinical interventions (food / Ensure / insulin) during a CGM+EMF recording session. One CSV per session, stored at
`gs://tedence-gav-yam/{patient_label}/{session_date}/session_{yyyy-mm-dd-hh-mm-ss}.csv`.

## Storage model

### Session CSV format
Single file per session. Line 1 is a `#`-prefixed metadata line; line 2 is the column header; lines 3+ are events.

```
# patient_label=NG_01,operator=matan,cgm_device=libre,started_at_utc=2026-04-19T20:00:00+00:00,ended_at_utc=2026-04-19T21:30:00+00:00
ts_utc,kind,intervention_type,phase,intervention_id,text,operator
2026-04-19T20:05:11+00:00,note,,,,"patient felt lightheaded",matan
2026-04-19T20:10:00+00:00,intervention,food,start,a1b2c3,"toast + tea",matan
2026-04-19T20:18:45+00:00,intervention,food,stop,a1b2c3,"",matan
```

### Path
`gs://tedence-gav-yam/{patient_label}/{session_date}/session_{start_timestamp}.csv`
- `session_date` = start date, even if session crosses midnight (per spec)
- Multiple concurrent sessions per patient = multiple files in the same date folder

### Columns
| col | type | notes |
| --- | --- | --- |
| `ts_utc` | ISO-8601 UTC | when the event occurred (client clock) |
| `kind` | `note` \| `intervention` | |
| `intervention_type` | `food` \| `ensure` \| `insulin` \| null | null for notes |
| `phase` | `start` \| `stop` \| null | null for notes; paired via `intervention_id` |
| `intervention_id` | string | shared by matching start/stop rows (uuid) |
| `text` | string | free-text; empty allowed on stop rows |
| `operator` | string | self-declared name at event time (may differ across rows if handoff) |

Two-row pairing for interventions = crash-safe; a session CSV with an unmatched start row is still valid data (intervention still in progress when ended).

## Lifecycle

1. **Start** — operator picks patient + supplies `operator` name + `cgm_device`; `started_at_utc = now()`. **No backend call**: session state is client-only draft.
2. **Record** — events append to in-memory state + localStorage draft (`session_draft_{draft_id}`). Any operator on the same browser can edit/delete events. Concurrent interventions allowed; each has own Start/Stop button.
3. **Pause/close tab** — draft survives (localStorage). Operator can resume later from the Sessions view.
4. **End** — operator clicks End → `ended_at_utc = now()` → `POST /api/sessions` with full payload → backend uploads CSV to GCS. On 200, draft is purged. On 503, draft stays → operator retries.
5. **After end** — session is historical, GCS-only. Any operator can **view**; only admin (`X-Admin-Token`) can `PATCH` (full rewrite) or `DELETE`.

## Backend

### New files
- `backend/session_store.py` — pure-function CSV format/parse + blob path helpers.

### Extended files
- `backend/models.py` — `SessionEvent`, `SessionPayload`, `SessionSummary`.
- `backend/gcs_client.py` — `upload_session_csv`, `download_session_csv`, `list_sessions_for_patient`, `delete_session_csv`. `_maybe_inject_failure` now handles `operation="session"`.
- `backend/main.py` — endpoints below. Reuses existing `audit.append_entry` + `require_admin`.

### Endpoints

| method | path | auth | purpose |
| --- | --- | --- | --- |
| POST | `/api/sessions` | none | create: body = `SessionPayload`. 503 on GCS failure. |
| GET | `/api/sessions?patient_label=X` | none | list blob paths for a patient, with parsed summary metadata |
| GET | `/api/sessions/{patient_label}/{date}/{filename}` | none | parsed session (header + events) |
| PATCH | `/api/sessions/{patient_label}/{date}/{filename}` | admin | full rewrite; admin-only |
| DELETE | `/api/sessions/{patient_label}/{date}/{filename}` | admin | hard delete (blob removed); admin-only |

### GCS strict coupling
Session has no local copy on the backend (unlike `patients.csv`). The "strict coupling" shape is simpler:
- create / update = upload to GCS; any failure → 503 + `friendly_error`. Client retains the draft and can retry.
- delete = delete the blob; 503 on failure.

### Audit
Every mutation appends a row to `data/audit_log.jsonl` then best-effort mirrors to GCS:
- `session_create` — `{user, action, label, diff: {blob_path: [null, "..."], event_count: [0, N]}}`
- `session_update` — `{user, action, label, diff: {blob_path, event_count_before, event_count_after}}`
- `session_delete` — `{user, action, label, diff: {blob_path: ["...", null]}}`

Operator name for `session_create` comes from `SessionPayload.operator` (self-declared), consistent with the existing plan's "any operator" rule. Admin mutations use `X-Admin-User`.

## Frontend

### New files
- `frontend/src/SessionsView.jsx` — top-nav view. Patient picker + list of historical + active-draft sessions per patient.
- `frontend/src/SessionRecorder.jsx` — active recording UI (full-screen card).
- `frontend/src/SessionViewer.jsx` — read-only session view; admin can toggle to edit mode (inline rewrite), and delete.

### Extended files
- `frontend/src/App.jsx` — add `"sessions"` nav entry.

### UI shape

**SessionsView**
- Dropdown: pick patient (from `/api/patients`).
- Section: **Active drafts** (scanned from localStorage keys `session_draft_*` matching the selected patient). Each draft row: start time, operator, event count. Buttons: Resume / Discard.
- Section: **Completed sessions** (from `/api/sessions?patient_label=X`). Each row: date, start time, event count. Click → open SessionViewer.
- Button: **+ Start new session** → open SessionRecorder with a fresh draft.

**SessionRecorder** (full-screen overlay)
- Header: patient label (locked), operator name (editable text), CGM device (select: libre/medtronic/dexcom/other).
- Session info: started-at timestamp, elapsed timer.
- Event log (scrollable, chronological):
  - note rows: `[ts] 📝 "text" — operator` with inline edit + delete
  - intervention rows: `[ts] 🍽 food — started` / `[ts] 🍽 food — stopped`; when start without matching stop, row highlighted "ongoing"
- Controls area:
  - Quick-note input + "Add note" button
  - Intervention row per type (Food / Ensure / Insulin). Each row has an input for notes + Start button; when active, swaps to Stop button + "ongoing" pill.
- Footer buttons: **Save draft** (explicit, although autosave runs on every change), **Cancel** (keeps draft), **End Session** (uploads; on success → close + return to SessionsView).

**SessionViewer** (modal card)
- Metadata header (patient, operator, CGM, started, ended, duration).
- Read-only table of events.
- If admin-authed (reuses `admin_token` / `admin_user` sessionStorage from EditTable):
  - "Edit" toggles inline row editing + "Save" and "Delete session" buttons.
  - Save → PATCH with full rebuilt payload.
  - Delete → DELETE, confirm.

### Draft storage

```js
localStorage.setItem(
  `session_draft_${draftId}`,
  JSON.stringify({
    draftId,
    patient_label,
    operator,
    cgm_device,
    started_at_utc,
    events,
  })
);
```
- `draftId` = uuid (`crypto.randomUUID()`) — allows concurrent drafts per patient.
- Autosave on every state change.
- On successful End Session upload, `localStorage.removeItem(key)`.

## Tests (out of scope for this PR — flag for follow-up)
- `tests/test_sessions.py`: POST roundtrip, list/get roundtrip, 404 on missing, 503 on GCS fail mode, admin gating on PATCH/DELETE.
- Frontend: manual smoke (per CLAUDE.md — UI testing is hands-on).

## Deferred / explicit non-goals
- No live CGM/EMG streaming (per Q17).
- No server-side draft store (localStorage only; cross-device resume not supported).
- No audit log row *per event* — only per session create/update/delete.
- No tombstone on session delete — it's a hard delete of the GCS blob. Admin-only for safety.
- No session tests yet (add in a follow-up PR).
