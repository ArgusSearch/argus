// Decides whether this page load starts on the entry screen (gate.ts) and, only then, loads it: the screen and
// the avatars it draws stay out of the main bundle. While it is up, the app behind it is hidden (gate.css reads
// <html data-fx-entry>); entering remembers the choice for this tab and lands on the overview.

import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { ConnectionState } from "../../lib/api";
import { staticReplay } from "../../lib/deployment";
import type { Health } from "../../lib/types";
import { tokenMs } from "../motion";
import { go } from "../nav";
import { entryWanted, readEntered, rememberEntered, searchAfterEntry } from "./gate";
import "./gate.css";

const EntryPage = lazy(() => import("./EntryPage"));

type Stage = "open" | "leaving" | "gone";

/** Renders the entry screen when this page load wants it; nothing otherwise. */
export function EntryGate({ health = null, connection = "connecting" }: {
  health?: Health | null;
  connection?: ConnectionState;
} = {}) {
  const [stage, setStage] = useState<Stage>(() => (staticReplay || entryWanted(window.location.search, readEntered()) ? "open" : "gone"));

  useLayoutEffect(() => {
    if (stage === "gone") return;
    const root = document.documentElement;
    const workspace = document.getElementById("root");
    const wasInert = workspace?.inert ?? false;
    root.dataset.fxEntry = stage;
    // The entry is portalled outside the app root. Keep its background, including notices, out of keyboard focus.
    if (workspace) workspace.inert = true;
    return () => {
      delete root.dataset.fxEntry;
      if (workspace) workspace.inert = wasInert;
    };
  }, [stage]);

  useEffect(() => {
    if (stage !== "leaving") return;
    const timer = window.setTimeout(() => setStage("gone"), tokenMs("--fx-dur-move", 600) + 120);
    return () => window.clearTimeout(timer);
  }, [stage]);

  const enter = useCallback(() => {
    if (stage !== "open") return;
    if (staticReplay) {
      window.location.assign("?challenge=reveal");
      return;
    }
    rememberEntered();
    const search = searchAfterEntry(window.location.search);
    window.history.replaceState(window.history.state, "", window.location.pathname + search + window.location.hash);
    go("dashboard");
    setStage("leaving");
  }, [stage]);

  if (stage === "gone") return null;
  return createPortal(
    <Suspense fallback={null}>
      <EntryPage health={health} connection={connection} leaving={stage === "leaving"} onEnter={enter} />
    </Suspense>,
    document.body,
  );
}
