// Which page of the Argus Ice workspace is on screen. Pages of the workspace itself (overview, incidents, one
// incident, glossary) render in Workspace.tsx; the others are the views of the view host (Youssef's ViewHost:
// graph = "Visualization", tree, investigation, morning report, scorecard). The view host keeps its own tab
// state; the layer drives it through its public keyboard shortcuts (1 to 5) and follows it when demo mode
// switches tabs by itself, so neither side edits the other.

import { useSyncExternalStore } from "react";

export type HostView = "graph" | "tree" | "investigation" | "report" | "scorecard";
export type Page = "dashboard" | "incidents" | "incident" | "glossary";
export type Section = Page | HostView;

const HOST_KEYS: Record<HostView, string> = { graph: "1", tree: "2", investigation: "3", report: "4", scorecard: "5" };
const HOST_VIEWS = Object.keys(HOST_KEYS) as HostView[];
const PAGES: readonly Page[] = ["dashboard", "incidents", "incident", "glossary"];

export function isHostView(value: string | null | undefined): value is HostView {
  return HOST_VIEWS.includes(value as HostView);
}

export function isPage(value: string | null | undefined): value is Page {
  return PAGES.includes(value as Page);
}

export interface Location {
  section: Section;
  /** the incident the incident page shows; null on every other page */
  incident: string | null;
}

const HOME: Location = Object.freeze({ section: "dashboard", incident: null });

/** The page a page load starts on: a deep link (?view=tree, ?view=incident&incident=INC-0001) wins, else the overview. */
export function initialLocation(search: string): Location {
  const params = new URLSearchParams(search);
  const asked = params.get("view");
  if (asked === "incident") {
    const incident = params.get("incident");
    return incident ? { section: "incident", incident } : { section: "incidents", incident: null };
  }
  if (isHostView(asked) || isPage(asked)) return { section: asked, incident: null };
  return HOME;
}

/**
 * The page to show when the view host switched to `tab` without the layer asking: demo mode returning to the
 * graph after a verdict means "back to the overview", which is the dashboard here.
 */
export function followHost(tab: HostView, demo: boolean): Section {
  return tab === "graph" && demo ? "dashboard" : tab;
}

/** Where the incident page's back link (and Escape) goes: the page it was opened from, never another incident page. */
export function backFrom(previous: Location): Location {
  return previous.section === "incident" ? HOME : previous;
}

type Listener = () => void;
const listeners = new Set<Listener>();
let current: Location = typeof window === "undefined" ? HOME : initialLocation(window.location.search);
let previous: Location = HOME;
let requested: HostView | null = null;

function set(next: Location) {
  if (next.section === current.section && next.incident === current.incident) return;
  if (current.section !== "incident") previous = current;
  current = next;
  for (const listener of [...listeners]) listener();
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useLocation(): Location {
  return useSyncExternalStore(
    subscribe,
    () => current,
    () => current,
  );
}

/** The view host's tab as its tab bar shows it. */
export function hostTab(): HostView | null {
  const index = [...document.querySelectorAll(".vh-tabs [role=tab]")].findIndex((t) => t.getAttribute("aria-selected") === "true");
  return index >= 0 ? (HOST_VIEWS[index] ?? null) : null;
}

/**
 * Shows a section. A view of the view host switches the host's tab with its own shortcut; the workspace's
 * pages put the graph behind them (hidden), so the scene keeps its place. The incident page leaves the host
 * where it is, so demo mode's own switch back to the graph still registers as a change.
 */
export function go(next: Section, incident: string | null = null) {
  set({ section: next, incident: next === "incident" ? incident : null });
  const tab: HostView | null = isHostView(next) ? next : next === "incident" ? null : "graph";
  if (tab && hostTab() !== tab) {
    requested = tab;
    window.dispatchEvent(new KeyboardEvent("keydown", { key: HOST_KEYS[tab] }));
  }
}

export function openIncidentPage(id: string) {
  go("incident", id);
}

/** Leaves the incident page for the page it was opened from. */
export function back() {
  const to = backFrom(previous);
  go(to.section, to.incident);
}

/** Follows the view host's tab bar: a switch the layer did not ask for (demo mode, the 1 to 5 keys) wins. */
export function watchHost(): () => void {
  const bar = document.querySelector(".vh-tabs");
  if (!bar) return () => undefined;
  const sync = () => {
    const tab = hostTab();
    if (!tab) return;
    if (requested === tab) {
      requested = null;
      return;
    }
    requested = null;
    set({ section: followHost(tab, document.documentElement.classList.contains("argus-demo")), incident: null });
  };
  const observer = new MutationObserver(sync);
  observer.observe(bar, { subtree: true, attributes: true, attributeFilter: ["aria-selected"] });
  return () => observer.disconnect();
}
