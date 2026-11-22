import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ChallengeGate } from "./challenge";
import { StyleProvider } from "./fx";
import { EntryGate } from "./fx/entry/EntryGate";
import { staticReplay } from "./lib/deployment";
import "./styles.css";

if (staticReplay && new URLSearchParams(location.search).get("demo") === "1") {
  history.replaceState(null, "", "?challenge=reveal");
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <StyleProvider>
      <ChallengeGate>
        {staticReplay ? <EntryGate /> : <App />}
      </ChallengeGate>
    </StyleProvider>
  </StrictMode>,
);
