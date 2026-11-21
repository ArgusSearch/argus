// The Argus Ice workspace: a sidebar of named sections and the workspace's own pages (overview, incidents, one
// incident, glossary) as items of the app's grid; the other sections are the views of the view host. Every
// number on these pages is one the API sent; the pages only pick, order and label them in plain words.

import { useEffect, useLayoutEffect, type ReactNode } from "react";
import { Mark } from "../../components/Header";
import type { RunView } from "../../lib/store";
import type { Graph } from "../../lib/types";
import { autonomyCounts } from "../../views/autonomy";
import { investigations } from "../../views/model";
import { fxOn } from "../flag";
import { go, useLocation, watchHost, type Section } from "../nav";
import { IncidentPage } from "./IncidentPage";
import { Overview } from "./Overview";
import { GlossaryPage, IncidentsPage } from "./Pages";
import { tip } from "./plain";

export interface WorkspaceProps {
  graph: Graph | null;
  view: RunView;
  onOpenIncident: (id: string) => void;
  onSelectNode: (id: string) => void;
}

/** Renders nothing without the flag; with it, the sidebar and the workspace's pages as items of the app's grid. */
export function FxWorkspace(props: WorkspaceProps) {
  if (!fxOn()) return null;
  return <Workspace {...props} />;
}

function Workspace({ graph, view, onOpenIncident, onSelectNode }: WorkspaceProps) {
  const { section, incident } = useLocation();
  useLayoutEffect(() => {
    document.documentElement.dataset.fxSection = section;
  }, [section]);
  useEffect(() => watchHost(), []);
  return (
    <>
      <Sidebar section={section} view={view} />
      {section === "dashboard" && <Overview graph={graph} view={view} onOpenIncident={onOpenIncident} onSelectNode={onSelectNode} />}
      {section === "incidents" && <IncidentsPage graph={graph} view={view} onOpenIncident={onOpenIncident} />}
      {section === "incident" && incident && <IncidentPage key={incident} id={incident} graph={graph} view={view} onSelectNode={onSelectNode} />}
      {section === "glossary" && <GlossaryPage />}
    </>
  );
}

/* ------------------------------------------------------------------ sidebar */

interface NavItem {
  id: Section;
  group: string;
  label: string;
  hint: string;
  icon: ReactNode;
}

const NAV: NavItem[] = [
  {
    id: "dashboard",
    group: "Monitor",
    label: "Overview",
    hint: "Shop health, this week's costs and what needs your decision",
    icon: <path d="M2.5 2.5h4.5v6h-4.5zM9 2.5h4.5v3.5h-4.5zM9 8h4.5v5.5h-4.5zM2.5 10.5h4.5v3h-4.5z" />,
  },
  {
    id: "incidents",
    group: "Monitor",
    label: "Incidents",
    hint: "Everything Argus filed, and the alerts it held back",
    icon: <path d="M8 2.2l6 10.8h-12zM8 6.5v3.2M8 11.4v.1" />,
  },
  {
    id: "investigation",
    group: "Monitor",
    label: "Live investigation",
    hint: "Each check Argus runs, step by step, as it runs it",
    icon: <path d="M7 2.5a4.5 4.5 0 1 0 0 9a4.5 4.5 0 1 0 0-9zM10.3 10.3l3.2 3.2" />,
  },
  {
    id: "report",
    group: "Monitor",
    label: "While you slept",
    hint: "The night in a few lines, each with its evidence",
    icon: <path d="M3.5 2.5h9v11h-9zM5.5 5.5h5M5.5 8h5M5.5 10.5h3" />,
  },
  {
    id: "graph",
    group: "Explore",
    label: "Visualization",
    hint: "The shop's metrics and how they depend on each other, in 3D",
    icon: <path d="M3.5 4.5a1.5 1.5 0 1 0 0 .01M12.5 3.5a1.5 1.5 0 1 0 0 .01M12.5 12.5a1.5 1.5 0 1 0 0 .01M5 4.6l6-1M5 5.2l6.4 6.4" />,
  },
  {
    id: "tree",
    group: "Explore",
    label: "Metric tree",
    hint: "Every metric as a searchable tree with its formula",
    icon: <path d="M3 3h4M5 3v10M5 7.5h3.5M5 12.5h3.5M10 6h3.5v3h-3.5zM10 11h3.5v3h-3.5z" />,
  },
  {
    id: "scorecard",
    group: "Proof",
    label: "Track record",
    hint: "Sealed test runs: how often Argus was right, next to a plain threshold alarm",
    icon: <path d="M2.5 13.5h11M4 13.5v-4M7 13.5v-7M10 13.5v-5M13 13.5v-9" />,
  },
  {
    id: "glossary",
    group: "Proof",
    label: "Glossary",
    hint: "The plain meaning of every technical term Argus uses",
    icon: <path d="M2.5 3.5c2-1 3.8-1 5.5.4c1.7-1.4 3.5-1.4 5.5-.4v9.5c-2-1-3.8-1-5.5.4c-1.7-1.4-3.5-1.4-5.5-.4zM8 3.9v9.5" />,
  },
];

function Sidebar({ section, view }: { section: Section; view: RunView }) {
  const counts = autonomyCounts(view);
  const value = (key: string) => counts.find((c) => c.key === key)?.value ?? 0;
  const running = investigations(view).some((inv) => !view.steps.some((s) => s.anomalyId === inv.anomalyId && s.step.kind === "verdict"));
  const open = Object.values(view.incidents).filter((i) => i.state !== "resolved").length;
  const current = section === "incident" ? "incidents" : section;
  return (
    <nav className="fx-side" aria-label="sections">
      <div className="fx-side-brand">
        <Mark />
        <div>
          <b>ARGUS</b>
          <span>Shop monitor</span>
        </div>
      </div>
      <ul className="fx-side-nav">
        {NAV.map((item, i) => (
          <li key={item.id}>
            {item.group !== NAV[i - 1]?.group && <span className="fx-side-group">{item.group}</span>}
            <button
              className={`fx-side-item${current === item.id ? " on" : ""}`}
              aria-current={current === item.id ? "page" : undefined}
              title={item.hint}
              onClick={() => go(item.id)}
            >
              <svg viewBox="0 0 16 16" aria-hidden="true">
                {item.icon}
              </svg>
              <span>{item.label}</span>
              {item.id === "investigation" && running && <i className="fx-side-live" aria-label="investigation running" />}
              {item.id === "incidents" && open > 0 && (
                <em className="fx-side-badge" aria-label={`${open} open`}>
                  {open}
                </em>
              )}
            </button>
          </li>
        ))}
      </ul>
      <div className="fx-side-foot">
        <span className="fx-hud">On its own</span>
        <dl>
          <div>
            <dt>hours watched</dt>
            <dd>{value("hours")}</dd>
          </div>
          <div>
            <dt title={tip("Edge test")}>formula checks</dt>
            <dd>{value("edges")}</dd>
          </div>
          <div>
            <dt>investigations</dt>
            <dd>{value("investigations")}</dd>
          </div>
          <div className="human">
            <dt>human actions</dt>
            <dd>0</dd>
          </div>
        </dl>
      </div>
    </nav>
  );
}
