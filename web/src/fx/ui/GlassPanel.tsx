import type { ElementType, HTMLAttributes } from "react";
import { fxOn } from "../flag";
import { cx } from "./cx";

export interface GlassPanelProps extends HTMLAttributes<HTMLElement> {
  as?: ElementType;
  /** Blur what is behind it. The budget is 3 blurred surfaces over the moving stage, so off by default. */
  blur?: boolean;
}

/** A frosted plate (A4). Without the flag it is the bare element with your class names. */
export function GlassPanel({ as: Tag = "div", blur = false, className, ...rest }: GlassPanelProps) {
  if (!fxOn()) return <Tag className={className} {...rest} />;
  return <Tag className={cx("fx-glass", blur && "fx-glass-blur", className)} {...rest} />;
}
