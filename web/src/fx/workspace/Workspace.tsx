// The Argus Ice workspace: a sidebar of named sections and the workspace's own pages (overview, incidents, one
// incident, glossary) as items of the app's grid; the other sections are the views of the view host. Every
// number on these pages is one the API sent; the pages only pick, order and label them in plain words.

import { lazy, Suspense, useEffect, useLayoutEffect, useState, type ComponentType, type ReactNode } from "react";
import { Mark } from "../../components/Header";
import { useAgentDemo } from "../../lib/agentDemo";
import type { RunView } from "../../lib/store";
import type { Graph } from "../../lib/types";
import { autonomyCounts } from "../../views/autonomy";
import { investigations } from "../../views/model";
import { EntryGate } from "../entry/EntryGate";
import { fxOn } from "../flag";
import { go, useLocation, watchHost, type Section } from "../nav";
import { AgentDemoControl } from "./AgentDemoControl";
import { AgentPage } from "./AgentPage";
import { AgentProvider, useAgent, useHumanActions } from "./agent";
import { AskPanel, setAskOpen, useAskOpen } from "./AskPanel";
import { IncidentPage } from "./IncidentPage";
import { Overview } from "./Overview";
import { GlossaryPage, IncidentsPage } from "./Pages";
import { StoryPanel } from "./StoryPanel";
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
  return (
    <AgentProvider stream={props.view.stream}>
      <Workspace {...props} />
    </AgentProvider>
  );
}

/** Lane G's village view, when its folder exists: `web/src/village/Village.tsx`, default (or `Village`) export. */
export interface VillageProps {
  graph: Graph | null;
  view: RunView;
  onSelectNode: (id: string) => void;
}
type VillageModule = { default?: ComponentType<VillageProps>; Village?: ComponentType<VillageProps> };
// import.meta.glob instead of import(): an absent folder builds to an empty map instead of failing
const villageFiles = import.meta.glob<VillageModule>("../../village/Village.tsx");
const importVillage = villageFiles["../../village/Village.tsx"];
const Village = importVillage
  ? lazy(() =>
      importVillage().then((m) => {
        const component = m.default ?? m.Village;
        if (!component) throw new Error("web/src/village/Village.tsx exports no component");
        return { default: component };
      }),
    )
  : null;

function Workspace({ graph, view, onOpenIncident, onSelectNode }: WorkspaceProps) {
  const { section, incident } = useLocation();
  const demo = useAgentDemo();
  useLayoutEffect(() => {
    document.documentElement.dataset.fxSection = section;
    if (window.matchMedia("(max-width: 1179px)").matches) window.scrollTo(0, 0);
  }, [section]);
  useEffect(() => watchHost(), []);
  return (
    <>
      <Sidebar section={section} view={view} />
      {section === "dashboard" && <Overview graph={graph} view={view} onOpenIncident={onOpenIncident} onSelectNode={onSelectNode} />}
      {section === "incidents" && <IncidentsPage graph={graph} view={view} onOpenIncident={onOpenIncident} />}
      {section === "incident" && incident && <IncidentPage key={incident} id={incident} graph={graph} view={view} onSelectNode={onSelectNode} />}
      {section === "glossary" && <GlossaryPage />}
      {section === "agent" && <AgentPage />}
      {section === "village" && Village && (
        <main className="fx-dash ws-page ws-village" aria-label="village">
          <Suspense fallback={<p className="fx-empty">Loading the village…</p>}>
            <Village graph={graph} view={view} onSelectNode={onSelectNode} />
          </Suspense>
        </main>
      )}
      {section === "graph" && <StoryPanel graph={graph} view={view} />}
      <AskPanel key={demo?.runId} incident={section === "incident" ? incident : null} />
      <EntryGate />
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
  /** shown only when this says so (the agent's routes are mounted, lane G's view exists) */
  when?: "agent" | "village";
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
    id: "agent",
    group: "Monitor",
    label: "Agent activity",
    hint: "Every step the Argus agent took, and what the verdict gate let through",
    icon: <path d="M8 2.5v2M4.5 6.5h7a1.5 1.5 0 0 1 1.5 1.5v3.5a1.5 1.5 0 0 1-1.5 1.5h-7a1.5 1.5 0 0 1-1.5-1.5v-3.5a1.5 1.5 0 0 1 1.5-1.5zM6.2 9.4v.1M9.8 9.4v.1M1.5 9v1.5M14.5 9v1.5" />,
    when: "agent",
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
    id: "village",
    group: "Explore",
    label: "Village",
    hint: "The shop as a village: every metric a place you can walk to",
    icon: <path d="M2 13.5h12M3.5 13.5v-5l3-2.5 3 2.5v5M9.5 13.5v-3.5l2.25-2 2.25 2v3.5M5.5 13.5v-2.5h2v2.5" />,
    when: "village",
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
  const [menuOpen, setMenuOpen] = useState(false);
  const counts = autonomyCounts(view);
  const value = (key: string) => counts.find((c) => c.key === key)?.value ?? 0;
  const running = investigations(view).some((inv) => !view.steps.some((s) => s.anomalyId === inv.anomalyId && s.step.kind === "verdict"));
  const open = Object.values(view.incidents).filter((i) => i.state !== "resolved").length;
  const current = section === "incident" ? "incidents" : section;
  const agent = useAgent();
  const asking = useAskOpen();
  const humans = useHumanActions(view);
  const items = NAV.filter((item) => (item.when === "agent" ? agent.enabled : item.when === "village" ? Village !== null : true));
  return (
    <nav
      className="fx-side"
      aria-label="sections"
      data-menu-open={menuOpen}
      onKeyDown={(event) => {
        if (event.key !== "Escape" || !menuOpen) return;
        event.stopPropagation();
        setMenuOpen(false);
        event.currentTarget.querySelector<HTMLButtonElement>(".fx-side-menu")?.focus();
      }}
    >
      <div className="fx-side-brand">
        <Mark />
        <div>
          <b>ARGUS</b>
          <span>Shop monitor</span>
        </div>
      </div>
      <button
        type="button"
        className="fx-side-menu"
        aria-expanded={menuOpen}
        aria-controls="fx-side-main"
        onClick={() => setMenuOpen(!menuOpen)}
      >
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d={menuOpen ? "M4 4l8 8M12 4l-8 8" : "M2 4h12M2 8h12M2 12h12"} />
        </svg>
        {menuOpen ? "Close menu" : "Menu"}
      </button>
      <div id="fx-side-main" className="fx-side-main">
      {agent.enabled && (
        <button
          className={`fx-side-ask${asking ? " on" : ""}`}
          onClick={() => {
            setMenuOpen(false);
            setAskOpen(!asking);
          }}
          aria-expanded={asking}
          aria-label="Ask Argus"
          title="Ask Argus (/)"
        >
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2zM5.5 6.5h5M5.5 8.5h3" />
          </svg>
          <span>Ask Argus</span>
          <kbd>/</kbd>
        </button>
      )}
      <ul className="fx-side-nav">
        {items.map((item, i) => (
          <li key={item.id}>
            {item.group !== items[i - 1]?.group && <span className="fx-side-group">{item.group}</span>}
            <button
              className={`fx-side-item${current === item.id ? " on" : ""}`}
              aria-current={current === item.id ? "page" : undefined}
              aria-label={item.label}
              title={item.hint}
              onClick={(event) => {
                if (menuOpen) event.currentTarget.closest("nav")?.querySelector<HTMLButtonElement>(".fx-side-menu")?.focus();
                setMenuOpen(false);
                go(item.id);
              }}
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
      </div>
      <AgentDemoControl />
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
            <dt title="Decisions people made: approvals and denials. Everything else Argus did on its own.">human actions</dt>
            <dd>{humans}</dd>
          </div>
        </dl>
      </div>
    </nav>
  );
}
