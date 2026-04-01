const LABELS = {
  age: "Age",
  sex: "Sex",
  height_cm: "Height (cm)",
  weight_kg: "Weight (kg)",
  metabolic_group: "Metabolic Group",
  diabetes_duration_years: "Diabetes Duration (years)",
  diabetes_medication: "Diabetes Medication",
  insulin_use: "Insulin Use",
  smoking_status: "Smoking Status",
  cgm_device_type: "CGM Device Type",
  cgm_own_device: "CGM Own Device",
  apple_watch: "Apple Watch",
  first_name: "First Name",
  surname: "Surname",
  blood_type: "Blood Type",
  last_meal_time: "Last Meal Time",
  last_meal_description: "Last Meal Description",
  apple_watch: "Apple Watch",
  operator_notes: "Operator Notes",
};

export default function ReviewScreen({
  form,
  bmi,
  diabetic,
  bmiWarning,
  onBack,
  onConfirm,
  error,
}) {
  const OPTIONAL_KEYS = ["first_name", "surname", "blood_type", "last_meal_time", "last_meal_description", "operator_notes"];
  const fields = Object.entries(LABELS).filter(([key]) => {
    if (!diabetic && ["diabetes_duration_years", "diabetes_medication", "insulin_use"].includes(key))
      return false;
    if (OPTIONAL_KEYS.includes(key) && !form[key]) return false;
    return true;
  });

  return (
    <div className="card">
      <h2>Review Patient Information</h2>

      {bmiWarning && (
        <div className="warning">
          BMI {bmi} is outside the expected range (15–50). You can still proceed.
        </div>
      )}

      <table className="review-table">
        <tbody>
          {fields.map(([key, label]) => (
            <tr key={key}>
              <td>{label}</td>
              <td>
                {key === "cgm_own_device" || key === "apple_watch"
                  ? form[key] ? "Yes" : "No"
                  : form[key]}
              </td>
            </tr>
          ))}
          <tr>
            <td>BMI (auto-calculated)</td>
            <td>{bmi}</td>
          </tr>
        </tbody>
      </table>

      {error && <div className="block-error" style={{ marginTop: 12 }}>{error}</div>}

      <div className="btn-group">
        <button className="btn btn-secondary" onClick={onBack}>
          Back to Edit
        </button>
        <button className="btn btn-primary" onClick={onConfirm}>
          Confirm &amp; Register
        </button>
      </div>
    </div>
  );
}
