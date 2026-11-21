// Which section of the Argus Ice workspace is on screen: the dashboard (the layer's own start page) or one of
// the views of the view host (Youssef's ViewHost: graph, tree, investigation, morning report, scorecard).
// The view host keeps its own tab state; the layer drives it through its public keyboard shortcuts (1 to 5)
// and follows it when demo mode switches tabs by itself, so neither side edits the other.

import { useSyncExternalStore } from "react";

export type HostView = "graph" | "tree" | "investigation" | "report" | "scorecard";
export type Section = "dashboard" | HostView;

const HOST_KEYS: Record<HostView, string> = { graph: "1", tree: "2", investigation: "3", report: "4", scorecard: "5" };
const HOST_VIEWS = Object.keys(HOST_KEYS) as HostView[];

export function isHostView(value: string | null | undefined): value is HostView {
  return HOST_VIEWS.includes(value as HostView);
}

/** The section a page load starts in: a deep link (?view=tree) wins, else the dashboard. */
export function initialSection(search: string): Section {
  const asked = new URLSearchParams(search).get("view");
  return isHostView(asked) ? asked : "dashboard";
}

/**
 * The section to show when the view host switched to `tab` without the layer asking: demo mode returning to
 * the graph after a verdict means "back to the overview", which is the dashboard here.
 */
export function followHost(tab: HostView, demo: boolean): Section {
  return tab === "graph" && demo ? "dashboard" : tab;
}

type Listener = () => void;
const listeners = new Set<Listener>();
let current: Section = typeof window === "undefined" ? "dashboard" : initialSection(window.location.search);
let requested: HostView | null = null;

function set(next: Section) {
  if (next === current) return;
  current = next;
  for (const listener of [...listeners]) listener();
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useSection(): Section {
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

/** Shows a section; for a view of the view host, switches its tab with the host's own shortcut. */
export function go(next: Section) {
  const tab: HostView = next === "dashboard" ? "graph" : next;
  set(next);
  if (hostTab() !== tab) {
    requested = tab;
    window.dispatchEvent(new KeyboardEvent("keydown", { key: HOST_KEYS[tab] }));
  }
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
    set(followHost(tab, document.documentElement.classList.contains("argus-demo")));
  };
  const observer = new MutationObserver(sync);
  observer.observe(bar, { subtree: true, attributes: true, attributeFilter: ["aria-selected"] });
  return () => observer.disconnect();
}
