import { useSyncExternalStore, type MouseEvent } from "react";
import { analysisURL, readAnalysisQuery, type AnalysisQuery } from "./query";

function subscribe(update: () => void) {
  window.addEventListener("popstate", update);
  return () => window.removeEventListener("popstate", update);
}

export function useWorkspaceSearch() {
  return useSyncExternalStore(subscribe, () => window.location.search, () => "");
}

export function useAnalysisQuery() {
  return readAnalysisQuery(useWorkspaceSearch());
}

export function navigateWorkspaceURL(href: string) {
  if (href === window.location.href) return;
  if (document.documentElement.classList.contains("argus-demo")) window.history.replaceState(null, "", href);
  else window.history.pushState(null, "", href);
  // The workspace already restores its section from the URL on popstate.
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function analysisHref(query: AnalysisQuery | null) {
  return analysisURL(window.location.href, query).href;
}

export function followLink(event: MouseEvent<HTMLAnchorElement>, navigate: () => void) {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  navigate();
}
