// Decides whether this page load starts on the entry screen (gate.ts) and, only then, loads it: the screen and
// the avatars it draws stay out of the main bundle. While it is up, the app behind it is hidden (gate.css reads
// <html data-fx-entry>); entering remembers the choice for this tab and lands on the overview.

import { lazy, Suspense, useCallback, useLayoutEffect, useState } from "react";
import { createPortal } from "react-dom";
import { tokenMs } from "../motion";
import { go } from "../nav";
import { entryWanted, readEntered, rememberEntered, searchAfterEntry } from "./gate";
import "./gate.css";

const EntryPage = lazy(() => import("./EntryPage"));

type Stage = "open" | "leaving" | "gone";

/** Renders the entry screen when this page load wants it; nothing otherwise. */
export function EntryGate() {
  const [stage, setStage] = useState<Stage>(() => (entryWanted(window.location.search, readEntered()) ? "open" : "gone"));

  useLayoutEffect(() => {
    const root = document.documentElement;
    if (stage === "gone") delete root.dataset.fxEntry;
    else root.dataset.fxEntry = stage;
    return () => {
      delete root.dataset.fxEntry;
    };
  }, [stage]);

  const enter = useCallback(() => {
    rememberEntered();
    const search = searchAfterEntry(window.location.search);
    window.history.replaceState(window.history.state, "", window.location.pathname + search + window.location.hash);
    go("dashboard");
    setStage("leaving");
    window.setTimeout(() => setStage("gone"), tokenMs("--fx-dur-move", 600) + 120);
  }, []);

  if (stage === "gone") return null;
  return createPortal(
    <Suspense fallback={null}>
      <EntryPage leaving={stage === "leaving"} onEnter={enter} />
    </Suspense>,
    document.body,
  );
}
