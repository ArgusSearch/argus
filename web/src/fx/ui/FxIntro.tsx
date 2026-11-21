import { useEffect, useState, type ReactNode } from "react";
import { fxOn } from "../flag";
import { timeline, tokenMs } from "../motion";
import { HudLabel } from "./HudLabel";
import { TextReveal } from "./TextReveal";

export interface FxIntroProps {
  title: string;
  kicker?: string;
  /** ms the title card stays before it lifts; the content cascades in under it */
  hold?: number;
  children?: ReactNode;
}

/**
 * A title card over the stage in a dawn tint (A20): the title resolves (A3), the card lifts and the content's
 * panels cascade in (A19). Plays once per mount. Without the flag only the content.
 */
export function FxIntro({ title, kicker, hold = 1400, children }: FxIntroProps) {
  const [card, setCard] = useState<"shown" | "lifting" | "gone">("shown");
  useEffect(() => {
    if (!fxOn()) return;
    // reduced motion turns the duration tokens into 1 ms, and the card with them
    const lift = Math.min(hold, tokenMs("--fx-dur-intro", hold));
    return timeline([
      [lift, () => setCard("lifting")],
      [lift + tokenMs("--fx-dur-move", 600), () => setCard("gone")],
    ]);
  }, [hold]);
  if (!fxOn()) return <>{children}</>;
  return (
    <div className="fx-intro">
      <div className="fx-intro-body">{children}</div>
      {card !== "gone" && (
        <div className={`fx-intro-card${card === "lifting" ? " lifting" : ""}`} aria-hidden="true">
          {kicker && <HudLabel className="fx-intro-kicker">{kicker}</HudLabel>}
          <TextReveal as="div" className="fx-intro-title" text={title} delay={120} />
        </div>
      )}
    </div>
  );
}
