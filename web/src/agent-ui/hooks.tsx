// The React side of the agent surfaces' small behaviours: follow-tail scrolling on a scroller, a ticking runtime
// that repaints only its own text (no re-render per second), and the waiting-decisions count in the tab title.

import { useCallback, useEffect, useLayoutEffect, useReducer, useRef } from "react";
import { runClock, formatElapsed } from "./clock";
import { titleWithCount } from "./activity";
import { atEnd, initialTail, jumpLabel, releases, tailReducer, unseen, type Navigation } from "./follow";

const UP_KEYS = new Set(["PageUp", "Home", "ArrowUp"]);
const DOWN_KEYS = new Set(["PageDown", "End", "ArrowDown", " "]);
const SCROLLBAR_HIT_PX = 16;

const reducedMotion = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export interface FollowTail {
  /** put on the scroller */
  ref: (node: HTMLElement | null) => (() => void) | void;
  following: boolean;
  /** items that arrived while the reader was away from the end */
  unseen: number;
  /** scroll to the newest item and follow again */
  jump: () => void;
  /** let go on purpose (the reader opened something above the end) */
  release: () => void;
}

/** Keeps a scroller's newest item in view while the reader is at its end; `count` is how many items it holds. */
export function useFollowTail(count: number): FollowTail {
  const [tail, dispatch] = useReducer(tailReducer, count, initialTail);
  const node = useRef<HTMLElement | null>(null);
  const following = tail.follow.mode === "following";
  const followingRef = useRef(following);

  useLayoutEffect(() => {
    followingRef.current = following;
  }, [following]);

  useLayoutEffect(() => {
    dispatch({ type: "count", count });
  }, [count]);

  // new items while following: stay on the end
  useLayoutEffect(() => {
    const el = node.current;
    if (el && following) el.scrollTop = el.scrollHeight;
  }, [count, following]);

  const ref = useCallback((el: HTMLElement | null) => {
    node.current = el;
    if (!el) return;
    const view = () => ({ canScrollUp: el.scrollTop > 0, awayFromEnd: !atEnd(el) });
    const heard = (nav: Navigation) => {
      if (releases(nav, view())) dispatch({ type: "navigated" });
    };
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && e.deltaY !== 0) heard({ source: "wheel", up: e.deltaY < 0 });
    };
    const onTouch = () => heard({ source: "touch" });
    const onPointer = (e: PointerEvent) =>
      heard({ source: "pointer", onScrollbar: e.target === el && el.getBoundingClientRect().right - e.clientX <= Math.max(SCROLLBAR_HIT_PX, el.offsetWidth - el.clientWidth) });
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || e.isComposing) return;
      if (t && (t.isContentEditable || t.tagName === "TEXTAREA" || t.tagName === "INPUT")) return;
      const up = UP_KEYS.has(e.key) ? true : DOWN_KEYS.has(e.key) ? false : null;
      if (up !== null) heard({ source: "key", up });
    };
    const onScroll = () => dispatch({ type: atEnd(el) ? "reachedEnd" : "leftEnd" });
    // content that grows without a new item (a check's result, an opened group at the end) stays pinned too
    // and content that shrank back to the end (a folded run) follows again, with no scroll event to say so
    const resize = new ResizeObserver(() => {
      if (followingRef.current) el.scrollTop = el.scrollHeight;
      else if (atEnd(el)) dispatch({ type: "reachedEnd" });
    });
    // watch the scroller and each of its children, also children that replace each other (empty note, then list)
    const watchChildren = () => {
      resize.disconnect();
      resize.observe(el);
      for (const child of el.children) resize.observe(child);
    };
    const children = new MutationObserver(watchChildren);
    children.observe(el, { childList: true });
    watchChildren();
    el.addEventListener("wheel", onWheel, { passive: true });
    el.addEventListener("touchmove", onTouch, { passive: true });
    el.addEventListener("pointerdown", onPointer, { passive: true });
    el.addEventListener("keydown", onKey);
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      node.current = null;
      resize.disconnect();
      children.disconnect();
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("touchmove", onTouch);
      el.removeEventListener("pointerdown", onPointer);
      el.removeEventListener("keydown", onKey);
      el.removeEventListener("scroll", onScroll);
    };
  }, []);

  const jump = useCallback(() => {
    dispatch({ type: "followEnd" });
    const el = node.current;
    el?.scrollTo({ top: el.scrollHeight, behavior: reducedMotion() ? "auto" : "smooth" });
  }, []);
  const release = useCallback(() => dispatch({ type: "navigated" }), []);

  return { ref, following, unseen: unseen(tail), jump, release };
}

/** The pill at the bottom of a followed list while the reader is elsewhere. */
export function JumpToLatest({ tail, noun }: { tail: FollowTail; noun?: string }) {
  if (tail.following) return null;
  return (
    <button
      type="button"
      className="au-jump"
      // keep focus where it is: the click scrolls, it does not move the reader's focus
      onPointerDown={(e) => e.preventDefault()}
      onClick={tail.jump}
    >
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M4 6l4 4 4-4" />
      </svg>
      {jumpLabel(tail.unseen, noun)}
    </button>
  );
}

/** How long a run has worked: ticks once a second while live, by writing its own text only. */
export function Elapsed({ id, live, className }: { id: string; live: boolean; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    runClock.observe(id, live, Date.now());
    const el = ref.current;
    if (!el) return;
    const paint = () => {
      const ms = runClock.elapsed(id, Date.now());
      el.textContent = ms === null ? "" : formatElapsed(ms / 1000);
    };
    paint();
    if (!live) return;
    const timer = window.setInterval(paint, 1000);
    return () => window.clearInterval(timer);
  }, [id, live]);
  return <span ref={ref} className={`au-elapsed${className ? ` ${className}` : ""}`} />;
}

/** "(2) Argus · Mission Control" while two decisions wait; the plain title again once none do. */
export function useWaitingTitle(waiting: number) {
  useEffect(() => {
    document.title = titleWithCount(document.title, waiting);
  }, [waiting]);
  useEffect(
    () => () => {
      document.title = titleWithCount(document.title, 0);
    },
    [],
  );
}
