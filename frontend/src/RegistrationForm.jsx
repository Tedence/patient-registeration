import { useState, useMemo } from "react";
import ReviewScreen from "./ReviewScreen";

const INITIAL = {
  age: "",
  sex: "",
  height_cm: "",
  weight_kg: "",
  metabolic_group: "",
  diabetes_duration_years: "",
  diabetes_medication: "",
  insulin_use: "",
  smoking_status: "",
  cgm_device_type: "",
  cgm_own_device: false,
  apple_watch: false,
  // Optional
  first_name: "",
  surname: "",
  blood_type: "",
  last_meal_time: "",
  last_meal_description: "",
  operator_notes: "",
};

function validate(form) {
  const errs = {};
  const age = Number(form.age);
  if (!form.age || isNaN(age)) errs.age = "Required";
  else if (age < 18 || age > 65) errs.age = "Must be 18–65";

  if (!form.sex) errs.sex = "Required";

  const h = Number(form.height_cm);
  if (!form.height_cm || isNaN(h)) errs.height_cm = "Required";
  else if (h < 100 || h > 220) errs.height_cm = "Must be 100–220";

  const w = Number(form.weight_kg);
  if (!form.weight_kg || isNaN(w)) errs.weight_kg = "Required";
  else if (w < 30 || w > 300) errs.weight_kg = "Must be 30–300";

  if (!form.metabolic_group) errs.metabolic_group = "Required";

  const diabetic = form.metabolic_group === "T1DM" || form.metabolic_group === "T2DM";
  if (diabetic) {
    if (!form.diabetes_duration_years) errs.diabetes_duration_years = "Required";
    if (!form.insulin_use) errs.insulin_use = "Required";
  }

  if (!form.smoking_status) errs.smoking_status = "Required";
  if (!form.cgm_device_type) errs.cgm_device_type = "Required";

  return errs;
}

export default function RegistrationForm({ api }) {
  const [form, setForm] = useState(INITIAL);
  const [touched, setTouched] = useState({});
  const [step, setStep] = useState("form"); // form | review | success
  const [result, setResult] = useState(null);
  const [submitError, setSubmitError] = useState("");

  const errors = validate(form);
  const isValid = Object.keys(errors).length === 0;
  const diabetic = form.metabolic_group === "T1DM" || form.metabolic_group === "T2DM";

  const bmi = useMemo(() => {
    const h = Number(form.height_cm);
    const w = Number(form.weight_kg);
    if (h > 0 && w > 0) return (w / (h / 100) ** 2).toFixed(1);
    return null;
  }, [form.height_cm, form.weight_kg]);

  const bmiWarning = bmi && (bmi < 15 || bmi > 50);

  const set = (field, value) => setForm((f) => ({ ...f, [field]: value }));
  const blur = (field) => setTouched((t) => ({ ...t, [field]: true }));

  const err = (field) => touched[field] && errors[field];

  function buildPayload() {
    const payload = {
      age: Number(form.age),
      sex: form.sex,
      height_cm: Number(form.height_cm),
      weight_kg: Number(form.weight_kg),
      metabolic_group: form.metabolic_group,
      smoking_status: form.smoking_status,
      cgm_device_type: form.cgm_device_type,
      cgm_own_device: form.cgm_own_device,
      apple_watch: form.apple_watch,
    };
    if (diabetic) {
      payload.diabetes_duration_years = Number(form.diabetes_duration_years);
      if (form.diabetes_medication) payload.diabetes_medication = form.diabetes_medication;
      payload.insulin_use = form.insulin_use;
    }
    if (form.first_name) payload.first_name = form.first_name;
    if (form.surname) payload.surname = form.surname;
    if (form.blood_type) payload.blood_type = form.blood_type;
    if (form.last_meal_time) payload.last_meal_time = form.last_meal_time;
    if (form.last_meal_description) payload.last_meal_description = form.last_meal_description;
    if (form.operator_notes) payload.operator_notes = form.operator_notes;
    return payload;
  }

  async function handleSubmit() {
    setSubmitError("");
    let res;
    try {
      res = await fetch(`${api}/api/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildPayload()),
      });
    } catch (e) {
      console.error("register network error", e);
      setSubmitError(
        "Cannot reach the registration server. Is the backend running on port 8000?"
      );
      return;
    }

    let data;
    try {
      data = await res.json();
    } catch {
      data = null;
    }

    if (!res.ok) {
      console.error("register failed", res.status, data);
      if (res.status === 503) {
        // Backend already gave us a friendly one-liner via `detail`.
        setSubmitError(
          (data && data.detail) ||
            "Cloud storage is unavailable — registration was not saved. Please retry."
        );
      } else if (res.status === 422) {
        // Pydantic validation — mostly caught client-side already, but just in case.
        setSubmitError(
          "Some fields are invalid. Go back and double-check the form."
        );
      } else {
        setSubmitError(
          (data && data.detail) ||
            `Registration failed (HTTP ${res.status}). Please retry or contact admin.`
        );
      }
      return;
    }

    setResult(data);
    setStep("success");
  }

  if (step === "success" && result) {
    return (
      <div className="card success-card">
        <h2>Registration Complete</h2>
        <div className="label">{result.patient_label}</div>
        <p>Communicate this label to the acquisition operator.</p>
        {result.warnings?.length > 0 && (
          <div className="warning">
            {result.warnings.map((w, i) => (
              <div key={i}>{w}</div>
            ))}
          </div>
        )}
        <button
          className="btn btn-primary"
          onClick={() => {
            setForm(INITIAL);
            setTouched({});
            setStep("form");
            setResult(null);
          }}
        >
          Register Another
        </button>
      </div>
    );
  }

  if (step === "review") {
    return (
      <ReviewScreen
        form={form}
        bmi={bmi}
        diabetic={diabetic}
        bmiWarning={bmiWarning}
        onBack={() => setStep("form")}
        onConfirm={handleSubmit}
        error={submitError}
      />
    );
  }

  return (
    <>
      <div className="card">
        <h2>Required Information</h2>

        <div className="form-row">
          <div className="form-group">
            <label>Age</label>
            <input
              type="number"
              value={form.age}
              onChange={(e) => set("age", e.target.value)}
              onBlur={() => blur("age")}
              placeholder="18–65"
            />
            {err("age") && <div className="error">{errors.age}</div>}
          </div>
          <div className="form-group">
            <label>Sex</label>
            <select
              value={form.sex}
              onChange={(e) => set("sex", e.target.value)}
              onBlur={() => blur("sex")}
            >
              <option value="">Select...</option>
              <option value="male">Male</option>
              <option value="female">Female</option>
            </select>
            {err("sex") && <div className="error">{errors.sex}</div>}
          </div>
        </div>

        <div className="form-row">
          <div className="form-group">
            <label>Height (cm)</label>
            <input
              type="number"
              value={form.height_cm}
              onChange={(e) => set("height_cm", e.target.value)}
              onBlur={() => blur("height_cm")}
              placeholder="100–220"
            />
            {err("height_cm") && <div className="error">{errors.height_cm}</div>}
          </div>
          <div className="form-group">
            <label>Weight (kg)</label>
            <input
              type="number"
              step="0.1"
              value={form.weight_kg}
              onChange={(e) => set("weight_kg", e.target.value)}
              onBlur={() => blur("weight_kg")}
              placeholder="30–300"
            />
            {err("weight_kg") && <div className="error">{errors.weight_kg}</div>}
          </div>
        </div>

        <div className="form-group">
          <label>BMI (auto-calculated)</label>
          <div className="bmi-display">
            {bmi || "—"}
            {bmiWarning && (
              <span style={{ color: "#e65100", marginLeft: 8, fontSize: 12 }}>
                Outside expected range (15–50)
              </span>
            )}
          </div>
        </div>

        <div className="form-group">
          <label>Metabolic Group</label>
          <select
            value={form.metabolic_group}
            onChange={(e) => {
              set("metabolic_group", e.target.value);
              if (e.target.value === "normoglycemic") {
                set("diabetes_duration_years", "");
                set("diabetes_medication", "");
                set("insulin_use", "");
              }
            }}
            onBlur={() => blur("metabolic_group")}
          >
            <option value="">Select...</option>
            <option value="normoglycemic">Normoglycemic</option>
            <option value="T1DM">T1DM</option>
            <option value="T2DM">T2DM</option>
          </select>
          {err("metabolic_group") && (
            <div className="error">{errors.metabolic_group}</div>
          )}
        </div>

        {diabetic && (
          <>
            <div className="form-row">
              <div className="form-group">
                <label>Diabetes Duration (years)</label>
                <input
                  type="number"
                  value={form.diabetes_duration_years}
                  onChange={(e) => set("diabetes_duration_years", e.target.value)}
                  onBlur={() => blur("diabetes_duration_years")}
                />
                {err("diabetes_duration_years") && (
                  <div className="error">{errors.diabetes_duration_years}</div>
                )}
              </div>
              <div className="form-group">
                <label>Insulin Use</label>
                <select
                  value={form.insulin_use}
                  onChange={(e) => set("insulin_use", e.target.value)}
                  onBlur={() => blur("insulin_use")}
                >
                  <option value="">Select...</option>
                  <option value="pump">Pump</option>
                  <option value="injections">Injections</option>
                  <option value="none">None</option>
                </select>
                {err("insulin_use") && (
                  <div className="error">{errors.insulin_use}</div>
                )}
              </div>
            </div>
            <div className="form-group">
              <label>Diabetes Medication <span style={{ fontWeight: 400, color: "#999" }}>(optional)</span></label>
              <input
                type="text"
                value={form.diabetes_medication}
                onChange={(e) => set("diabetes_medication", e.target.value)}
                placeholder="e.g. Humalog + Lantus"
              />
            </div>
          </>
        )}

        <div className="form-row">
          <div className="form-group">
            <label>Smoking Status</label>
            <select
              value={form.smoking_status}
              onChange={(e) => set("smoking_status", e.target.value)}
              onBlur={() => blur("smoking_status")}
            >
              <option value="">Select...</option>
              <option value="never">Never</option>
              <option value="former">Former</option>
              <option value="current">Current</option>
            </select>
            {err("smoking_status") && (
              <div className="error">{errors.smoking_status}</div>
            )}
          </div>
          <div className="form-group">
            <label>Apple Watch</label>
            <div className="checkbox-group" style={{ marginTop: 8 }}>
              <input
                type="checkbox"
                checked={form.apple_watch}
                onChange={(e) => set("apple_watch", e.target.checked)}
              />
              <span>Patient wears Apple Watch</span>
            </div>
          </div>
        </div>

        <div className="form-row">
          <div className="form-group">
            <label>CGM Device Type</label>
            <select
              value={form.cgm_device_type}
              onChange={(e) => set("cgm_device_type", e.target.value)}
              onBlur={() => blur("cgm_device_type")}
            >
              <option value="">Select...</option>
              <option value="libre">Libre</option>
              <option value="medtronic">Medtronic</option>
              <option value="dexcom">Dexcom</option>
              <option value="other">Other</option>
            </select>
            {err("cgm_device_type") && (
              <div className="error">{errors.cgm_device_type}</div>
            )}
          </div>
          <div className="form-group">
            <label>CGM Own Device</label>
            <div className="checkbox-group" style={{ marginTop: 8 }}>
              <input
                type="checkbox"
                checked={form.cgm_own_device}
                onChange={(e) => set("cgm_own_device", e.target.checked)}
              />
              <span>Patient uses their own CGM device</span>
            </div>
          </div>
        </div>

      </div>

      <div className="card">
        <h2>Optional Information</h2>

        <div className="form-row">
          <div className="form-group">
            <label>First Name</label>
            <input
              type="text"
              value={form.first_name}
              onChange={(e) => set("first_name", e.target.value)}
            />
          </div>
          <div className="form-group">
            <label>Surname</label>
            <input
              type="text"
              value={form.surname}
              onChange={(e) => set("surname", e.target.value)}
            />
          </div>
        </div>

        <div className="form-group">
          <label>Blood Type</label>
          <select
            value={form.blood_type}
            onChange={(e) => set("blood_type", e.target.value)}
          >
            <option value="">Select...</option>
            <option value="A+">A+</option>
            <option value="A-">A-</option>
            <option value="B+">B+</option>
            <option value="B-">B-</option>
            <option value="AB+">AB+</option>
            <option value="AB-">AB-</option>
            <option value="O+">O+</option>
            <option value="O-">O-</option>
          </select>
        </div>

        <div className="form-row">
          <div className="form-group">
            <label>Last Meal Time</label>
            <input
              type="datetime-local"
              value={form.last_meal_time}
              onChange={(e) => set("last_meal_time", e.target.value)}
            />
          </div>
          <div className="form-group">
            <label>Last Meal Description</label>
            <input
              type="text"
              value={form.last_meal_description}
              onChange={(e) => set("last_meal_description", e.target.value)}
              placeholder="e.g. toast + coffee"
            />
          </div>
        </div>

        <div className="form-group">
          <label>Operator Notes</label>
          <input
            type="text"
            value={form.operator_notes}
            onChange={(e) => set("operator_notes", e.target.value)}
            placeholder="Free text — any relevant notes"
          />
        </div>

        <div className="btn-group">
          <button
            className="btn btn-primary"
            disabled={!isValid}
            onClick={() => {
              setTouched(
                Object.keys(INITIAL).reduce((a, k) => ({ ...a, [k]: true }), {})
              );
              if (isValid) setStep("review");
            }}
          >
            Review
          </button>
        </div>
      </div>
    </>
  );
}
