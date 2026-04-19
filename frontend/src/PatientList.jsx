import { useState, useEffect } from "react";

export default function PatientList({ api }) {
  const [patients, setPatients] = useState([]);
  const [filter, setFilter] = useState("");
  const [search, setSearch] = useState("");
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    setLoading(true);
    setLoadError("");
    fetch(`${api}/api/patients`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setPatients(data);
        setLoading(false);
      })
      .catch((e) => {
        console.error("patient list fetch failed", e);
        setLoadError("Cannot load patients. Is the backend running?");
        setLoading(false);
      });
  }, [api]);

  const filtered = patients.filter((p) => {
    if (filter && p.metabolic_group !== filter) return false;
    if (search && !p.patient_label.toLowerCase().includes(search.toLowerCase()))
      return false;
    return true;
  });

  async function showDetail(label) {
    try {
      const res = await fetch(`${api}/api/patients/${label}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setDetail(await res.json());
    } catch (e) {
      console.error("patient detail fetch failed", e);
      setLoadError(`Could not load details for ${label}.`);
    }
  }

  return (
    <>
      <div className="card">
        <h2>Registered Patients ({patients.length})</h2>
        <div className="filters">
          <input
            placeholder="Search by label..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All Groups</option>
            <option value="normoglycemic">Normoglycemic</option>
            <option value="T1DM">T1DM</option>
            <option value="T2DM">T2DM</option>
          </select>
        </div>

        {loading ? (
          <p>Loading...</p>
        ) : loadError ? (
          <div className="block-error">{loadError}</div>
        ) : filtered.length === 0 ? (
          <p style={{ color: "#999", padding: 16 }}>No patients found.</p>
        ) : (
          <table className="patient-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Age</th>
                <th>Sex</th>
                <th>Metabolic Group</th>
                <th>Registered</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((p) => (
                <tr key={p.patient_label} onClick={() => showDetail(p.patient_label)}>
                  <td><strong>{p.patient_label}</strong></td>
                  <td>{p.age}</td>
                  <td>{p.sex}</td>
                  <td>{p.metabolic_group}</td>
                  <td>{new Date(p.registered_at_utc).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {detail && (
        <div className="detail-overlay" onClick={() => setDetail(null)}>
          <div className="detail-card" onClick={(e) => e.stopPropagation()}>
            <h2 style={{ marginBottom: 16 }}>{detail.patient_label}</h2>
            <table className="review-table">
              <tbody>
                {Object.entries(detail).map(([key, val]) => (
                  <tr key={key}>
                    <td>{key.replace(/_/g, " ")}</td>
                    <td>{val === true ? "Yes" : val === false ? "No" : val ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="btn-group" style={{ justifyContent: "flex-end" }}>
              <button className="btn btn-secondary" onClick={() => setDetail(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
