import { useEffect, useMemo, useRef, useState } from "react";
import {
  discardDraft,
  loadDraft,
  newDraftId,
  saveDraft,
} from "./sessionDrafts";

const CGM_OPTIONS = ["libre", "medtronic", "dexcom", "other"];
const INTERVENTION_TYPES = [
  { key: "food", label: "🍽 Food" },
  { key: "ensure", label: "🥤 Ensure" },
  { key: "insulin", label: "💉 Insulin" },
];

function nowIso() {
  return new Date().toISOString();
}

function freshDraft(patientLabel) {
  return {
    draftId: newDraftId(),
    patient_label: patientLabel,
    operator: "",
    cgm_device: "libre",
    started_at_utc: nowIso(),
    events: [],
  };
}

function formatElapsed(fromIso) {
  const ms = Date.now() - new Date(fromIso).getTime();
  if (ms < 0) return "00:00";
  const total = Math.floor(ms / 1000);
  const h = String(Math.floor(total / 3600)).padStart(2, "0");
  const m = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return h === "00" ? `${m}:${s}` : `${h}:${m}:${s}`;
}

function newUuid() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `i_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

export default function SessionRecorder({ api, patientLabel, draftId, onClose }) {
  const [draft, setDraft] = useState(() => {
    const existing = draftId ? loadDraft(draftId) : null;
    return existing || freshDraft(patientLabel);
  });
  const [quickNote, setQuickNote] = useState("");
  const [interventionText, setInterventionText] = useState({
    food: "",
    ensure: "",
    insulin: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState("");
  const [, forceTick] = useState(0);
  const timerRef = useRef();

  // Re-render once per second so the elapsed clock advances.
  useEffect(() => {
    timerRef.current = setInterval(() => forceTick((t) => t + 1), 1000);
    return () => clearInterval(timerRef.current);
  }, []);

  // Autosave on every change — draft survives tab close.
  useEffect(() => {
    saveDraft(draft);
  }, [draft]);

  // All interventions with an unmatched "start" row, grouped by type.
  // Concurrent interventions of the same type are allowed — each becomes
  // its own row with an independent Stop button.
  const ongoingByType = useMemo(() => {
    const starts = new Map();
    const stops = new Set();
    for (const ev of draft.events) {
      if (ev.kind !== "intervention") continue;
      if (ev.phase === "start") starts.set(ev.intervention_id, ev);
      if (ev.phase === "stop") stops.add(ev.intervention_id);
    }
    const out = { food: [], ensure: [], insulin: [] };
    for (const [id, ev] of starts.entries()) {
      if (!stops.has(id)) out[ev.intervention_type].push(ev);
    }
    for (const k of Object.keys(out)) {
      out[k].sort(
        (a, b) => new Date(a.ts_utc).getTime() - new Date(b.ts_utc).getTime()
      );
    }
    return out;
  }, [draft.events]);

  function updateDraft(patch) {
    setDraft((d) => ({ ...d, ...patch }));
  }

  function addEvent(ev) {
    setDraft((d) => ({ ...d, events: [...d.events, ev] }));
  }

  function removeEvent(idx) {
    setDraft((d) => ({
      ...d,
      events: d.events.filter((_, i) => i !== idx),
    }));
  }

  function updateEventText(idx, text) {
    setDraft((d) => ({
      ...d,
      events: d.events.map((e, i) => (i === idx ? { ...e, text } : e)),
    }));
  }

  function addNote() {
    const text = quickNote.trim();
    if (!text) return;
    if (!draft.operator.trim()) {
      setErr("Set operator name before logging events.");
      return;
    }
    addEvent({
      ts_utc: nowIso(),
      kind: "note",
      intervention_type: null,
      phase: null,
      intervention_id: null,
      text,
      operator: draft.operator.trim(),
    });
    setQuickNote("");
    setErr("");
  }

  function startIntervention(type) {
    if (!draft.operator.trim()) {
      setErr("Set operator name before logging events.");
      return;
    }
    const id = newUuid();
    addEvent({
      ts_utc: nowIso(),
      kind: "intervention",
      intervention_type: type,
      phase: "start",
      intervention_id: id,
      text: interventionText[type] || "",
      operator: draft.operator.trim(),
    });
    setInterventionText((t) => ({ ...t, [type]: "" }));
    setErr("");
  }

  function stopIntervention(interventionId, fallbackOperator, type) {
    addEvent({
      ts_utc: nowIso(),
      kind: "intervention",
      intervention_type: type,
      phase: "stop",
      intervention_id: interventionId,
      text: "",
      operator: draft.operator.trim() || fallbackOperator,
    });
  }

  async function endSession() {
    setErr("");
    if (!draft.operator.trim()) {
      setErr("Operator name is required.");
      return;
    }
    if (draft.events.length === 0) {
      if (!confirm("End this session with zero events recorded?")) return;
    }
    setSubmitting(true);
    const payload = {
      patient_label: draft.patient_label,
      operator: draft.operator.trim(),
      cgm_device: draft.cgm_device,
      started_at_utc: draft.started_at_utc,
      ended_at_utc: nowIso(),
      events: draft.events,
    };
    try {
      const res = await fetch(`${api}/api/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        setErr(
          `Save failed: ${(data && data.detail) || `HTTP ${res.status}`} — your draft is kept.`
        );
        setSubmitting(false);
        return;
      }
      discardDraft(draft.draftId);
      setSubmitting(false);
      onClose({ finalized: true, blobPath: data.blob_path });
    } catch (e) {
      console.error(e);
      setErr("Network error. Draft kept — retry when the backend is reachable.");
      setSubmitting(false);
    }
  }

  function cancelKeepDraft() {
    onClose({ finalized: false });
  }

  function cancelDiscard() {
    if (!confirm("Discard this draft? All recorded events will be lost.")) return;
    discardDraft(draft.draftId);
    onClose({ finalized: false });
  }

  return (
    <div className="detail-overlay">
      <div
        className="detail-card"
        style={{ maxWidth: 860, width: "94%", maxHeight: "92vh", overflow: "auto" }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <h2 style={{ margin: 0 }}>
            🔴 Recording — {draft.patient_label}
          </h2>
          <div style={{ fontFamily: "monospace", fontSize: 18 }}>
            ⏱ {formatElapsed(draft.started_at_utc)}
          </div>
        </div>
        <div style={{ color: "#666", fontSize: 13, marginTop: 4 }}>
          Started {new Date(draft.started_at_utc).toLocaleString()} — draft autosaved locally.
        </div>

        <div className="form-row" style={{ marginTop: 12, flexWrap: "wrap" }}>
          <div className="form-group">
            <label>Operator name</label>
            <input
              value={draft.operator}
              onChange={(e) => updateDraft({ operator: e.target.value })}
              placeholder="your name"
            />
          </div>
          <div className="form-group">
            <label>CGM device</label>
            <select
              value={draft.cgm_device}
              onChange={(e) => updateDraft({ cgm_device: e.target.value })}
            >
              {CGM_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </div>
        </div>

        {err && <div className="block-error" style={{ marginTop: 8 }}>{err}</div>}

        <h3 style={{ marginTop: 16 }}>Quick note 📝</h3>
        <div className="form-row" style={{ gap: 8 }}>
          <input
            style={{ flex: 1 }}
            value={quickNote}
            onChange={(e) => setQuickNote(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") addNote();
            }}
            placeholder="e.g. patient reported feeling lightheaded"
          />
          <button className="btn btn-primary" onClick={addNote}>
            Add
          </button>
        </div>

        <h3 style={{ marginTop: 16 }}>Interventions ⏲</h3>
        <p style={{ color: "#666", fontSize: 13, marginTop: -4 }}>
          Multiple concurrent interventions of the same type are allowed —
          each Start creates its own stoppable row.
        </p>
        <table className="patient-table">
          <thead>
            <tr>
              <th>Type</th>
              <th>Label / notes</th>
              <th>Ongoing</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {INTERVENTION_TYPES.map(({ key, label }) => {
              const ongoing = ongoingByType[key];
              return (
                <tr key={key}>
                  <td style={{ verticalAlign: "top" }}>{label}</td>
                  <td>
                    <input
                      value={interventionText[key]}
                      onChange={(e) =>
                        setInterventionText((t) => ({
                          ...t,
                          [key]: e.target.value,
                        }))
                      }
                      placeholder="optional label for next start"
                    />
                  </td>
                  <td>
                    {ongoing.length === 0 ? (
                      <span style={{ color: "#999" }}>none</span>
                    ) : (
                      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        {ongoing.map((ev) => (
                          <div
                            key={ev.intervention_id}
                            style={{
                              display: "flex",
                              gap: 8,
                              alignItems: "center",
                            }}
                          >
                            <span style={{ color: "#c0392b", fontWeight: 600 }}>
                              ●
                            </span>
                            <span style={{ fontSize: 13 }}>
                              {ev.text || "(no label)"} — since{" "}
                              {new Date(ev.ts_utc).toLocaleTimeString()}
                            </span>
                            <button
                              className="btn btn-secondary"
                              onClick={() =>
                                stopIntervention(
                                  ev.intervention_id,
                                  ev.operator,
                                  key
                                )
                              }
                              style={{ padding: "2px 10px", fontSize: 13 }}
                            >
                              Stop
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </td>
                  <td style={{ verticalAlign: "top" }}>
                    <button
                      className="btn btn-primary"
                      onClick={() => startIntervention(key)}
                    >
                      Start
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        <h3 style={{ marginTop: 16 }}>Event log ({draft.events.length})</h3>
        {draft.events.length === 0 ? (
          <p style={{ color: "#999", padding: 8 }}>No events yet.</p>
        ) : (
          <table className="patient-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Kind</th>
                <th>Text</th>
                <th>Operator</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {draft.events.map((ev, idx) => (
                <tr key={idx}>
                  <td style={{ fontFamily: "monospace" }}>
                    {new Date(ev.ts_utc).toLocaleTimeString()}
                  </td>
                  <td>
                    {ev.kind === "note"
                      ? "📝 note"
                      : `${
                          INTERVENTION_TYPES.find(
                            (t) => t.key === ev.intervention_type
                          )?.label || ev.intervention_type
                        } ${ev.phase}`}
                  </td>
                  <td>
                    {ev.kind === "note" ||
                    (ev.kind === "intervention" && ev.phase === "start") ? (
                      <input
                        value={ev.text}
                        onChange={(e) => updateEventText(idx, e.target.value)}
                      />
                    ) : (
                      <span style={{ color: "#999" }}>—</span>
                    )}
                  </td>
                  <td>{ev.operator}</td>
                  <td>
                    <button
                      className="btn btn-secondary"
                      onClick={() => removeEvent(idx)}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div
          className="btn-group"
          style={{ justifyContent: "flex-end", marginTop: 16 }}
        >
          <button
            className="btn btn-secondary"
            onClick={cancelDiscard}
            disabled={submitting}
          >
            Discard draft
          </button>
          <button
            className="btn btn-secondary"
            onClick={cancelKeepDraft}
            disabled={submitting}
          >
            Close (keep draft)
          </button>
          <button
            className="btn btn-primary"
            onClick={endSession}
            disabled={submitting}
          >
            {submitting ? "Uploading..." : "End & upload"}
          </button>
        </div>
      </div>
    </div>
  );
}
