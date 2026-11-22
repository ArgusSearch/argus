import type { ReactNode } from "react";
import { fxOn } from "../flag";
import { cx } from "./cx";

/** Square corner brackets that snap around the content while `on` (A6). Without the flag only the content. */
export function Bracket({ on = true, children, className }: { on?: boolean; children: ReactNode; className?: string }) {
  if (!fxOn()) return <>{children}</>;
  return <span className={cx("fx-bracket", on && "on", className)}>{children}</span>;
}
