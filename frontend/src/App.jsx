import { useState } from "react";
import { Dashboard } from "./components/Dashboard.jsx";
import { DeployedConfirmation } from "./utils/DeployedConfirmation.jsx";
import { InstructionManual } from "./components/InstructionManual.jsx";

function App() {
  const [phase, setPhase] = useState("manual");

  if (phase === "manual") {
    return (
      <InstructionManual
        onDeploy={() => setPhase("confirmation")}
        onGoToMap={() => setPhase("dashboard")}
      />
    );
  }

  if (phase === "confirmation") {
    return <DeployedConfirmation onContinue={() => setPhase("dashboard")} />;
  }

  return <Dashboard onReset={() => setPhase("manual")} />;
}

export default App;
