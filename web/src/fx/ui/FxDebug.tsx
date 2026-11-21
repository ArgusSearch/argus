import { useEffect, useState } from "react";
import { FX_QUALITY, type FxQualityDetail } from "../events";
import { CornerHud } from "./CornerHud";

interface Frames {
  fps: number;
  /** longest frame of the last second, ms */
  worst: number;
}

/** `?fxdebug=1`: the page's frame rate and the scene's quality tier, bottom left, updated once a second. */
export function FxDebug() {
  const [quality, setQuality] = useState<FxQualityDetail | null>(null);
  const [frames, setFrames] = useState<Frames | null>(null);

  useEffect(() => {
    const onQuality = (e: Event) => setQuality((e as CustomEvent<FxQualityDetail>).detail);
    window.addEventListener(FX_QUALITY, onQuality);
    let raf = 0;
    let last = performance.now();
    let start = last;
    let count = 0;
    let worst = 0;
    const tick = (now: number) => {
      count += 1;
      worst = Math.max(worst, now - last);
      last = now;
      if (now - start >= 1000) {
        setFrames({ fps: (count * 1000) / (now - start), worst });
        start = now;
        count = 0;
        worst = 0;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener(FX_QUALITY, onQuality);
    };
  }, []);

  return (
    <CornerHud
      fixed
      className="fx-debug"
      bl={
        <span className="fx-hud">
          {frames ? `${frames.fps.toFixed(0)} fps · worst ${frames.worst.toFixed(1)} ms` : "measuring"}
          {quality && ` · ${quality.tier} · px ${quality.pixelRatio.toFixed(2)} · scene ${quality.fps.toFixed(0)} fps`}
        </span>
      }
    />
  );
}
