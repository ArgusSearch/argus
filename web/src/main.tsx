import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { StyleProvider } from "./fx";
import "./styles.css";
import "./ui/responsive.css";

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <StyleProvider>
      <App />
    </StyleProvider>
  </StrictMode>,
);
