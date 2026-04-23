import { useState } from "react";
import RegistrationForm from "./RegistrationForm";
import PatientList from "./PatientList";
import EditTable from "./EditTable";
import SessionsView from "./SessionsView";
import tedenceLogo from "./assets/tedence_logo.png";

const API = "http://localhost:8000";

function App() {
  const [view, setView] = useState("register");

  return (
    <>
      <div className="header">
        <h1>Patient Registration</h1>
        <img src={tedenceLogo} alt="Tedence" className="header-logo" />
      </div>
      <nav>
        <button
          className={view === "register" ? "active" : ""}
          onClick={() => setView("register")}
        >
          Register Patient
        </button>
        <button
          className={view === "list" ? "active" : ""}
          onClick={() => setView("list")}
        >
          Patient List
        </button>
        <button
          className={view === "sessions" ? "active" : ""}
          onClick={() => setView("sessions")}
        >
          Sessions
        </button>
        <button
          className={view === "edit" ? "active" : ""}
          onClick={() => setView("edit")}
        >
          Edit Table
        </button>
      </nav>
      <div className="container">
        {view === "register" && <RegistrationForm api={API} />}
        {view === "list" && <PatientList api={API} />}
        {view === "sessions" && <SessionsView api={API} />}
        {view === "edit" && <EditTable api={API} />}
      </div>
    </>
  );
}

export default App;
