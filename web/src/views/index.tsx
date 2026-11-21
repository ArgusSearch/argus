// The view switcher around Mission Control's main area. "Graph" is the existing page (passed as children and
// kept mounted, so it never loses its place); the other views load on first use. Demo mode (?demo=1) drives
// the switcher by itself. Deep link to a view with ?view=tree|investigation|report|scorecard.

import { lazy, Suspense, useCallback, useEffect, useState, type ReactNode } from "react";
import type { RunView } from "../lib/store";
import type { Graph, Health } from "../lib/types";
import { AutonomyStrip } from "./AutonomyStrip";
import { CaptionStrip, useDemo, type DemoTab } from "./demo/DemoMode";
import "./views.css";

const TreeView = lazy(() => import("./TreeView").then((m) => ({ default: m.TreeView })));
const InvestigationView = lazy(() => import("./InvestigationView").then((m) => ({ default: m.InvestigationView })));
const MorningReport = lazy(() => import("./MorningReport").then((m) => ({ default: m.MorningReport })));
const ScorecardView = lazy(() => import("./ScorecardView").then((m) => ({ default: m.ScorecardView })));

export interface ViewHostProps {
  graph: Graph | null;
  view: RunView;
  health: Health | null;
  onSelectNode: (id: string) => void;
  onOpenIncident: (id: string) => void;
  children: ReactNode;
}

const TABS: { id: DemoTab; label: string; key: string }[] = [
  { id: "graph", label: "Graph", key: "1" },
  { id: "tree", label: "Tree", key: "2" },
  { id: "investigation", label: "Investigation", key: "3" },
  { id: "report", label: "Morning report", key: "4" },
  { id: "scorecard", label: "Scorecard", key: "5" },
];

function initialTab(): DemoTab {
  const asked = new URLSearchParams(window.location.search).get("view");
  return TABS.some((t) => t.id === asked) ? (asked as DemoTab) : "graph";
}

export function ViewHost({ graph, view, health, onSelectNode, onOpenIncident, children }: ViewHostProps) {
  const [tab, setTabState] = useState<DemoTab>(initialTab);
  const setTab = useCallback((next: DemoTab) => setTabState(next), []);
  const { options, beat } = useDemo({ view, graph, health, setTab, onOpenIncident });

  // 1-5 switch views (not while typing, and not with a modifier)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented) return;
      const target = e.target as HTMLElement | null;
      if (target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))) return;
      const hit = TABS.find((t) => t.key === e.key);
      if (hit) setTabState(hit.id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const running = view.anomalies.length > 0 && !view.steps.some((s) => s.step.kind === "verdict" && s.anomalyId === view.anomalies[view.anomalies.length - 1].id);
  const fallback = <div className="vw-empty">Loading…</div>;

  return (
    <div className={`vh${options.demo ? " demo" : ""}`}>
      <div className="vh-bar">
        <nav className="vh-tabs" role="tablist" aria-label="views">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              className={`vh-tab${tab === t.id ? " on" : ""}`}
              onClick={() => setTabState(t.id)}
              title={`${t.label} (${t.key})`}
            >
              {t.label}
              {t.id === "investigation" && running && <span className="vh-live" aria-label="investigation running" />}
            </button>
          ))}
        </nav>
        <AutonomyStrip view={view} />
      </div>
      <div className="vh-body">
        <div className="vh-graph" hidden={tab !== "graph"}>
          {children}
        </div>
        {tab !== "graph" && (
          <div className="vh-view" role="tabpanel">
            <Suspense fallback={fallback}>
              {tab === "tree" && <TreeView graph={graph} view={view} onSelectNode={onSelectNode} />}
              {tab === "investigation" && <InvestigationView graph={graph} view={view} onSelectNode={onSelectNode} onOpenIncident={onOpenIncident} />}
              {tab === "report" && <MorningReport view={view} onOpenIncident={onOpenIncident} />}
              {tab === "scorecard" && <ScorecardView />}
            </Suspense>
          </div>
        )}
      </div>
      {beat && <CaptionStrip beat={beat} />}
    </div>
  );
}
