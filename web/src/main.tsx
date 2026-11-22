import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ChallengeGate } from "./challenge";
import { StyleProvider } from "./fx";
import "./styles.css";

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <StyleProvider>
      <ChallengeGate>
        <App />
      </ChallengeGate>
    </StyleProvider>
  </StrictMode>,
);
