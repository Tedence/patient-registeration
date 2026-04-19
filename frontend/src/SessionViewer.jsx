import { useCallback, useEffect, useMemo, useState } from "react";

const TOKEN_KEY = "admin_token";
const USER_KEY = "admin_user";

function adminHeaders() {
  return {
    "X-Admin-Token": sessionStorage.getItem(TOKEN_KEY) || "",
    "X-Admin-User": sessionStorage.getItem(USER_KEY) || "",
  };
}

function hasAdminCreds() {
  return !!sessionStorage.getItem(TOKEN_KEY) && !!sessionStorage.getItem(USER_KEY);
}

export default function SessionViewer({ api, blobPath, onClose, onChange }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setErr("");
    try {
      const res = await fetch(`${api}/api/sessions/${blobPath}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const parsed = await res.json();
      setData(parsed);
      setDraft(JSON.parse(JSON.stringify(parsed)));
    } catch (e) {
      console.error(e);
      setErr("Could not load session.");
    }
  }, [api, blobPath]);

  useEffect(() => {
    load();
  }, [load]);

  const pathParts = useMemo(() => blobPath.split("/"), [blobPath]);
  const isAdmin = hasAdminCreds();

  async function save() {
    setMsg("");
    setBusy(true);
    const payload = {
      patient_label: draft.patient_label,
      operator: draft.operator,
      cgm_device: draft.cgm_device,
      started_at_utc: draft.started_at_utc,
      ended_at_utc: draft.ended_at_utc,
      events: draft.events,
    };
    try {
      const res = await fetch(`${api}/api/sessions/${blobPath}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...adminHeaders() },
        body: JSON.stringify(payload),
      });
      const body = await res.json().catch(() => null);
      if (res.status === 401) {
        setMsg("Admin auth failed. Open Edit Table to re-enter credentials.");
        setBusy(false);
        return;
      }
      if (!res.ok) {
        setMsg(`Save failed: ${(body && body.detail) || `HTTP ${res.status}`}`);
        setBusy(false);
        return;
      }
      setMsg("Saved.");
      setEditing(false);
      setBusy(false);
      await load();
      onChange?.();
    } catch (e) {
      console.error(e);
      setMsg("Network error.");
      setBusy(false);
    }
  }

  async function deleteSession() {
    if (!confirm("Delete this session permanently from cloud storage?")) return;
    setMsg("");
    setBusy(true);
    try {
      const res = await fetch(`${api}/api/sessions/${blobPath}`, {
        method: "DELETE",
        headers: adminHeaders(),
      });
      const body = await res.json().catch(() => null);
      if (res.status === 401) {
        setMsg("Admin auth failed. Open Edit Table to re-enter credentials.");
        setBusy(false);
        return;
      }
      if (!res.ok) {
        setMsg(`Delete failed: ${(body && body.detail) || `HTTP ${res.status}`}`);
        setBusy(false);
        return;
      }
      setBusy(false);
      onChange?.();
      onClose();
    } catch (e) {
      console.error(e);
      setMsg("Network error.");
      setBusy(false);
    }
  }

  function updateEvent(idx, patch) {
    setDraft((d) => ({
      ...d,
      events: d.events.map((e, i) => (i === idx ? { ...e, ...patch } : e)),
    }));
  }

  function removeEvent(idx) {
    setDraft((d) => ({
      ...d,
      events: d.events.filter((_, i) => i !== idx),
    }));
  }

  const view = editing ? draft : data;

  return (
    <div className="detail-overlay" onClick={onClose}>
      <div
        className="detail-card"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 860, width: "94%", maxHeight: "92vh", overflow: "auto" }}
      >
        <h2 style={{ marginBottom: 4 }}>
          Session — {pathParts[0]}
        </h2>
        <div style={{ color: "#666", fontSize: 13 }}>{blobPath}</div>

        {err && <div className="block-error" style={{ marginTop: 8 }}>{err}</div>}
        {msg && <div className="warning" style={{ marginTop: 8 }}>{msg}</div>}

        {view && (
          <>
            <table className="review-table" style={{ marginTop: 12 }}>
              <tbody>
                <tr>
                  <td>patient_label</td>
                  <td>{view.patient_label}</td>
                </tr>
                <tr>
                  <td>operator</td>
                  <td>{view.operator}</td>
                </tr>
                <tr>
                  <td>cgm_device</td>
                  <td>{view.cgm_device}</td>
                </tr>
                <tr>
                  <td>started_at_utc</td>
                  <td>{new Date(view.started_at_utc).toLocaleString()}</td>
                </tr>
                <tr>
                  <td>ended_at_utc</td>
                  <td>{new Date(view.ended_at_utc).toLocaleString()}</td>
                </tr>
              </tbody>
            </table>

            <h3 style={{ marginTop: 16 }}>Events ({view.events.length})</h3>
            {view.events.length === 0 ? (
              <p style={{ color: "#999", padding: 8 }}>No events.</p>
            ) : (
              <table className="patient-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Kind</th>
                    <th>Type</th>
                    <th>Phase</th>
                    <th>Text</th>
                    <th>Operator</th>
                    {editing && <th></th>}
                  </tr>
                </thead>
                <tbody>
                  {view.events.map((ev, idx) => (
                    <tr key={idx}>
                      <td style={{ fontFamily: "monospace" }}>
                        {new Date(ev.ts_utc).toLocaleString()}
                      </td>
                      <td>{ev.kind}</td>
                      <td>{ev.intervention_type || "—"}</td>
                      <td>{ev.phase || "—"}</td>
                      <td>
                        {editing ? (
                          <input
                            value={ev.text || ""}
                            onChange={(e) =>
                              updateEvent(idx, { text: e.target.value })
                            }
                          />
                        ) : (
                          ev.text || <span style={{ color: "#999" }}>—</span>
                        )}
                      </td>
                      <td>
                        {editing ? (
                          <input
                            value={ev.operator || ""}
                            onChange={(e) =>
                              updateEvent(idx, { operator: e.target.value })
                            }
                          />
                        ) : (
                          ev.operator
                        )}
                      </td>
                      {editing && (
                        <td>
                          <button
                            className="btn btn-secondary"
                            onClick={() => removeEvent(idx)}
                          >
                            ✕
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}

        <div
          className="btn-group"
          style={{ justifyContent: "flex-end", marginTop: 16 }}
        >
          <button className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Close
          </button>
          {isAdmin && !editing && (
            <>
              <button
                className="btn btn-secondary"
                onClick={deleteSession}
                disabled={busy}
              >
                Delete
              </button>
              <button
                className="btn btn-primary"
                onClick={() => {
                  setDraft(JSON.parse(JSON.stringify(data)));
                  setEditing(true);
                }}
                disabled={busy || !data}
              >
                Edit (admin)
              </button>
            </>
          )}
          {isAdmin && editing && (
            <>
              <button
                className="btn btn-secondary"
                onClick={() => {
                  setEditing(false);
                  setDraft(JSON.parse(JSON.stringify(data)));
                }}
                disabled={busy}
              >
                Cancel edits
              </button>
              <button
                className="btn btn-primary"
                onClick={save}
                disabled={busy}
              >
                Save
              </button>
            </>
          )}
          {!isAdmin && (
            <span style={{ color: "#999", fontSize: 13, alignSelf: "center" }}>
              Open Edit Table to authenticate for editing.
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
