import { autonomyCounts } from "../views/autonomy";
import { stepQuestion } from "../views/investigation";
import { investigations, nodeLabel } from "../views/model";
import { activityAvatarRole, type AvatarCues } from "../village/avatars/state";
import { ROLE_IDS, type RoleId } from "../village/roles";
import { roleOfTool, type ActivityRecord, type ProposalView, type RunSummary } from "./agent";
import type { ConnectionState } from "./api";
import { dayLabel, hhmm, monitoringText } from "./format";
import type { RunView } from "./store";
import type { Graph, Health } from "./types";

interface AgentSnapshot {
  records: ActivityRecord[];
  proposals: ProposalView[];
  runs: RunSummary[];
  avatars: AvatarCues;
}

const RUN_WORK: Record<RunSummary["kind"], [RoleId, string]> = {
  investigate: ["detective", "Investigating a metric change"],
  ask: ["narrator", "Answering a question"],
  morning: ["narrator", "Preparing the shop report"],
  verify_effect: ["operator", "Checking the effect of an action"],
};

export function selectMonitor(view: RunView, graph: Graph | null, health: Health | null, connection: ConnectionState, agent: AgentSnapshot) {
  const time = view.simTs;
  const incidents = Object.values(view.incidents).sort((a, b) => b.firstSeq - a.firstSeq);
  const openIncidents = incidents.filter((incident) => incident.state !== "resolved");
  const cases = investigations(view);
  const latest = view.anomalies.at(-1);
  const finished = health?.stream === view.stream && health.run.finished && view.lastSeq >= health.last_seq;
  const investigating = connection === "open" && !finished && latest?.detected_at === time
    && !view.steps.some((step) => step.anomalyId === latest.id && step.step.kind === "verdict")
    ? latest
    : null;
  const activeStep = investigating ? view.steps.findLast((step) => step.anomalyId === investigating.id) : undefined;
  const records = agent.records;
  const ended = new Set(records.filter((record) => record.kind === "run_finished").map((record) => record.run_id));
  const runningRuns = connection === "open" ? agent.runs.filter((run) => run.status === "running" && !ended.has(run.run_id)) : [];
  const runningRun = runningRuns.at(-1);
  const runningInvestigation = runningRuns.findLast((run) => run.kind === "investigate");
  const pending = agent.proposals.findLast((proposal) => proposal.state === "AWAIT_OPERATOR");
  const avatars: AvatarCues = {};
  let investigationRole: RoleId | null = null;
  if (time && connection === "open") {
    for (const run of runningRuns) {
      const record = records.findLast((item) => item.run_id === run.run_id);
      const [fallbackRole, fallbackText] = RUN_WORK[run.kind];
      const role = record ? activityAvatarRole(record) : fallbackRole;
      if (run === runningInvestigation) investigationRole = role;
      const cue = agent.avatars[role];
      const text = record?.observation?.summary || record?.text;
      avatars[role] = {
        status: "working",
        key: record?.seq ?? run.run_id,
        text: text?.trim() ? monitoringText(text) : fallbackText,
        runId: run.run_id,
        actionId: cue?.runId === run.run_id ? cue.actionId : undefined,
      };
    }
    if (investigating && !runningInvestigation) {
      const role = activeStep ? roleOfTool(activeStep.step.tool, activeStep.step.kind) : "detective";
      investigationRole = role;
      avatars[role] = {
        status: "working",
        key: activeStep?.seq ?? investigating.id,
        text: activeStep ? stepQuestion(activeStep.step) : `Investigating ${nodeLabel(graph, investigating.node)}`,
      };
    }
    const operator = agent.avatars.operator;
    if (pending) {
      avatars.operator = { status: "waiting", key: pending.id, text: monitoringText(pending.action), actionId: pending.id };
    } else if (operator?.status === "working" && agent.proposals.some((p) =>
      p.id === operator.actionId && (p.state === "APPLYING" || p.state === "VERIFYING"))) {
      avatars.operator = { ...operator, text: operator.text && monitoringText(operator.text) };
    }
  }
  const activity = pending && avatars.operator?.status === "waiting"
    ? "Waiting for your approval"
    : runningInvestigation || investigating
      ? "Investigating a metric change"
      : runningRun
        ? RUN_WORK[runningRun.kind][1]
        : avatars.operator?.status === "working"
          ? "Checking an action"
          : "Watching the shop";
  const activityRole = avatars.operator?.status === "waiting" ? "operator"
    : investigationRole ?? (Object.keys(avatars) as RoleId[]).find((role) => avatars[role]?.status === "working") ?? null;
  for (const role of ROLE_IDS) {
    avatars[role] ??= { status: role === "watcher" ? "idle" : "sleeping" };
  }

  return {
    time,
    timeLabel: time ? `${dayLabel(time)} · ${hhmm(time)}` : null,
    connection,
    incidents,
    openIncidents,
    cases,
    investigating,
    runningRuns,
    runningInvestigation,
    runningRun,
    activeInvestigation: Boolean(investigating || runningInvestigation),
    autonomy: autonomyCounts(view, cases.length),
    avatars,
    pending,
    activity,
    activityRole,
  };
}

export type MonitorState = ReturnType<typeof selectMonitor>;
