import type { ReactNode } from "react";
import { fxOn } from "../flag";
import { cx } from "./cx";

export interface CornerHudProps {
  tl?: ReactNode;
  tr?: ReactNode;
  bl?: ReactNode;
  br?: ReactNode;
  /** Pin to the window instead of the nearest positioned parent. */
  fixed?: boolean;
  className?: string;
}

/** Four non-interactive labels in the corners, white on the stage (A5). Renders nothing without the flag. */
export function CornerHud({ tl, tr, bl, br, fixed = false, className }: CornerHudProps) {
  if (!fxOn()) return null;
  return (
    <div className={cx("fx-corners", fixed && "fixed", className)} aria-hidden="true">
      {tl != null && <div className="fx-corner tl">{tl}</div>}
      {tr != null && <div className="fx-corner tr">{tr}</div>}
      {bl != null && <div className="fx-corner bl">{bl}</div>}
      {br != null && <div className="fx-corner br">{br}</div>}
    </div>
  );
}
