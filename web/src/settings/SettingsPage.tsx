import { useMemo, useRef, useState, type ReactNode } from "react";
import { dayLabel, hhmm, humanize } from "../lib/format";
import { AGENT_ROLES } from "../lib/agent";
import type { RunView } from "../lib/store";
import type { Graph } from "../lib/types";
import { go } from "../fx/nav";
import { useAgent } from "../fx/workspace/agent";
import { useIncidents } from "../fx/workspace/ui";
import { ROLE_TEXT } from "../fx/workspace/AvatarSlot";
import { CODE_RULES } from "./constants";
import { useAutonomy, useHealth } from "./data";
import { incidentCost, rulesByAgent } from "./model";
import { SETTINGS_TABS, type SettingsTab } from "./route";
import { Badge, Btn, Card, Empty, LevelPicker, PageHead, Portrait, Preview, Row, Source, SubNav, Switch, type SubNavGroup } from "./ui";

const TITLES: Record<SettingsTab, { title: string; lead: string }> = {
  autonomy: { title: "Autonomy", lead: "What each agent may decide alone and where it asks you first. Argus watches and investigates on its own. Applying a fix requires approval." },
  playbooks: { title: "Playbooks", lead: "The named investigation plans Argus picks from, step by step, depending on which metric moved and which way." },
  thresholds: { title: "Thresholds", lead: "The lines the Watcher scores against and the rules an investigation must meet before it may call a cause." },
  budgets: { title: "Budgets", lead: "What one live agent run may spend, and what this run's investigations cost." },
  "quiet-hours": { title: "Quiet hours", lead: "When Argus may page a person, and what never pages anyone." },
  channels: { title: "Channels", lead: "Where Argus tells you about an incident." },
  sources: { title: "Data sources", lead: "Where Argus reads the shop's numbers and change logs from, and how complete the latest hour is." },
};

const GROUPS: SubNavGroup<SettingsTab>[] = [
  { label: "Agents", items: [{ id: "autonomy", label: "Autonomy" }, { id: "playbooks", label: "Playbooks" }] },
  { label: "Detection", items: [{ id: "thresholds", label: "Thresholds" }, { id: "budgets", label: "Budgets" }] },
  { label: "Notifications", items: [{ id: "quiet-hours", label: "Quiet hours" }, { id: "channels", label: "Channels" }] },
  { label: "Data", items: [{ id: "sources", label: "Data sources" }] },
];

export function SettingsPage({ graph, view }: { graph: Graph | null; view: RunView }) {
  const content = useRef<HTMLDivElement>(null);
  const [tab, setSettingsTab] = useState<SettingsTab>(() => {
    const requested = new URLSearchParams(window.location.search).get("tab");
    return SETTINGS_TABS.find((tab) => tab === requested) ?? "autonomy";
  });
  const t = TITLES[tab];
  const pickTab = (next: SettingsTab) => {
    setSettingsTab(next);
    content.current?.scrollIntoView({ block: "start" });
  };
  return (
    <div className="cs-split cs-settings">
      <aside className="cs-list">
        <span className="cs-side-title">Settings</span>
        <SubNav groups={GROUPS} current={tab} onPick={pickTab} label="settings sections" />
        <Btn onClick={() => go("calendar")}>Open calendar</Btn>
      </aside>
      <div className="cs-main" ref={content}>
        <PageHead title={t.title} lead={t.lead} />
        {tab === "autonomy" && <AutonomyTab view={view} />}
        {tab === "playbooks" && <PlaybooksTab view={view} />}
        {tab === "thresholds" && <ThresholdsTab view={view} />}
        {tab === "budgets" && <BudgetsTab view={view} />}
        {tab === "quiet-hours" && <QuietTab />}
        {tab === "channels" && <ChannelsTab />}
        {tab === "sources" && <SourcesTab graph={graph} view={view} />}
      </div>
    </div>
  );
}

function ReadOnly({ children }: { children: ReactNode }) {
  return (
    <p className="cs-note">
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M4.5 7V5a3.5 3.5 0 0 1 7 0v2M3.5 7h9v6.5h-9z" />
      </svg>
      <span>{children}</span>
    </p>
  );
}

/* ------------------------------------------------------------------ autonomy */

function AutonomyTab({ view }: { view: RunView }) {
  const autonomy = useAutonomy(view.stream);
  const ruled = useMemo(() => (autonomy.data ? rulesByAgent(autonomy.data, AGENT_ROLES) : null), [autonomy.data]);
  if (!ruled) return <Card>{autonomy.error ? <Empty>Could not read GET /autonomy: {autonomy.error}</Empty> : <Empty>Reading the limits…</Empty>}</Card>;
  const probation = autonomy.data?.probation ?? [];
  return (
    <>
      <ReadOnly>
        Read-only policy from <Source>GET /autonomy</Source>.
      </ReadOnly>
      {ruled.agents.map(({ role, rules }) => {
        return (
          <Card
            key={role}
            className="cs-agent-card"
            title={
              <span className="cs-agent-title">
                <Portrait role={role} size={34} />
                {ROLE_TEXT[role].name}
              </span>
            }
          >
            {rules.length === 0 && <Row label="No rule of its own" help="Runs inside the Detective's investigation and follows its limits." />}
            {rules.map((r) => (
              <Row key={r.id} label={r.name} help={`${r.when} ${r.behavior}`}>
                <LevelPicker level={r.level} label={`${ROLE_TEXT[role].name}: ${r.name}`} />
              </Row>
            ))}
            {role === "cartographer" && (
              <Row label="On probation now" help="Graph placements waiting for stronger evidence or your decision before promotion.">
                <span className="cs-chips end">
                  {probation.length === 0 ? <Badge tone="ok">none</Badge> : probation.map((p) => <Badge key={p.id} tone="watch">{p.id}</Badge>)}
                </span>
              </Row>
            )}
          </Card>
        );
      })}
      {ruled.other.length > 0 && (
        <Card title="Other rules">
          {ruled.other.map((r) => (
            <Row key={r.id} label={r.name} help={`${r.when} ${r.behavior}`}>
              <LevelPicker level={r.level} label={r.name} />
            </Row>
          ))}
        </Card>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ playbooks */

function PlaybooksTab({ view }: { view: RunView }) {
  const autonomy = useAutonomy(view.stream);
  const books = autonomy.data?.playbooks ?? [];
  const used = new Set(view.steps.map((s) => (s.step.data?.playbook as { id?: string } | undefined)?.id).filter(Boolean));
  if (!autonomy.data) return <Card>{autonomy.error ? <Empty>Could not read GET /autonomy: {autonomy.error}</Empty> : <Empty>Reading the playbooks…</Empty>}</Card>;
  return (
    <>
      <ReadOnly>
        From <Source>GET /autonomy</Source> (playbooks). Argus picks one by the metric that moved and its direction; a playbook used in this run is marked.
      </ReadOnly>
      {books.map((b) => (
        <Card key={b.id} title={b.name} desc={<Source>{b.id}</Source>} action={used.has(b.id) ? <Badge tone="probe" dot>used in this run</Badge> : undefined}>
          <ol className="cs-steps">
            {b.steps.map((s) => (
              <li key={s.id}>
                <b>{s.label}</b>
                <span>{s.question}</span>
              </li>
            ))}
          </ol>
        </Card>
      ))}
    </>
  );
}

/* ------------------------------------------------------------------ thresholds */

function ThresholdsTab({ view }: { view: RunView }) {
  const health = useHealth(view.stream);
  const t = health.data?.thresholds;
  return (
    <>
      <Card title="Watcher defaults" desc={<>From <Source>GET /health</Source>. These thresholds use robust standard deviations (|z|) from the same hour of the last four weeks.</>}>
        {!t ? (
          <Empty>{health.error ? `Could not read GET /health: ${health.error}` : "Reading…"}</Empty>
        ) : (
          <>
            <Ruler wiggle={t.wiggle_z} pair={t.pair_z} alarm={t.alarm_z} />
            <Row label="Ignore below" help="A smaller move is noise: counted, never shown.">
              <span className="cs-num">|z| &lt; {t.wiggle_z}</span>
            </Row>
            <Row label="Open on two hours" help="Two of three hours above this line, in the same direction, open an anomaly.">
              <span className="cs-num">|z| &gt; {t.pair_z}</span>
            </Row>
            <Row label="Open at once" help="One hour above this line opens an anomaly and starts an investigation.">
              <span className="cs-num">|z| &gt; {t.alarm_z}</span>
            </Row>
          </>
        )}
      </Card>
      <Card title="Investigation rules" desc="Fixed limits from the investigation engine.">
        {CODE_RULES.map((r) => (
          <Row
            key={r.key}
            label={r.label}
            help={
              <>
                {r.help} <Source>{`${r.file.replace("src/argus/", "")} · ${r.constant}`}</Source>
              </>
            }
          >
            <span className="cs-num">{r.show}</span>
          </Row>
        ))}
      </Card>
      <Card title="Per-metric thresholds" action={<Preview />}>
        <Row label="Tune a metric's lines" help="The Watcher derives slice thresholds from its defaults. Per-metric overrides would go here.">
          <Switch on={false} label="Per-metric thresholds" />
        </Row>
      </Card>
    </>
  );
}

function Ruler({ wiggle, pair, alarm }: { wiggle: number; pair: number; alarm: number }) {
  const top = alarm * 1.4;
  const at = (v: number) => `${(v / top) * 100}%`;
  return (
    <div className="cs-ruler" aria-hidden="true">
      <div className="cs-ruler-track">
        <i className="z-calm" style={{ width: at(wiggle) }} />
        <i className="z-wiggle" style={{ left: at(wiggle), width: at(pair - wiggle) }} />
        <i className="z-pair" style={{ left: at(pair), width: at(alarm - pair) }} />
        <i className="z-alarm" style={{ left: at(alarm), right: 0 }} />
      </div>
      <div className="cs-ruler-marks">
        <span style={{ left: 0 }}>0</span>
        <span style={{ left: at(wiggle) }}>{wiggle}</span>
        <span style={{ left: at(pair) }}>{pair}</span>
        <span style={{ left: at(alarm) }}>{alarm}</span>
      </div>
      <div className="cs-ruler-words">
        <span style={{ left: at(wiggle / 2) }}>noise</span>
        <span style={{ left: at((wiggle + pair) / 2) }}>wiggle</span>
        <span style={{ left: at((pair + alarm) / 2) }}>two hours open</span>
        <span style={{ left: at(alarm + (top - alarm) / 2) }}>alarm</span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ budgets */

const CAP_WORD: Record<string, { label: string; show: (v: number) => string }> = {
  usd: { label: "Spend per run", show: (v) => `$${v.toFixed(2)}` },
  requests: { label: "Model requests per run", show: (v) => String(v) },
  tool_calls: { label: "Tool calls per run", show: (v) => String(v) },
  input_tokens: { label: "Input tokens per run", show: (v) => v.toLocaleString("en") },
  output_tokens: { label: "Output tokens per run", show: (v) => v.toLocaleString("en") },
  wall_seconds: { label: "Wall time per run", show: (v) => `${v} s` },
};

function BudgetsTab({ view }: { view: RunView }) {
  const agent = useAgent();
  const health = agent.health;
  const { incidents, failed } = useIncidents(view);
  const cost = incidentCost(incidents);
  const caps = Object.entries(health?.caps ?? {}).filter(([, v]) => typeof v === "number") as [string, number][];
  const models = health ? (Array.isArray(health.models) ? health.models.map((m) => [m, m] as const) : Object.entries(health.models)) : [];
  return (
    <>
      <Card title="Live agent caps" desc={<>Live from <Source>GET /agent/health</Source>. A run that reaches a cap stops and falls back to the deterministic investigator.</>} action={health ? <Badge tone={health.enabled ? "ok" : "muted"} dot>{health.enabled ? `agent ${health.mode}` : "agent off in this run"}</Badge> : undefined}>
        {!health ? (
          <Empty>Agent caps are unavailable for this run.</Empty>
        ) : (
          <>
            {!health.enabled && health.reason && <ReadOnly>{health.reason}</ReadOnly>}
            {caps.length === 0 && <Empty>This run reports no live agent caps.</Empty>}
            {caps.map(([k, v]) => (
              <Row key={k} label={CAP_WORD[k]?.label ?? humanize(k)}>
                <span className="cs-num">{CAP_WORD[k]?.show(v) ?? String(v)}</span>
              </Row>
            ))}
            {models.map(([k, m]) => (
              <Row key={k} label={`Model, ${humanize(k)}`}>
                <code className="cs-source">{m}</code>
              </Row>
            ))}
            <Row label="Spent by the live agent so far">
              <span className="cs-num">${health.usd.toFixed(3)}</span>
            </Row>
          </>
        )}
      </Card>
      <Card title="This run's investigations" desc="Totals from the incidents with recorded costs.">
        {failed ? <Empty>Could not load incident costs.</Empty> : <>
        <Row label="Incidents investigated">
          <span className="cs-num">{cost.n}</span>
        </Row>
        <Row label="Queries run">
          <span className="cs-num">{cost.queries}</span>
        </Row>
        <Row label="Query time">
          <span className="cs-num">{cost.seconds.toFixed(2)} s</span>
        </Row>
        <Row label="Model calls">
          <span className="cs-num">{cost.llm_calls}</span>
        </Row>
        <Row label="Model spend">
          <span className="cs-num">€{cost.eur.toFixed(2)}</span>
        </Row>
        </>}
      </Card>
      <Card title="Monthly budget" action={<Preview />}>
        <Row label="Stop the live agent at a monthly spend" help="A per-month ceiling across runs would go here; today only the per-run caps above apply.">
          <Switch on={false} label="Monthly budget" />
        </Row>
      </Card>
    </>
  );
}

/* ------------------------------------------------------------------ quiet hours */

function QuietTab() {
  return (
    <>
      <Card title="What never wakes anyone" desc="Argus logs these cases without escalating them.">
        <Row label="Planned changes" help="A change that follows a logged plan within its band is logged as a note, never paged (hold_alert).">
          <Badge tone="ok" dot>
            always on
          </Badge>
        </Row>
        <Row label="Late data" help="An hour with incomplete source data waits for the data instead of raising an alarm (defer_late_data).">
          <Badge tone="ok" dot>
            always on
          </Badge>
        </Row>
        <Row label="Symptoms of an open incident" help="A metric that moves because of an incident already filed adds to that incident, not a new page.">
          <Badge tone="ok" dot>
            always on
          </Badge>
        </Row>
      </Card>
      <Card title="Paging window" action={<Preview />}>
        <Row label="Quiet hours" help="Hold pages between these hours and deliver them in the morning report.">
          <Switch on={false} label="Quiet hours" />
        </Row>
        <Row label="Page anyway above" help="An incident costing more than this per hour would still page during quiet hours.">
          <Badge>Not set</Badge>
        </Row>
        <Row label="Weekends" help="Treat Saturday and Sunday as quiet all day.">
          <Switch on={false} label="Weekends quiet" />
        </Row>
      </Card>
    </>
  );
}

/* ------------------------------------------------------------------ channels */

const OUTSIDE: { id: string; name: string; help: string }[] = [
  { id: "slack", name: "Slack", help: "Post each incident with its verdict and receipts to a channel." },
  { id: "email", name: "Email", help: "Send the morning report and every incident by mail." },
  { id: "pagerduty", name: "PagerDuty", help: "Page the on-call person for an incident above the paging line." },
  { id: "webhook", name: "Webhook", help: "POST each incident as JSON to your own endpoint." },
];

function ChannelsTab() {
  return (
    <>
      <Card title="In the app" desc="Notifications delivered inside the workspace.">
        <Row label="Live notices" help="A notice when an incident is explained and when the run completes.">
          <Badge tone="ok" dot>
            on
          </Badge>
        </Row>
        <Row label="Morning report" help="The night in a few lines, each with its receipts.">
          <Btn onClick={() => go("report")}>Open</Btn>
        </Row>
        <Row label="Event stream" help={<>Every event as it happens, for your own tools: <Source>GET /events</Source> (server-sent events).</>}>
          <Badge tone="ok" dot>
            on
          </Badge>
        </Row>
      </Card>
      <Card title="Outside channels" action={<Preview />}>
        {OUTSIDE.map((c) => (
          <Row key={c.id} label={c.name} help={c.help}>
            <Switch on={false} label={c.name} />
          </Row>
        ))}
      </Card>
    </>
  );
}

/* ------------------------------------------------------------------ sources */

const CONNECTORS = ["Shopify", "Google Analytics 4", "Google Ads", "Meta Ads", "Stripe"];

function SourcesTab({ graph, view }: { graph: Graph | null; view: RunView }) {
  const health = useHealth(view.stream);
  const h = health.data;
  const tables = useMemo(() => {
    const byTable = new Map<string, string[]>();
    for (const n of graph?.nodes ?? []) if (n.table) byTable.set(n.table, [...(byTable.get(n.table) ?? []), n.id]);
    return [...byTable.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [graph]);
  const fresh = new Map((view.tick?.freshness ?? []).map((f) => [f.table, f]));
  return (
    <>
      <Card title="Connected" desc={<>Live from <Source>GET /health</Source>.</>}>
        {!h ? <Empty>{health.error ? "Could not read the current source." : "Reading the current source…"}</Empty> : <Row
          lead={<i className="cs-conn ok" aria-hidden="true" />}
          label={h.mode === "live" ? "Shop · live" : "Shop · sealed run"}
          help={h.mode === "live" ? "Generated shop data served by DuckDB." : "A sealed recording of Argus over generated shop data."}
        >
          <span className="cs-chips end">
            <Source>{h.source}</Source>
            <Badge tone="ok" dot>
              connected
            </Badge>
          </span>
        </Row>}
        {h?.world_start && (
          <Row label="History since" help="The first day of data the expectations learn from.">
            <span className="cs-num">{dayLabel(h.world_start)}</span>
          </Row>
        )}
        {view.tick && (
          <Row label="Latest hour scored">
            <span className="cs-num">
              {dayLabel(view.tick.hour)} {hhmm(view.tick.hour)}
            </span>
          </Row>
        )}
      </Card>
      <Card title="Tables" desc="The source tables metrics use, with coverage for the latest scored hour.">
        {tables.length === 0 && <Empty>No source tables available.</Empty>}
        {tables.map(([table, metrics]) => {
          const f = fresh.get(table);
          return (
            <Row
              key={table}
              label={<code className="cs-source plain">{table}</code>}
              help={
                <span className="cs-chips">
                  {metrics.map((m) => (
                    <Badge key={m}>{graph?.nodes.find((n) => n.id === m)?.label ?? m}</Badge>
                  ))}
                </span>
              }
            >
              {f ? (
                <Badge tone={f.status === "ok" ? "ok" : "watch"} dot>
                  {Math.round(f.completeness * 100)}% delivered
                </Badge>
              ) : (
                <Badge>no hour yet</Badge>
              )}
            </Row>
          );
        })}
      </Card>
      <Card title="Change logs" desc="What Argus reads to tell a planned change from a fault.">
        {(graph?.logs ?? []).map((l) => (
          <Row key={l.id} label={l.label} help={l.description}>
            <code className="cs-source">{l.id}</code>
          </Row>
        ))}
      </Card>
      <Card title="Connectors" desc="The Shop is connected through DuckDB." action={<Preview />}>
        {CONNECTORS.map((c) => (
          <Row key={c} lead={<i className="cs-conn" aria-hidden="true" />} label={c}>
            <Switch on={false} label={c} />
          </Row>
        ))}
      </Card>
    </>
  );
}
