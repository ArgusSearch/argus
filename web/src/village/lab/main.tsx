// Dev-only lab: the village full-window in the Argus Ice look, without the shell.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
import "../../fx/tokens.css";
import { ArgusVillage } from "../ArgusVillage";

const style = document.createElement("style");
style.textContent = "html,body,#village{margin:0;height:100%;background:#a2a8b5}";
document.head.append(style);

createRoot(document.getElementById("village") as HTMLElement).render(
  <StrictMode>
    <ArgusVillage onMetricMap={() => alert("The shell opens the metric map here.")} />
  </StrictMode>,
);
