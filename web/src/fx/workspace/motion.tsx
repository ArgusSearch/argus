// Motion for the workspace's pages: numbers that count up to the value the API sent, and a light that follows
// the pointer over glass. A count-up only ever ends on the real value, runs under a second, and starts from the
// value shown before (from zero when a page opens); with reduced motion the value is shown at once.

import { useEffect, useRef, useState, type RefObject } from "react";
import { useFx } from "../StyleProvider";

const reduced = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** easeOutCubic: fast start, soft landing, the feel of the layer's `--fx-ease-out` */
const ease = (t: number) => 1 - (1 - t) ** 3;

/**
 * The number to show this frame while it travels to `target`. While the loader still covers the page (the
 * layer's "boot" phase) it waits at zero, so the count is seen.
 */
export function useCountUp(target: number, ms = 900): number {
  const { phase } = useFx();
  const [shown, setShown] = useState(() => (reduced() ? target : 0));
  const from = useRef(shown);
  const current = useRef(shown);
  const waiting = phase === "boot";
  useEffect(() => {
    if (!Number.isFinite(target) || waiting) return;
    if (reduced() || current.current === target) {
      current.current = target;
      setShown(target);
      return;
    }
    from.current = current.current;
    const start = performance.now();
    let frame = 0;
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / ms);
      const value = t >= 1 ? target : from.current + (target - from.current) * ease(t);
      current.current = value;
      setShown(value);
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, ms, waiting]);
  return shown;
}

/** A number that counts up to `value`; `format` turns the frame's value into text (integers by default). */
export function CountUp({ value, format = (n) => Math.round(n).toLocaleString("en-US"), ms }: { value: number; format?: (n: number) => string; ms?: number }) {
  const shown = useCountUp(value, ms);
  return <>{format(shown)}</>;
}

/**
 * Sets `--mx` and `--my` (pixels) on the element under the pointer that carries `data-light`, inside `ref`, so
 * its glass can catch a highlight where the pointer is. One listener for the page, at most once per frame.
 */
export function usePointerLight(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const root = ref.current;
    if (!root || reduced()) return;
    let frame = 0;
    let last: PointerEvent | null = null;
    const apply = () => {
      frame = 0;
      const e = last;
      if (!e) return;
      const target = (e.target as HTMLElement | null)?.closest<HTMLElement>("[data-light]");
      if (!target) return;
      const box = target.getBoundingClientRect();
      target.style.setProperty("--mx", `${(e.clientX - box.left).toFixed(0)}px`);
      target.style.setProperty("--my", `${(e.clientY - box.top).toFixed(0)}px`);
    };
    const onMove = (e: PointerEvent) => {
      last = e;
      if (!frame) frame = requestAnimationFrame(apply);
    };
    root.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      root.removeEventListener("pointermove", onMove);
      cancelAnimationFrame(frame);
    };
  }, [ref]);
}
