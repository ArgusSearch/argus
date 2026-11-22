// Small timing helpers for the style layer. No animation library: CSS does the moving, these only decide when.

/** Delay of the item at `index` in a cascade, `step` ms apart; items past `cap` share the last slot. */
export function stagger(index: number, step: number, cap = 12): number {
  const i = Math.max(0, Math.min(Math.floor(index), cap));
  return i * Math.max(0, step);
}

/** A CSS time value ("400ms", "1.25s", " 1ms ") in milliseconds, or the fallback when it is not one. */
export function cssTimeMs(value: string | null | undefined, fallback: number): number {
  const m = /^\s*(-?\d*\.?\d+)(ms|s)\s*$/.exec(value ?? "");
  if (!m) return fallback;
  const n = Number(m[1]) * (m[2] === "s" ? 1000 : 1);
  return Number.isFinite(n) && n >= 0 ? n : fallback;
}

/** A duration token of tokens.css (for example "--fx-dur-intro"), which reduced motion turns into 1 ms. */
export function tokenMs(name: string, fallback: number): number {
  if (typeof document === "undefined") return fallback;
  return cssTimeMs(getComputedStyle(document.documentElement).getPropertyValue(name), fallback);
}

export function reducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

export interface Clock {
  set(run: () => void, ms: number): unknown;
  clear(handle: unknown): void;
}

const windowClock: Clock = {
  set: (run, ms) => setTimeout(run, ms),
  clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/** Runs each step at its offset in ms from now; the returned function cancels the steps not yet run. */
export function timeline(steps: readonly (readonly [number, () => void])[], clock: Clock = windowClock): () => void {
  let live = true;
  const handles = steps.map(([at, run]) =>
    clock.set(() => {
      if (live) run();
    }, Math.max(0, at)),
  );
  return () => {
    live = false;
    for (const h of handles) clock.clear(h);
  };
}
