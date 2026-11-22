import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ChallengeGate } from "./challenge";
import { StyleProvider } from "./fx";
import { StaticWorkspace } from "./fx/workspace/Workspace";
import { staticReplay } from "./lib/deployment";
import "./styles.css";
import "./ui/responsive.css";

if (staticReplay && new URLSearchParams(location.search).get("demo") === "1") {
  history.replaceState(null, "", "?challenge=reveal");
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <StyleProvider>
      <ChallengeGate>
        {staticReplay ? <StaticWorkspace /> : <App />}
      </ChallengeGate>
    </StyleProvider>
  </StrictMode>,
);
