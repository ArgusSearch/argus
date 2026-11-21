// Follow-tail scrolling, the way T3 Code's timeline does it (useTimelineFollow / timelineViewport, pingdotgg/t3code,
// MIT; rewritten for Argus): the list keeps its newest line in view only while the reader is at the end. Any move
// of the reader's away from the end lets go; scrolling back to the end, or "Jump to latest", follows again. What
// arrives while the reader is elsewhere is counted for the jump button. Pure state; the hook wires it to a scroller.

/** Whether the list keeps its end in view. Released, `atEnd` tracks whether the reader still sits at the end. */
export type Follow = { readonly mode: "following" } | { readonly mode: "released"; readonly atEnd: boolean };

export const FOLLOWING: Follow = { mode: "following" };

export type FollowEvent = "navigated" | "followEnd" | "reachedEnd" | "leftEnd";

export function transition(state: Follow, event: FollowEvent): Follow {
  switch (event) {
    case "navigated":
      return state.mode === "released" ? state : { mode: "released", atEnd: true };
    case "followEnd":
      return FOLLOWING;
    case "reachedEnd":
      // a scroll key pressed at the end stays released until the list has left the end and come back
      return state.mode === "released" && !state.atEnd ? FOLLOWING : state;
    case "leftEnd":
      // while following, growth leaves the end for a frame before the follow scroll catches up
      return state.mode === "released" && state.atEnd ? { mode: "released", atEnd: false } : state;
  }
}

/** One attempt of the reader's to move the list. */
export type Navigation =
  | { readonly source: "wheel"; readonly up: boolean }
  | { readonly source: "key"; readonly up: boolean }
  | { readonly source: "touch" }
  | { readonly source: "pointer"; readonly onScrollbar: boolean };

/**
 * Whether a navigation can carry the list away from its end. Upward input lets go when the content can scroll up;
 * downward input only counts away from the end, so a gesture during growth cannot let go by accident.
 */
export function releases(nav: Navigation, view: { canScrollUp: boolean; awayFromEnd: boolean }): boolean {
  switch (nav.source) {
    case "wheel":
      return nav.up && view.canScrollUp;
    case "key":
      return nav.up ? view.canScrollUp : view.awayFromEnd;
    case "pointer":
      return nav.onScrollbar ? view.canScrollUp : view.awayFromEnd;
    case "touch":
      return view.awayFromEnd;
  }
}

/** Within this many pixels of the bottom counts as the end (T3 Code uses the same band). */
export const END_BAND_PX = 40;

export function atEnd(el: { scrollHeight: number; scrollTop: number; clientHeight: number }, band = END_BAND_PX): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= band;
}

/** Follow mode plus how many items the reader has seen, so the jump button can say how many are new. */
export interface Tail {
  readonly follow: Follow;
  readonly count: number;
  readonly seen: number;
}

export type TailEvent = { readonly type: FollowEvent } | { readonly type: "count"; readonly count: number };

export function initialTail(count: number): Tail {
  return { follow: FOLLOWING, count, seen: count };
}

export function tailReducer(state: Tail, event: TailEvent): Tail {
  if (event.type === "count") {
    if (event.count === state.count) return state;
    const following = state.follow.mode === "following";
    // a shrinking list (a new stream starts over) is seen as it is
    return { ...state, count: event.count, seen: following || event.count < state.seen ? event.count : state.seen };
  }
  const follow = transition(state.follow, event.type);
  if (follow === state.follow) return state;
  return { ...state, follow, seen: follow.mode === "following" ? state.count : state.seen };
}

/** Items that arrived while the reader was away from the end. */
export function unseen(state: Tail): number {
  return state.follow.mode === "following" ? 0 : Math.max(0, state.count - state.seen);
}

/** The jump button's words: "Jump to latest" and, when some arrived, "(3 new)". */
export function jumpLabel(newCount: number, noun = "new"): string {
  return newCount > 0 ? `Jump to latest (${newCount} ${noun})` : "Jump to latest";
}
