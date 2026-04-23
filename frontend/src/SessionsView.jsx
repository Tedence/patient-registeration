import { useCallback, useEffect, useMemo, useState } from "react";
import SessionRecorder from "./SessionRecorder";
import SessionViewer from "./SessionViewer";
import { listDraftsForPatient, discardDraft } from "./sessionDrafts";

export default function SessionsView({ api }) {
  const [patients, setPatients] = useState([]);
  const [patientLabel, setPatientLabel] = useState("");
  const [drafts, setDrafts] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [activeDraftId, setActiveDraftId] = useState(null);
  const [viewingBlobPath, setViewingBlobPath] = useState(null);

  useEffect(() => {
    fetch(`${api}/api/patients`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data) => setPatients(data))
      .catch(() => setErr("Could not load patients."));
  }, [api]);

  const refreshDrafts = useCallback(() => {
    if (!patientLabel) {
      setDrafts([]);
      return;
    }
    setDrafts(listDraftsForPatient(patientLabel));
  }, [patientLabel]);

  const refreshHistory = useCallback(async () => {
    if (!patientLabel) {
      setHistory([]);
      return;
    }
    setLoading(true);
    setErr("");
    try {
      const res = await fetch(
        `${api}/api/sessions?patient_label=${encodeURIComponent(patientLabel)}`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setHistory(data.sessions || []);
    } catch (e) {
      console.error(e);
      setErr("Could not load sessions.");
    } finally {
      setLoading(false);
    }
  }, [api, patientLabel]);

  useEffect(() => {
    refreshDrafts();
    refreshHistory();
  }, [refreshDrafts, refreshHistory]);

  const selectedPatient = useMemo(
    () => patients.find((p) => p.patient_label === patientLabel) || null,
    [patients, patientLabel]
  );

  function handleRecorderClose({ finalized }) {
    setActiveDraftId(null);
    refreshDrafts();
    if (finalized) refreshHistory();
  }

  function handleDiscardDraft(draftId) {
    if (!confirm("Discard this draft? Unsaved events will be lost.")) return;
    discardDraft(draftId);
    refreshDrafts();
  }

  return (
    <>
      <div className="card">
        <h2>Session Recording</h2>
        <p style={{ color: "#666", fontSize: 14 }}>
          Log timestamped notes and timed interventions (food / Ensure / insulin)
          during a CGM + EMF recording session.
        </p>

        <div className="form-group" style={{ maxWidth: 360 }}>
          <label>Patient</label>
          <select
            value={patientLabel}
            onChange={(e) => setPatientLabel(e.target.value)}
          >
            <option value="">— pick a patient —</option>
            {patients.map((p) => (
              <option key={p.patient_label} value={p.patient_label}>
                {p.patient_label} ({p.metabolic_group})
              </option>
            ))}
          </select>
        </div>

        {err && <div className="block-error">{err}</div>}

        {patientLabel && (
          <div className="btn-group">
            <button
              className="btn btn-primary"
              onClick={() => setActiveDraftId("__new__")}
            >
              + Start new session
            </button>
          </div>
        )}
      </div>

      {patientLabel && (
        <div className="card">
          <h3>Active drafts ({drafts.length})</h3>
          {drafts.length === 0 ? (
            <p style={{ color: "#999", padding: 8 }}>
              No drafts in progress for {patientLabel}.
            </p>
          ) : (
            <table className="patient-table">
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Operator</th>
                  <th>CGM</th>
                  <th>Events</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {drafts.map((d) => (
                  <tr key={d.draftId}>
                    <td>{new Date(d.started_at_utc).toLocaleString()}</td>
                    <td>{d.operator || "—"}</td>
                    <td>{d.cgm_device || "—"}</td>
                    <td>{d.events?.length ?? 0}</td>
                    <td>
                      <div className="btn-group" style={{ margin: 0 }}>
                        <button
                          className="btn btn-primary"
                          onClick={() => setActiveDraftId(d.draftId)}
                        >
                          Resume
                        </button>
                        <button
                          className="btn btn-secondary"
                          onClick={() => handleDiscardDraft(d.draftId)}
                        >
                          Discard
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {patientLabel && (
        <div className="card">
          <h3>Completed sessions ({history.length})</h3>
          {loading ? (
            <p>Loading...</p>
          ) : history.length === 0 ? (
            <p style={{ color: "#999", padding: 8 }}>
              No completed sessions yet.
            </p>
          ) : (
            <table className="patient-table">
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Ended</th>
                  <th>Operator</th>
                  <th>CGM</th>
                  <th>Events</th>
                </tr>
              </thead>
              <tbody>
                {history.map((s) => (
                  <tr
                    key={s.blob_path}
                    onClick={() => setViewingBlobPath(s.blob_path)}
                  >
                    <td>{new Date(s.started_at_utc).toLocaleString()}</td>
                    <td>{new Date(s.ended_at_utc).toLocaleString()}</td>
                    <td>{s.operator}</td>
                    <td>{s.cgm_device}</td>
                    <td>{s.event_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {activeDraftId && selectedPatient && (
        <SessionRecorder
          api={api}
          patientLabel={selectedPatient.patient_label}
          draftId={activeDraftId === "__new__" ? null : activeDraftId}
          onClose={handleRecorderClose}
        />
      )}

      {viewingBlobPath && (
        <SessionViewer
          api={api}
          blobPath={viewingBlobPath}
          onClose={() => setViewingBlobPath(null)}
          onChange={refreshHistory}
        />
      )}
    </>
  );
}
