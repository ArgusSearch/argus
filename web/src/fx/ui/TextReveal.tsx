import type { CSSProperties, ElementType } from "react";
import { fxOn } from "../flag";
import { cx } from "./cx";

/** Longer texts reveal word by word, so a paragraph does not become hundreds of animated spans. */
const MAX_CELLS = 48;

export interface TextRevealProps {
  text: string;
  as?: ElementType;
  className?: string;
  /** ms before the first cell appears */
  delay?: number;
}

/**
 * Two-stage text reveal (A3): every character first shows as a block cell, then resolves to its glyph, left to
 * right. Digits get the same cells as letters: a number is never shown through values it did not have.
 * A new `text` replays the reveal. Without the flag it renders the text as is.
 */
export function TextReveal({ text, as: Tag = "span", className, delay = 0 }: TextRevealProps) {
  if (!fxOn()) return <Tag className={className}>{text}</Tag>;
  const cells = text.length <= MAX_CELLS ? Array.from(text) : text.split(/(\s+)/).filter(Boolean);
  return (
    <Tag key={text} className={cx("fx-reveal", className)} style={{ "--fx-delay": `${Math.max(0, delay)}ms` } as CSSProperties}>
      <span className="fx-sr">{text}</span>
      {cells.map((cell, i) => (
        <span key={i} className="fx-ch" aria-hidden="true" style={{ "--i": Math.min(i, MAX_CELLS) } as CSSProperties}>
          {cell}
        </span>
      ))}
    </Tag>
  );
}
