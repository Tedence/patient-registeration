import { useCallback, useEffect, useMemo, useState } from "react";

const EDITABLE_COLUMNS = [
  { key: "patient_label", label: "Label", type: "text" },
  { key: "registered_at_utc", label: "Registered", type: "text" },
  { key: "age", label: "Age", type: "number" },
  { key: "sex", label: "Sex", type: "select", options: ["male", "female"] },
  { key: "height_cm", label: "Height", type: "number" },
  { key: "weight_kg", label: "Weight", type: "number" },
  { key: "bmi", label: "BMI", type: "number" },
  {
    key: "metabolic_group",
    label: "Group",
    type: "select",
    options: ["normoglycemic", "T1DM", "T2DM"],
  },
  { key: "diabetes_duration_years", label: "DM years", type: "number" },
  { key: "diabetes_medication", label: "DM meds", type: "text" },
  {
    key: "insulin_use",
    label: "Insulin",
    type: "select",
    options: ["", "pump", "injections", "none"],
  },
  {
    key: "smoking_status",
    label: "Smoking",
    type: "select",
    options: ["never", "former", "current"],
  },
  {
    key: "cgm_device_type",
    label: "CGM",
    type: "select",
    options: ["libre", "medtronic", "dexcom", "other"],
  },
  { key: "cgm_own_device", label: "Own CGM", type: "bool" },
  { key: "apple_watch", label: "Apple Watch", type: "bool" },
  { key: "first_name", label: "First name", type: "text" },
  { key: "surname", label: "Surname", type: "text" },
  {
    key: "blood_type",
    label: "Blood",
    type: "select",
    options: ["", "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"],
  },
  { key: "last_meal_time", label: "Last meal", type: "text" },
  { key: "last_meal_description", label: "Meal desc", type: "text" },
  { key: "operator_notes", label: "Notes", type: "text" },
];

const TOKEN_KEY = "admin_token";
const USER_KEY = "admin_user";

function AuthGate({ onReady }) {
  const [token, setToken] = useState("");
  const [user, setUser] = useState("");
  const [err, setErr] = useState("");

  function submit(e) {
    e.preventDefault();
    if (!token.trim() || !user.trim()) {
      setErr("Both fields are required.");
      return;
    }
    sessionStorage.setItem(TOKEN_KEY, token.trim());
    sessionStorage.setItem(USER_KEY, user.trim());
    onReady();
  }

  return (
    <div className="card">
      <h2>Enter Edit Mode</h2>
      <p style={{ color: "#666", fontSize: 14 }}>
        Requires the shared admin token. Your name is recorded on every change.
      </p>
      <form onSubmit={submit}>
        <div className="form-group">
          <label>Your name</label>
          <input value={user} onChange={(e) => setUser(e.target.value)} />
        </div>
        <div className="form-group">
          <label>Admin token</label>
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
        </div>
        {err && <div className="error">{err}</div>}
        <button className="btn btn-primary" type="submit">
          Continue
        </button>
      </form>
    </div>
  );
}

export default function EditTable({ api }) {
  const [authed, setAuthed] = useState(
    !!sessionStorage.getItem(TOKEN_KEY) && !!sessionStorage.getItem(USER_KEY)
  );
  const [rows, setRows] = useState([]);
  const [edits, setEdits] = useState({}); // {label: {field: value}}
  const [loading, setLoading] = useState(false);
  const [loadErr, setLoadErr] = useState("");
  const [msg, setMsg] = useState("");
  const [showDeleted, setShowDeleted] = useState(false);
  const [adding, setAdding] = useState(false);
  const [newRow, setNewRow] = useState({});

  const adminHeaders = useCallback(
    () => ({
      "X-Admin-Token": sessionStorage.getItem(TOKEN_KEY) || "",
      "X-Admin-User": sessionStorage.getItem(USER_KEY) || "",
    }),
    []
  );

  const loadAll = useCallback(async () => {
    setLoading(true);
    setLoadErr("");
    try {
      const list = await fetch(`${api}/api/patients`).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      });
      const full = await Promise.all(
        list.map((p) =>
          fetch(`${api}/api/patients/${p.patient_label}`).then((r) => r.json())
        )
      );
      setRows(full);
    } catch (e) {
      console.error(e);
      setLoadErr("Could not load patients.");
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    if (authed) loadAll();
  }, [authed, loadAll]);

  const visible = useMemo(
    () => (showDeleted ? rows : rows.filter((r) => !r.deleted_at)),
    [rows, showDeleted]
  );

  if (!authed) return <AuthGate onReady={() => setAuthed(true)} />;

  function logout() {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_KEY);
    setAuthed(false);
  }

  function setCell(label, key, value) {
    setEdits((e) => ({ ...e, [label]: { ...(e[label] || {}), [key]: value } }));
  }

  async function saveRow(label) {
    const patch = edits[label];
    if (!patch || Object.keys(patch).length === 0) return;
    setMsg("");
    const res = await fetch(`${api}/api/patients/${label}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify(coercePatch(patch)),
    });
    await handleResponse(res, label, `${label} saved.`);
    setEdits((e) => {
      const { [label]: _, ...rest } = e;
      return rest;
    });
  }

  async function deleteRow(label) {
    if (!confirm(`Tombstone ${label}? (row kept with deleted_at timestamp)`))
      return;
    const res = await fetch(`${api}/api/patients/${label}`, {
      method: "DELETE",
      headers: adminHeaders(),
    });
    await handleResponse(res, label, `${label} deleted.`);
  }

  async function addRow() {
    const payload = coercePatch(newRow);
    const res = await fetch(`${api}/api/patients`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      setMsg(`Add failed: ${(data && data.detail) || `HTTP ${res.status}`}`);
      return;
    }
    setMsg(`Added ${data.patient_label}.`);
    setAdding(false);
    setNewRow({});
    loadAll();
  }

  async function handleResponse(res, label, ok) {
    const data = await res.json().catch(() => null);
    if (res.status === 401) {
      setMsg("Admin auth failed. Re-enter credentials.");
      logout();
      return;
    }
    if (!res.ok) {
      setMsg(
        `Save failed (${label}): ${(data && data.detail) || `HTTP ${res.status}`}`
      );
      return;
    }
    setMsg(ok + (data?.warnings?.length ? ` (${data.warnings.join("; ")})` : ""));
    loadAll();
  }

  return (
    <>
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2>Edit Mode ({visible.length})</h2>
          <div className="btn-group" style={{ margin: 0 }}>
            <label style={{ fontSize: 14, display: "flex", gap: 4, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={showDeleted}
                onChange={(e) => setShowDeleted(e.target.checked)}
              />
              Show deleted
            </label>
            <button className="btn btn-secondary" onClick={() => setAdding(true)}>
              + Add
            </button>
            <button className="btn btn-secondary" onClick={logout}>
              Exit
            </button>
          </div>
        </div>
        {msg && <div className="warning" style={{ marginTop: 8 }}>{msg}</div>}
        {loadErr && <div className="block-error">{loadErr}</div>}
        {loading ? (
          <p>Loading...</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="patient-table" style={{ fontSize: 12 }}>
              <thead>
                <tr>
                  {EDITABLE_COLUMNS.map((c) => (
                    <th key={c.key}>{c.label}</th>
                  ))}
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => {
                  const e = edits[r.patient_label] || {};
                  const dirty = Object.keys(e).length > 0;
                  return (
                    <tr
                      key={r.patient_label}
                      style={r.deleted_at ? { opacity: 0.45 } : {}}
                    >
                      {EDITABLE_COLUMNS.map((c) => (
                        <td key={c.key}>
                          <Cell
                            col={c}
                            value={c.key in e ? e[c.key] : r[c.key]}
                            onChange={(v) => setCell(r.patient_label, c.key, v)}
                          />
                        </td>
                      ))}
                      <td>
                        <button
                          className="btn btn-primary"
                          disabled={!dirty}
                          style={{ padding: "4px 8px", fontSize: 12 }}
                          onClick={() => saveRow(r.patient_label)}
                        >
                          Save
                        </button>
                        <button
                          className="btn btn-secondary"
                          style={{ padding: "4px 8px", fontSize: 12, marginLeft: 4 }}
                          onClick={() => deleteRow(r.patient_label)}
                          disabled={!!r.deleted_at}
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {adding && (
        <div className="detail-overlay" onClick={() => setAdding(false)}>
          <div className="detail-card" onClick={(ev) => ev.stopPropagation()}>
            <h2>Add Patient (label auto-generated)</h2>
            <table className="review-table">
              <tbody>
                {EDITABLE_COLUMNS.filter(
                  (c) =>
                    !["patient_label", "registered_at_utc", "bmi"].includes(c.key)
                ).map((c) => (
                  <tr key={c.key}>
                    <td>{c.label}</td>
                    <td>
                      <Cell
                        col={c}
                        value={newRow[c.key] ?? ""}
                        onChange={(v) => setNewRow((n) => ({ ...n, [c.key]: v }))}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="btn-group" style={{ justifyContent: "flex-end" }}>
              <button className="btn btn-secondary" onClick={() => setAdding(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={addRow}>
                Add
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function Cell({ col, value, onChange }) {
  if (col.type === "bool") {
    return (
      <input
        type="checkbox"
        checked={!!value}
        onChange={(e) => onChange(e.target.checked)}
      />
    );
  }
  if (col.type === "select") {
    return (
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        {col.options.map((o) => (
          <option key={o} value={o}>
            {o || "—"}
          </option>
        ))}
      </select>
    );
  }
  return (
    <input
      type={col.type}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value)}
      style={{ width: "100%", minWidth: 80 }}
    />
  );
}

function coercePatch(patch) {
  const out = {};
  for (const [k, v] of Object.entries(patch)) {
    if (v === "" || v === null || v === undefined) {
      out[k] = null;
      continue;
    }
    const col = EDITABLE_COLUMNS.find((c) => c.key === k);
    if (col?.type === "number") {
      const n = Number(v);
      if (!Number.isNaN(n)) out[k] = n;
      continue;
    }
    if (col?.type === "bool") {
      out[k] = !!v;
      continue;
    }
    out[k] = v;
  }
  return out;
}
