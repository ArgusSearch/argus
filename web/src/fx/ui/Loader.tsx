import { fxOn } from "../flag";
import { CornerHud } from "./CornerHud";
import { cx } from "./cx";

export interface LoaderProps {
  /** Fading out: the glyphs go in 250 ms, the cover in 750 ms. */
  leaving?: boolean;
  label?: string;
}

/** The ASCII loader (A1): one mono line of cells scanning in the middle of the fog. Nothing without the flag. */
export function Loader({ leaving = false, label = "Loading the metric graph" }: LoaderProps) {
  if (!fxOn()) return null;
  return (
    <div className={cx("fx-loader", leaving && "leaving")} role="status" aria-label={label}>
      <CornerHud tl={<span className="fx-hud">Argus</span>} tr="Mission control" bl={label} br="Autonomous watch" />
      <div className="fx-loader-core" aria-hidden="true">
        <span className="fx-loader-line" />
      </div>
    </div>
  );
}
