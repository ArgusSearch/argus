// The agent surfaces' pure parts: how a proposal's state reads and how far along it is, which incidents count as
// this week's tasks once the agent proposes actions, and the client's settle rule and idempotency keys.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { stageOf } from "../../../src/fx/workspace/ActionCard";
import { proposalFor } from "../../../src/fx/workspace/agent";
import { tasks } from "../../../src/fx/workspace/health";
import { idempotencyKey, settling, type ProposalState, type ProposalView } from "../../../src/lib/agent";
import type { Incident } from "../../../src/lib/types";

const STATES: ProposalState[] = ["AWAIT_OPERATOR", "DENIED", "EXPIRED", "APPLYING", "APPLIED", "VERIFYING", "VERIFIED", "NO_EFFECT", "INCONCLUSIVE"];

function proposal(id: string, incident: string, state: ProposalState): ProposalView {
  return {
    id,
    digest: "sha256:x",
    state,
    run_id: "run_0001",
    incident_ref: incident,
    playbook_id: "rollback_pacer",
    action: "Roll the pacer back.",
    scope: { country: ["DE"] },
    effective_at: "2026-11-20T03:00:00",
    expires_at: "2026-11-20T05:00:00",
    success_rule: { node: "pacing_ratio", scope: { country: ["DE"] }, rule: "in band for 3 hours", hours: 3, comparator: "untreated_twin" },
    evidence_refs: [],
    decision: null,
    effect: null,
  };
}

describe("a proposal's stage", () => {
  it("reads every state in words and only counts the stages it reached", () => {
    for (const s of STATES) {
      const st = stageOf(s);
      expect(st.word.length, s).toBeGreaterThan(0);
      expect(st.reached).toBeGreaterThanOrEqual(0);
      expect(st.reached).toBeLessThanOrEqual(3);
    }
    expect(stageOf("AWAIT_OPERATOR").reached).toBe(0);
    expect(stageOf("APPLYING").reached).toBe(1);
    expect(stageOf("VERIFIED")).toMatchObject({ reached: 3, tone: "ok" });
    expect(stageOf("NO_EFFECT").tone).toBe("alarm");
  });

  it("is polled only while it is still moving", () => {
    expect(STATES.filter(settling)).toEqual(["APPLYING", "APPLIED", "VERIFYING"]);
  });
});

describe("tasks and proposals", () => {
  const s4 = (): Incident[] =>
    JSON.parse(readFileSync(fileURLToPath(new URL("../../../../fixtures/s4/incidents.json", import.meta.url)), "utf8")) as Incident[];

  it("lists an incident the agent proposed an action for, even without a suggested action in its findings", () => {
    const [inc] = s4();
    const bare: Incident = { ...inc, findings: { ...inc.findings, suggested_action: null } };
    expect(tasks([bare], null).map((t) => t.id)).toEqual([]);
    const listed = tasks([bare], null, new Set([inc.id]));
    expect(listed.map((t) => t.id)).toEqual([inc.id]);
    expect(listed[0].action).toBe("");
  });

  it("picks the newest proposal of an incident", () => {
    const state = { proposals: [proposal("act_0001", "INC-0001", "DENIED"), proposal("act_0002", "INC-0001", "AWAIT_OPERATOR")] };
    expect(proposalFor(state as never, "INC-0001")?.id).toBe("act_0002");
    expect(proposalFor(state as never, "INC-0009")).toBeNull();
  });

  it("sends a fresh idempotency key with every decision", () => {
    expect(idempotencyKey()).not.toBe(idempotencyKey());
  });
});

describe("the agent presentation's wire shapes", () => {
  it("reads a recorded receipt proof as one receipt, and a live C4 receipt as it is", async () => {
    const { normalizeReceipt } = await import("../../../src/lib/agent");
    const receipt = { id: "r184", sql: "SELECT 1", as_of: "2026-11-20T02:00:00", result_hash: "sha256:ab", rows: 1, ms: 3.1, purpose: "pacing" };
    const proof = normalizeReceipt({ receipt, columns: ["a", "b"], rows: [[1, 2]], verified_at_capture: true });
    expect(proof).toMatchObject({ id: "r184", rows: 1, columns: ["a", "b"], captured_rows: [[1, 2]], verified_at_capture: true });
    expect(normalizeReceipt(receipt)).toEqual(receipt);
  });

  it("pins agent and evidence routes to the presentation's run while one plays", async () => {
    const { withRun, demoRunId } = await import("../../../src/lib/agentDemo");
    expect(demoRunId()).toBeNull();
    expect(withRun("/agent/actions")).toBe("/agent/actions");
    expect(withRun("/agent/activity?since=3")).toBe("/agent/activity?since=3");
  });
});

describe("who did a step", () => {
  it("takes the record's own role, else maps kind and tool like the village does", async () => {
    const { roleOf, AGENT_ROLES } = await import("../../../src/lib/agent");
    const rec = (over: Record<string, unknown>) => ({ seq: 1, run_id: "r", sim_ts: "2026-11-20T02:00:00", kind: "tool_call", stage: "ACT", actor: "model", text: "", anomaly_id: null, incident_id: null, action_id: null, tool: null, args: null, observation: null, receipt_links: [], model: null, input_tokens: null, output_tokens: null, usd: null, gate_action: null, ...over }) as never;
    expect(roleOf(rec({ role: "market" }))).toBe("market");
    expect(roleOf(rec({ kind: "watch" }))).toBe("watcher");
    expect(roleOf(rec({ kind: "gate" }))).toBe("skeptic");
    expect(roleOf(rec({ kind: "chat_answer" }))).toBe("narrator");
    expect(roleOf(rec({ kind: "action_decided" }))).toBe("operator");
    expect(roleOf(rec({ kind: "tool_call", tool: "holdout_check" }))).toBe("skeptic");
    expect(roleOf(rec({ kind: "tool_result", tool: "check_identities" }))).toBe("cartographer");
    expect(roleOf(rec({ kind: "tool_result", tool: "market_control" }))).toBe("market");
    expect(roleOf(rec({ kind: "thought", tool: null }))).toBe("detective");
    expect(AGENT_ROLES).toHaveLength(7);
  });
});
