import { useMemo, useRef, useState } from "react";
import { dayLabel, hhmm, humanize } from "../lib/format";
import { staticReplay } from "../lib/deployment";
import { AGENT_ROLES } from "../lib/agent";
import type { RunView } from "../lib/store";
import type { Graph } from "../lib/types";
import { go } from "../fx/nav";
import { useAgent } from "../fx/workspace/agent";
import { useIncidents } from "../fx/workspace/ui";
import { ROLE_TEXT } from "../fx/workspace/AvatarSlot";
import { ConnectionsTab } from "./connections/ConnectionsTab";
import { CODE_RULES } from "./constants";
import { useAutonomy, useHealth } from "./data";
import { EditorSection, type Editor } from "./editor";
import { useText } from "./language";
import { loadSettings, useOperatorSettings, type Lines, type Settings } from "./operator";
import { AccountTab, AiTab, AppearanceTab, DataTab, NotificationsTab, ShopTab } from "./SettingsForms";
import { incidentCost, rulesByAgent } from "./model";
import { SETTINGS_TABS, type SettingsTab } from "./route";
import { Badge, Btn, Card, Empty, LevelPicker, PageHead, Portrait, NumberInput, Row, Source, SubNav, Switch, type SubNavGroup } from "./ui";

const TITLES: Record<SettingsTab, { title: string; lead: string }> = {
  autonomy: { title: "Autonomy", lead: "What each agent may decide alone and where it asks you first. Argus watches and investigates on its own. Applying a fix requires approval." },
  playbooks: { title: "Playbooks", lead: "The named investigation plans Argus picks from, step by step, depending on which metric moved and which way." },
  thresholds: { title: "Thresholds", lead: "The lines the Watcher scores against and the rules an investigation must meet before it may call a cause." },
  budgets: { title: "Budgets", lead: "What one live agent run may spend, and what this run's investigations cost." },
  "quiet-hours": { title: "Quiet hours", lead: "When Argus may page a person, and what never pages anyone." },
  channels: { title: "Channels", lead: "Where Argus tells you about an incident." },
  account: { title: "Account", lead: "The operator profile shown in Argus." },
  ai: { title: "AI model", lead: "Choose the provider and model for the live agent." },
  appearance: { title: "Appearance", lead: "Choose the workspace theme and language." },
  notifications: { title: "Notifications", lead: "Set and test the destinations for incident notices." },
  connections: { title: "Connections", lead: "Bring provider metrics into Argus." },
  shop: { title: "Shop connection", lead: "Register and test a Shop endpoint." },
  data: { title: "Export and reset", lead: "Download a copy of your settings or restore the defaults." },
  sources: { title: "Data sources", lead: "Where Argus reads the shop's numbers and change logs from, and how complete the latest hour is." },
};

const GROUPS: SubNavGroup<SettingsTab>[] = [
  { label: "Agents", items: [{ id: "autonomy", label: "Autonomy" }, { id: "playbooks", label: "Playbooks" }, { id: "ai", label: "AI model" }] },
  { label: "Detection", items: [{ id: "thresholds", label: "Thresholds" }, { id: "budgets", label: "Budgets" }] },
  { label: "Notifications", items: [{ id: "quiet-hours", label: "Quiet hours" }, { id: "channels", label: "Channels" }, { id: "notifications", label: "Notifications" }] },
  { label: "Data", items: [{ id: "sources", label: "Data sources" }, { id: "shop", label: "Shop connection" }, { id: "connections", label: "Connections" }, { id: "data", label: "Export and reset" }] },
  { label: "Workspace", items: [{ id: "account", label: "Account" }, { id: "appearance", label: "Appearance" }] },
];

export function SettingsPage({ graph, view }: { graph: Graph | null; view: RunView }) {
  const content = useRef<HTMLDivElement>(null);
  const [tab, setSettingsTab] = useState<SettingsTab>(() => {
    const requested = new URLSearchParams(window.location.search).get("tab");
    return SETTINGS_TABS.find((tab) => tab === requested) ?? "autonomy";
  });
  const t = TITLES[tab];
  const tr = useText();
  const { snapshot, error } = useOperatorSettings();
  const pickTab = (next: SettingsTab) => {
    setSettingsTab(next);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    window.history.replaceState(window.history.state, "", url);
    content.current?.scrollIntoView({ block: "start" });
  };
  const groups = GROUPS.map((group) => ({ label: tr(group.label), items: group.items.map((item) => ({ ...item, label: tr(item.label) })) }));
  return (
    <div className="cs-split cs-settings">
      <aside className="cs-list">
        <span className="cs-side-title">{tr("Settings")}</span>
        <SubNav groups={groups} current={tab} onPick={pickTab} label={tr("Settings sections")} />
        <Btn onClick={() => go("calendar")}>{tr("Open calendar")}</Btn>
      </aside>
      <div className="cs-main" ref={content}>
        <PageHead title={tr(t.title)} lead={tr(t.lead)} />
        {tab === "connections" && <ConnectionsTab live={view.mode === "live"} />}
        {tab !== "connections" && !snapshot && <Card><Empty>{tr(error || "Loading settings…")}</Empty>
          {error && !staticReplay && <Btn onClick={() => void loadSettings()}>{tr("Try again")}</Btn>}
        </Card>}
        {tab !== "connections" && snapshot && <>
          {snapshot.simulator && <p className="cs-note">{tr("Settings are saved for this simulator session.")}</p>}
          {tab === "autonomy" && <EditorSection area="autonomy">{(editor) => <AutonomyTab view={view} editor={editor} />}</EditorSection>}
          {tab === "playbooks" && <EditorSection area="playbooks">{(editor) => <PlaybooksTab view={view} editor={editor} />}</EditorSection>}
          {tab === "thresholds" && <EditorSection area="thresholds">{(editor) => <ThresholdsTab graph={graph} editor={editor} />}</EditorSection>}
          {tab === "budgets" && <EditorSection area="budgets">{(editor) => <BudgetsTab view={view} editor={editor} />}</EditorSection>}
          {tab === "quiet-hours" && <EditorSection area="quiet_hours">{(editor) => <QuietTab editor={editor} />}</EditorSection>}
          {tab === "channels" && <EditorSection area="channels">{(editor) => <ChannelsTab editor={editor} />}</EditorSection>}
          {tab === "sources" && <SourcesTab graph={graph} view={view} />}
          {tab === "shop" && <ShopTab />}
          {tab === "account" && <AccountTab />}
          {tab === "ai" && <AiTab />}
          {tab === "notifications" && <NotificationsTab />}
          {tab === "appearance" && <AppearanceTab />}
          {tab === "data" && <DataTab />}
        </>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ autonomy */

function AutonomyTab({ view, editor }: { view: RunView; editor: Editor<Settings["autonomy"]> }) {
  const tr = useText();
  const autonomy = useAutonomy(view.stream);
  const ruled = useMemo(() => (autonomy.data ? rulesByAgent(autonomy.data, AGENT_ROLES) : null), [autonomy.data]);
  if (!ruled) return <Card>{autonomy.error ? <Empty>Could not read GET /autonomy: {autonomy.error}</Empty> : <Empty>Reading the limits…</Empty>}</Card>;
  const probation = autonomy.data?.probation ?? [];
  return (
    <>
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
              <Row key={r.id} label={r.name} help={`${tr(r.when)} ${tr(r.behavior)}`}>
                <LevelPicker level={editor.value[r.id] ?? r.level} allowed={r.level} onChange={(level) => editor.set(r.id, level)} label={`${ROLE_TEXT[role].name}: ${r.name}`} />
              </Row>
            ))}
            {role === "cartographer" && (
              <Row label="On probation now" help="Graph placements waiting for stronger evidence or your decision before promotion.">
                <span className="cs-chips end">
                  {probation.length === 0 ? <Badge tone="ok">{tr("none")}</Badge> : probation.map((p) => <Badge key={p.id} tone="watch">{p.id}</Badge>)}
                </span>
              </Row>
            )}
          </Card>
        );
      })}
      {ruled.other.length > 0 && (
        <Card title="Other rules">
          {ruled.other.map((r) => (
            <Row key={r.id} label={r.name} help={`${tr(r.when)} ${tr(r.behavior)}`}>
              <LevelPicker level={editor.value[r.id] ?? r.level} allowed={r.level} onChange={(level) => editor.set(r.id, level)} label={r.name} />
            </Row>
          ))}
        </Card>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ playbooks */

function PlaybooksTab({ view, editor }: { view: RunView; editor: Editor<Settings["playbooks"]> }) {
  const autonomy = useAutonomy(view.stream);
  const books = autonomy.data?.playbooks ?? [];
  const used = new Set(view.steps.map((s) => (s.step.data?.playbook as { id?: string } | undefined)?.id).filter(Boolean));
  if (!autonomy.data) return <Card>{autonomy.error ? <Empty>Could not read GET /autonomy: {autonomy.error}</Empty> : <Empty>Reading the playbooks…</Empty>}</Card>;
  return (
    <>
      {books.map((b) => (
        <Card key={b.id} title={b.name} desc={<Source>{b.id}</Source>} action={used.has(b.id) ? <Badge tone="probe" dot>used in this run</Badge> : undefined}>
          <Row label={b.name} help="Turn off to use the general investigation for these changes.">
            <Switch label={b.name} on={!editor.value.disabled.includes(b.id)} onChange={(on) => editor.set(
              "disabled", on ? editor.value.disabled.filter((id) => id !== b.id) : [...editor.value.disabled, b.id],
            )} />
          </Row>
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

const WATCH_FIELDS = [
  { key: "wiggle_z", label: "Ignore below", help: "Smaller moves count as noise." },
  { key: "pair_z", label: "Open on two hours", help: "Two of three hours above this line in the same direction open an anomaly." },
  { key: "alarm_z", label: "Open at once", help: "One hour above this line opens an anomaly and starts an investigation." },
] as const;

const INVESTIGATION_FIELDS = [
  ["supported", "supported", 0.01],
  ["stop", "stop", 0.01],
  ["plan_band", "plan-band", 0.01],
  ["plan_min", "plan-min", 0.01],
  ["freshness", "late-data", 0.001],
  ["calm_hours", "calm", 1],
  ["checks", "checks", 1],
] as const;

function ThresholdsTab({ graph, editor }: { graph: Graph | null; editor: Editor<Settings["thresholds"]> }) {
  const tr = useText();
  const [metric, pickMetric] = useState("");
  const t = editor.value;
  const defaults: Lines = { wiggle_z: t.wiggle_z, pair_z: t.pair_z, alarm_z: t.alarm_z };
  const chosen = t.per_metric[metric];
  return (
    <>
      <Card title="Watcher defaults" desc="Robust standard deviations (|z|) from the same hour of the last four weeks.">
        {0 < t.wiggle_z && t.wiggle_z < t.pair_z && t.pair_z < t.alarm_z && <Ruler wiggle={t.wiggle_z} pair={t.pair_z} alarm={t.alarm_z} />}
        {WATCH_FIELDS.map(({ key, label, help }) => (
          <Row key={key} label={label} help={help}>
            <NumberInput label={label} value={t[key]} step={0.1} min={0.1} max={40} onChange={(value) => editor.change(key, value)} />
          </Row>
        ))}
      </Card>
      <Card title="Investigation rules" desc="Enter shares as decimals, for example 0.8 for 80%.">
        {INVESTIGATION_FIELDS.map(([field, ruleKey, step]) => {
          const rule = CODE_RULES.find(({ key }) => key === ruleKey)!;
          const label = field === "freshness" ? "Minimum source completeness" : rule.label;
          return <Row key={field} label={label} help={field === "freshness" ? "Hold scoring when a source delivers less than this share." : rule.help}>
            <NumberInput label={label} value={t[field]} step={step} onChange={(value) => editor.change(field, value)} />
          </Row>;
        })}
      </Card>
      <Card title="Per-metric thresholds" desc="Override the Watcher defaults for a metric.">
        <Row label="Metric">
          <select className="cs-input" name="metric" aria-label={tr("Metric")} value={metric} onChange={(event) => pickMetric(event.target.value)}>
            <option value="">{tr("Select a metric")}</option>
            {graph?.nodes.filter((node) => node.north_star).map((node) => <option key={node.id} value={node.id}>{node.label}</option>)}
          </select>
        </Row>
        {metric && <Row label="Use an override"><Switch on={Boolean(chosen)} label="Use an override" onChange={(on) => {
          const next = { ...t.per_metric };
          if (on) next[metric] = defaults;
          else delete next[metric];
          editor.set("per_metric", next);
        }} /></Row>}
        {chosen && WATCH_FIELDS.map(({ key, label }) => (
          <Row key={key} label={label}>
            <NumberInput label={`Metric ${label.toLowerCase()}`} value={chosen[key]} step={0.1} min={0.1} max={40}
              onChange={(value) => editor.change("per_metric", { ...t.per_metric, [metric]: { ...chosen, [key]: value } })} />
          </Row>
        ))}
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

const CAP_FIELDS = [
  ["usd", "Spend per run (USD)", 0.01],
  ["requests", "Model requests per run", 1],
  ["tool_calls", "Tool calls per run", 1],
  ["input_tokens", "Input tokens per run", 1],
  ["output_tokens", "Output tokens per run", 1],
  ["wall_seconds", "Wall time per run (seconds)", 1],
] as const;

function BudgetsTab({ view, editor }: { view: RunView; editor: Editor<Settings["budgets"]> }) {
  const { health } = useAgent();
  const { incidents, failed } = useIncidents(view);
  const cost = incidentCost(incidents);
  const models = health ? (Array.isArray(health.models) ? health.models.map((model) => [model, model]) : Object.entries(health.models)) : [];
  return (
    <>
      <Card title="Live agent caps" desc="The deterministic investigator takes over when a model run reaches a cap." action={health ? <Badge tone={health.enabled ? "ok" : "muted"} dot>{health.enabled ? `agent ${health.mode}` : "agent off in this run"}</Badge> : undefined}>
        {CAP_FIELDS.map(([key, label, step]) => (
          <Row key={key} label={label}><NumberInput label={label} value={editor.value[key]} step={step}
            onChange={(value) => editor.change(key, value)} /></Row>
        ))}
        {models.map(([key, model]) => <Row key={key} label={`Model, ${humanize(key ?? "")}`}><Source>{model}</Source></Row>)}
        {health && <Row label="Spent by the live agent so far"><span className="cs-num">${health.usd.toFixed(3)}</span></Row>}
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
      <Card title="Monthly budget">
        <Row label="Monthly model spend (USD)" help="Leave blank for no monthly ceiling. The ceiling resets at the start of each UTC month.">
          <NumberInput label="Monthly model spend (USD)" step={0.01} value={editor.value.monthly_usd}
            onChange={(value) => editor.set("monthly_usd", value)} />
        </Row>
      </Card>
    </>
  );
}

/* ------------------------------------------------------------------ quiet hours */

function QuietTab({ editor }: { editor: Editor<Settings["quiet_hours"]> }) {
  const q = editor.value;
  const tr = useText();
  return (
    <>
      <Card title="What never wakes anyone" desc="Planned changes, late data and covered symptoms follow the autonomy policy.">
        <Row label="Planned changes" help="A change within its expected band can be logged as a note."><Badge>hold_alert</Badge></Row>
        <Row label="Late data" help="Incomplete source data can wait before scoring."><Badge>defer_late_data</Badge></Row>
        <Row label="Symptoms of an open incident" help="A covered symptom can be added to the existing incident."><Badge>hold_alert</Badge></Row>
      </Card>
      <Card title="Paging window">
        <Row label="Quiet hours" help="Hold outgoing notices until the quiet window ends."><Switch on={q.enabled} label="Quiet hours" onChange={(on) => editor.set("enabled", on)} /></Row>
        {(["start", "end"] as const).map((field) => {
          const label = field === "start" ? "Start" : "End";
          return <Row key={field} label={label}><input className="cs-input" type="time" name={field} aria-label={tr(label)}
            value={q[field]} onChange={(event) => editor.set(field, event.target.value)} /></Row>;
        })}
        <Row label="Timezone"><input className="cs-input" name="timezone" aria-label={tr("Timezone")} value={q.timezone} maxLength={96}
          onChange={(event) => editor.set("timezone", event.target.value)} /></Row>
        <Row label="Page anyway above" help="Estimated impact in EUR per hour. Leave blank to hold all notices.">
          <NumberInput label="Page anyway above" step={0.01} value={q.bypass_eur} onChange={(value) => editor.set("bypass_eur", value)} />
        </Row>
        <Row label="Weekends" help="Treat Saturday and Sunday as quiet all day."><Switch on={q.weekends} label="Weekends" onChange={(on) => editor.set("weekends", on)} /></Row>
      </Card>
    </>
  );
}

/* ------------------------------------------------------------------ channels */

const OUTSIDE: { id: Exclude<keyof Settings["channels"], "in_app">; name: string; help: string }[] = [
  { id: "slack", name: "Slack", help: "Post each incident with its verdict and receipts to a channel." },
  { id: "email", name: "Email", help: "Send incident notices by email." },
  { id: "pagerduty", name: "PagerDuty", help: "Send an incident notice to your configured PagerDuty webhook." },
  { id: "webhook", name: "Webhook", help: "POST each incident as JSON to your own endpoint." },
];

function ChannelsTab({ editor }: { editor: Editor<Settings["channels"]> }) {
  const tr = useText();
  return (
    <>
      <Card title="In the app" desc="Notifications delivered inside the workspace.">
        <Row label="Live notices" help="A notice when an incident is explained and when the run completes.">
          <Switch on={editor.value.in_app} label="Live notices" onChange={(on) => editor.set("in_app", on)} />
        </Row>
        <Row label="Morning report" help="The night in a few lines, each with its receipts.">
          <Btn onClick={() => go("report")}>{tr("Open")}</Btn>
        </Row>
        <Row label="Event stream" help={<>Every event as it happens, for your own tools: <Source>GET /events</Source> (server-sent events).</>}>
          <Badge tone="ok" dot>
            on
          </Badge>
        </Row>
      </Card>
      <Card title="Outside channels" desc="Set delivery destinations under Notifications.">
        {OUTSIDE.map((c) => (
          <Row key={c.id} label={c.name} help={c.help}>
            <Switch on={editor.value[c.id]} label={c.name} onChange={(on) => editor.set(c.id, on)} />
          </Row>
        ))}
      </Card>
    </>
  );
}

/* ------------------------------------------------------------------ sources */

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
      <ShopTab />
    </>
  );
}
