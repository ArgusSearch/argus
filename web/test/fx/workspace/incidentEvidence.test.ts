import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { incidentTimeline } from "../../../src/fx/workspace/incidentEvidence";
import type { Incident } from "../../../src/lib/types";

const [incident] = JSON.parse(
  readFileSync(new URL("../../../../fixtures/incidents.json", import.meta.url), "utf8"),
) as Incident[];

describe("incident timeline", () => {
  it("merges real log events and recorded incident transitions in chronological order", () => {
    const entries = incidentTimeline(incident);
    expect(entries.map((entry) => entry.at)).toEqual(entries.map((entry) => entry.at).sort());
    expect(entries).toContainEqual(expect.objectContaining({
      label: "Cause logged",
      at: incident.findings.root?.evidence?.ts,
      detail: incident.findings.root?.evidence?.description,
    }));
    expect(entries.filter((entry) => entry.label === "Ruled-out change")).toHaveLength(2);
    expect(entries.filter((entry) => entry.kind === "state")).toHaveLength(incident.history.length);
  });

  it("keeps repeated transitions and deduplicates the same log event", () => {
    const [ruled] = incident.findings.ruled_out;
    const reopenedAt = "2026-11-22T04:00:00";
    const entries = incidentTimeline({
      ...incident,
      history: [...incident.history, {
        sim_ts: reopenedAt,
        from_state: "resolved",
        to_state: "open",
        reason: "recorded test transition",
      }],
      findings: { ...incident.findings, ruled_out: [...incident.findings.ruled_out, ruled] },
    });
    expect(entries.filter((entry) => entry.label === "Ruled-out change")).toHaveLength(2);
    expect(entries.at(-1)).toEqual(expect.objectContaining({ at: reopenedAt, label: "Reopened" }));
  });
});
