// Follows the graph extension: polls `GET /graph/metrics` (a replay publishes no event for a placement, so the
// version is the signal in both modes) and calls `onGraphChanged` whenever a placement changed the graph.

import { useCallback, useEffect, useRef, useState } from "react";
import { extensionApi } from "./api";
import { nextOfPack } from "./model";
import type { ExtensionState, PlacementResult } from "./types";

const POLL_MS = 1500;
const PACK_STEP_MS = 1400;

export interface GraphExtension {
  state: ExtensionState | null;
  /** the placement on screen: the newest, or the one the viewer picked */
  current: PlacementResult | null;
  select: (name: string | null) => void;
  /** places the rest of the recorded pack, one metric at a time so each lands visibly */
  placePack: () => void;
  busy: boolean;
  error: string | null;
}

export function useGraphExtension(onGraphChanged: () => void): GraphExtension {
  const [state, setState] = useState<ExtensionState | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seen = useRef<string | null>(null);
  const requested = useRef(0);
  const applied = useRef(0);
  const changed = useRef(onGraphChanged);
  changed.current = onGraphChanged;

  const refresh = useCallback(async () => {
    const request = ++requested.current;
    try {
      const next = await extensionApi.state();
      if (request < applied.current) return;
      applied.current = request;
      const key = `${next.stream}:${next.version}`;
      if (seen.current === null ? next.placements.length > 0 : seen.current !== key) {
        changed.current();
        setPicked(null);
      }
      seen.current = key;
      setState(next);
    } catch {
      /* the API is offline or predates the extension: show nothing */
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const placePack = useCallback(() => {
    if (busy) return;
    setBusy(true);
    setError(null);
    const step = async () => {
      try {
        const now = await extensionApi.state();
        const metric = nextOfPack(now);
        if (!metric) return setBusy(false);
        await extensionApi.place(metric);
        await refresh();
        setTimeout(() => void step(), PACK_STEP_MS);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setBusy(false);
      }
    };
    void step();
  }, [busy, refresh]);

  const placements = state?.placements ?? [];
  const current = placements.find((p) => p.metric.name === picked) ?? placements[placements.length - 1] ?? null;
  return { state, current, select: setPicked, placePack, busy, error };
}
