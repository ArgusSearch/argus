import { describe, expect, it } from "vitest";
import s4 from "../../../../fixtures/agent/v1/s4/activity.jsonl?raw";
import type { ActivityRecord, ProposalView, ReceiptLink, RunSummary } from "../../lib/agent";
import { lineageOf, liveFixThreads, matchesThread, recordedSpan, threadForIncident, uniqueReceipts } from "./model";

const activity: ActivityRecord[] = s4.trim().split("\n").map((line) => JSON.parse(line));
const summary: RunSummary = {
  run_id: "run_0001", kind: "investigate", mode: "replay", sim_ts: activity[0].sim_ts,
  anomaly_id: null, incident_id: "INC-0001", status: "done", stop_reason: null,
  llm_calls: 4, tool_calls: 3, input_tokens: 0, output_tokens: 0, usd: 0.0459,
  gate: null, fallback: null,
};
const proposal = {
  id: "act_0001", state: "AWAIT_OPERATOR", run_id: "run_0001", incident_ref: "INC-0001",
} as ProposalView;

describe("Live Fix run shelf and lineage", () => {
  it("keeps the checkpoint on its originating run, with the operator observed but idle", () => {
    const threads = liveFixThreads(activity.slice(0, 16), [summary], [proposal], "awaiting_approval");
    expect(threads).toHaveLength(1);
    const thread = threadForIncident(threads, "INC-0001")!;
    expect(thread.state).toBe("awaiting approval");
    expect(thread.proposals).toEqual([proposal]);
    expect(threadForIncident(threads, "INC-0002")).toBeUndefined();
    expect(matchesThread(thread, "skeptic inc-0001")).toBe(true);
    expect(matchesThread(thread, "narrator")).toBe(false);
    expect(lineageOf(thread).map((entry) => [entry.role, entry.working, entry.seconds])).toEqual([
      ["detective", false, null], ["skeptic", false, null], ["operator", false, null],
    ]);
  });

  it("includes summary-only runs and never treats a missing live summary as proof of activity", () => {
    const threads = liveFixThreads(activity.slice(0, 6), [{ ...summary, run_id: "older" }], [], null);
    expect(threads.find((thread) => thread.id === "older")).toMatchObject({ state: "settled", group: null });
    expect(threads.find((thread) => thread.id === "run_0001")?.state).toBe("unknown");
  });

  it("shows only the current recorded role as working and stops on pause", () => {
    const partial = activity.slice(0, 6);
    const working = liveFixThreads(partial, [], [], "playing")[0];
    expect(working.state).toBe("working");
    expect(lineageOf(working).filter((entry) => entry.working).map((entry) => entry.role)).toEqual(["skeptic"]);
    const paused = liveFixThreads(partial, [], [], "paused")[0];
    expect(paused.state).toBe("paused");
    expect(lineageOf(paused).some((entry) => entry.working)).toBe(false);
  });

  it("keeps the originating investigation selected when a scoped Ask run starts", () => {
    const ask = { ...summary, run_id: "asking", kind: "ask", status: "running", sim_ts: "2026-11-20T03:00:00" } as const;
    const threads = liveFixThreads(activity.slice(0, 15), [summary, ask], [], null);
    expect(threads[0].id).toBe("asking");
    expect(threadForIncident(threads, "INC-0001")?.id).toBe(summary.run_id);
  });
});

describe("Live Fix evidence metadata", () => {
  it("includes only positive recorded spans from valid timestamps", () => {
    expect(recordedSpan("2026-11-20T02:00:00", "2026-11-20T02:00:18Z")).toBe(18);
    expect(recordedSpan("2026-11-20T02:00:00", "2026-11-20T02:00:00Z")).toBeNull();
    expect(recordedSpan("2026-11-20T02:00:18", "2026-11-20T02:00:00Z")).toBeNull();
    expect(recordedSpan("unknown", undefined)).toBeNull();
  });

  it("deduplicates receipt links using all scope fields", () => {
    const base: ReceiptLink = { run_id: "run_1", world_revision: "factual", receipt_id: "r9" };
    const otherWorld = { ...base, world_revision: "counterfactual" };
    const otherRun = { ...base, run_id: "run_2" };
    expect(uniqueReceipts([base, { ...base }, otherWorld, otherRun])).toEqual([base, otherWorld, otherRun]);
  });
});
