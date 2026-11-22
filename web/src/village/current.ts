import { roleOfTool } from "../lib/agent";
import { monitoringText } from "../lib/format";
import type { MonitorState } from "../lib/monitor";
import type { RunView } from "../lib/store";
import type { Graph } from "../lib/types";
import { stepQuestion } from "../views/investigation";
import { nodeLabel } from "../views/model";
import type { AgentState } from "../fx/workspace/agent";
import { activityAvatarRole } from "./avatars/state";
import type { Beat, LogEntry } from "./beats";
import type { RoleView } from "./Overlay";
import { ROLES, type RoleId } from "./roles";
import type { MarketVerdict } from "./telemetry";
import { idleBubbles, villageAt } from "./timeline";

const IDLE = idleBubbles(ROLES);

export function currentVillage(view: RunView, monitor: MonitorState, agent: Pick<AgentState, "records">, graph: Graph | null) {
  const state = villageAt({ slots: [], total: 0, waiting: false }, 0, IDLE);
  const { avatars } = monitor;

  const add = (role: RoleId, entry: LogEntry) => state.roles[role].log.push(entry);
  for (const step of view.steps.slice(-120)) {
    add(roleOfTool(step.step.tool, step.step.kind), {
      key: `check:${step.seq}`,
      simTs: step.simTs,
      tool: "Metric check",
      title: stepQuestion(step.step),
      detail: monitoringText(step.step.result),
      hypothesis: step.step.hypothesis && monitoringText(step.step.hypothesis),
      outcome: "info",
      receipts: step.step.receipts,
      linkedReceipts: true,
    });
  }
  for (const record of agent.records.slice(-120)) {
    const detail = record.observation?.summary || record.text;
    if (!detail || record.kind === "watch") continue;
    add(activityAvatarRole(record), {
      key: `activity:${record.seq}`,
      simTs: record.sim_ts,
      tool: record.tool ? "Agent check" : "Agent activity",
      title: monitoringText(detail),
      detail: null,
      hypothesis: null,
      outcome: "info",
      receipts: [],
      agentReceipts: record.receipt_links.length ? record.receipt_links : record.observation?.receipt_refs,
    });
  }

  const views: RoleView[] = ROLES.map(({ id }) => {
    const role = state.roles[id];
    const cue = avatars[id];
    role.log.sort((a, b) => a.simTs.localeCompare(b.simTs));
    role.beats = role.log.length;
    if (cue?.status === "waiting" || cue?.status === "working") {
      role.status = cue.status;
      role.bubble = cue.text ?? monitor.activity;
    } else if (id === "watcher" && monitor.time) {
      role.bubble = "Watching the shop";
    } else if (id === "detective" && monitor.openIncidents.length) {
      role.bubble = "No check in progress";
    }
    return {
      role: id,
      kind: role.status === "waiting" ? "need" : role.status === "working" ? "working" : null,
      line: role.status !== "idle" ? role.bubble : null,
      since: null,
    };
  });

  const pending = monitor.avatars.operator?.status === "waiting" ? monitor.pending : undefined;
  const gate: Beat["gate"] = pending
    ? { actionId: pending.id, action: monitoringText(pending.action), incidentId: pending.incident_ref, proposal: pending }
    : null;
  const role = monitor.activityRole;
  const run = monitor.runningInvestigation;
  const caseId = pending?.incident_ref ?? run?.incident_id ?? run?.anomaly_id ?? monitor.investigating?.id ?? null;
  if (role && monitor.time) {
    state.beat = {
      key: String(avatars[role]?.key ?? role),
      role,
      kind: gate ? "proposal" : "check",
      caseId,
      simTs: monitor.time,
      doing: state.roles[role].bubble,
      done: "",
      outcome: gate ? "wait" : "info",
      log: [],
      weight: 1,
      gate,
    };
  }
  state.gate = gate;
  state.simTs = monitor.time;
  state.focus = role;
  state.finished = false;

  const caseNode = monitor.investigating?.node
    ?? view.incidents[caseId ?? ""]?.root_node
    ?? view.anomalies.find((a) => a.id === caseId)?.node;
  const caseLabel = caseId ? (caseNode ? nodeLabel(graph, caseNode) : "Incident") : null;
  const watch = (view.tick?.scored_nodes ?? []).slice(0, 6).map((node) => ({
    label: nodeLabel(graph, node),
    values: view.zHistory[node] ?? [],
  }));
  const control = view.steps.findLast((step) => {
    const data = step.step.data?.market_control;
    return data && typeof data === "object" && "verdict" in data;
  })?.step.data.market_control as { verdict: string } | undefined;
  const market: MarketVerdict | null = control
    ? (control.verdict === "us" || control.verdict === "market" ? control.verdict : "inconclusive")
    : null;

  return { state, avatars, views, caseLabel, telemetry: { watch, market } };
}
