import type { ReactNode } from "react";
import { fxOn } from "../flag";
import { cx } from "./cx";

/** A `//` label in the HUD type: mono, uppercase, tracked. Without the flag a plain span. */
export function HudLabel({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={fxOn() ? cx("fx-hud", className) : className}>{children}</span>;
}
