// The 3D stage of the village (lazy loaded with three.js). Mounts the engine into its own element, hands it the
// player, the folded state and the overlay anchors, and reports a failure so the page can fall back to 2D.

import { useEffect, useRef } from "react";
import { qualityMode } from "../../fx/scene/quality";
import type { Player } from "../player";
import type { RoleId } from "../roles";
import type { RoomTelemetry } from "./rooms";
import type { VillageState } from "../timeline";
import { VillageEngine } from "./engine";

export interface VillageSceneProps {
  player: Player;
  state: VillageState;
  telemetry: RoomTelemetry;
  anchors: Map<string, HTMLElement>;
  onSelect: (role: RoleId) => void;
  onHover: (role: RoleId | null) => void;
  onFail: (error: Error) => void;
}

export default function VillageScene({ player, state, telemetry, anchors, onSelect, onHover, onFail }: VillageSceneProps) {
  const mount = useRef<HTMLDivElement>(null);
  const engine = useRef<VillageEngine | null>(null);
  const handlers = useRef({ onSelect, onHover, onFail });
  handlers.current = { onSelect, onHover, onFail };

  useEffect(() => {
    const el = mount.current;
    if (!el) return;
    let e: VillageEngine;
    try {
      e = new VillageEngine({
        mount: el,
        player,
        anchors,
        quality: qualityMode(window.location.search),
        onSelect: (r) => handlers.current.onSelect(r),
        onHover: (r) => handlers.current.onHover(r),
        onFail: (err) => handlers.current.onFail(err),
      });
    } catch (err) {
      handlers.current.onFail(err as Error);
      return;
    }
    engine.current = e;
    (window as unknown as { __village?: VillageEngine }).__village = e;
    return () => {
      e.dispose();
      engine.current = null;
      delete (window as unknown as { __village?: VillageEngine }).__village;
    };
  }, [player, anchors]);

  useEffect(() => {
    engine.current?.setState(state);
  }, [state]);

  useEffect(() => {
    engine.current?.setTelemetry(telemetry);
  }, [telemetry]);

  return <div ref={mount} className="vl-stage3d" />;
}
