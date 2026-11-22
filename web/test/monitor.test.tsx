import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { Header } from "../src/components/Header";
import { AgentReceiptChips, ReceiptChips } from "../src/components/Receipts";
import { Overview } from "../src/fx/workspace/Overview";
import { AppStateProvider } from "../src/lib/AppState";
import type { ActivityRecord, RunSummary } from "../src/lib/agent";
import { selectMonitor } from "../src/lib/monitor";
import { emptyView, foldAll, type RunView } from "../src/lib/store";
import type { ArgusEvent } from "../src/lib/types";
import { CalendarPage } from "../src/settings/CalendarPage";
import { CurrentVillage } from "../src/village/CurrentVillage";
import { currentVillage } from "../src/village/current";
import { InvestigationView } from "../src/views/InvestigationView";

vi.mock("../src/settings/language", () => ({ useText: () => (text: string) => text }));

const events: ArgusEvent[] = readFileSync(new URL("../../fixtures/events.jsonl", import.meta.url), "utf8")
  .split("\n").filter(Boolean).map((line) => JSON.parse(line));
const agent = { records: [], proposals: [], runs: [], avatars: {} };
const loadThrough = (predicate: (event: ArgusEvent) => boolean) => {
  const end = events.findIndex(predicate);
  expect(end).toBeGreaterThanOrEqual(0);
  return foldAll(emptyView("example-shop", "live"), events.slice(0, end + 1));
};
const select = (view: RunView) => selectMonitor(view, null, null, "open", agent);
const noop = () => undefined;

describe("workspace monitoring", () => {
  it("renders the same shop time in the header, Overview, Village and Calendar after each update", () => {
    const quiet = loadThrough((event) => event.type === "tick");
    const investigating = loadThrough((event) => event.type === "investigation_step");
    expect(quiet.simTs).not.toBe(investigating.simTs);
    for (const view of [quiet, investigating]) {
      expect(select(view).timeLabel).toBe(view.simTs!.slice(11, 16));
      const pages = [
        <Header view={view} health={null} connection="open" presenting={false} />,
        <Overview view={view} graph={null} onOpenIncident={noop} onSelectNode={noop} />,
        <CurrentVillage graph={null} />,
        <CalendarPage view={view} graph={null} />,
      ];
      for (const page of pages) {
        const html = renderToStaticMarkup(
          <AppStateProvider view={view} graph={null} health={null} connection="open">
            {page}
          </AppStateProvider>,
        );
        expect(html).toContain(select(view).timeLabel);
      }
    }
    expect(select({ ...quiet, mode: "replay" }).timeLabel).toMatch(/^\w{3} \d{2} \w{3} · \d{2}:\d{2}$/);
  });

  it("shares the incident lifecycle and the autonomy counts with the Village", () => {
    const quiet = loadThrough((event) => event.type === "tick");
    const checking = loadThrough((event) => event.type === "investigation_step");
    const filed = loadThrough((event) => event.type === "incident_updated");
    const recovered = loadThrough((event) => event.type === "incident_updated" && event.payload.state === "resolved");
    const quietVillage = currentVillage(quiet, select(quiet), agent, null);
    const activeVillage = currentVillage(checking, select(checking), agent, null);
    const recoveredVillage = currentVillage(recovered, select(recovered), agent, null);

    expect(select(quiet).activeInvestigation).toBe(false);
    expect(quietVillage.state.beat).toBeNull();
    expect(quietVillage.avatars.detective?.status).toBe("sleeping");
    expect(select(checking).activeInvestigation).toBe(true);
    expect(select(checking).autonomy.find((item) => item.key === "investigations")?.value).toBe(1);
    expect(activeVillage.state.simTs).toBe(checking.simTs);
    expect(activeVillage.views.find((role) => role.kind === "working")?.line).toBeTruthy();
    expect(select(filed).openIncidents).toHaveLength(1);
    expect(select(recovered).openIncidents).toHaveLength(0);
    expect(recoveredVillage.state.beat).toBeNull();
    expect(recoveredVillage.views.every((role) => role.kind === null)).toBe(true);
    expect(recoveredVillage.state.roles.watcher.log.length).toBeGreaterThan(0);
  });

  it("clears active agent work as soon as its finish arrives, even when the run summary is a poll behind", () => {
    const view = loadThrough((event) => event.type === "incident_updated");
    const run: RunSummary = {
      run_id: "run-1", kind: "investigate", mode: "live", sim_ts: view.simTs!,
      anomaly_id: view.anomalies[0].id, incident_id: "INC-0001", status: "running", stop_reason: null,
      llm_calls: 0, tool_calls: 0, input_tokens: 0, output_tokens: 0, usd: 0, gate: null, fallback: null,
    };
    const finished: ActivityRecord = {
      seq: 1, run_id: run.run_id, sim_ts: view.simTs!, kind: "run_finished", stage: "REPORT",
      actor: "host", text: "Finished", anomaly_id: run.anomaly_id, incident_id: run.incident_id,
      action_id: null, tool: null, args: null, observation: null, receipt_links: [],
      model: null, input_tokens: null, output_tokens: null, usd: null,
    };
    expect(selectMonitor(view, null, null, "open", { ...agent, runs: [run] }).activeInvestigation).toBe(true);
    const done = selectMonitor(view, null, null, "open", { ...agent, runs: [run], records: [finished] });
    expect(done.activeInvestigation).toBe(false);
    expect(done.runningRun).toBeUndefined();
    expect(done.avatars.detective?.status).toBe("sleeping");
  });

  it("uses metric names and query labels in rendered investigation and Village text", () => {
    const view = loadThrough((event) => event.type === "investigation_step");
    const html = renderToStaticMarkup(
      <AppStateProvider view={view} graph={null} health={null} connection="open">
        <InvestigationView view={view} graph={null} onSelectNode={noop} onOpenIncident={noop} />
        <CurrentVillage graph={null} />
        <ReceiptChips ids={["r226", "r230"]} />
        <AgentReceiptChips links={[{ run_id: "an_0001", world_revision: "r226", receipt_id: "r230" }]} />
      </AppStateProvider>,
    );
    expect(html).toContain("Is the data complete?");
    expect(html).toContain("Working on the next check");
    expect(html).toContain("Query 1");
    expect(html).toContain("View query");
    expect(html).not.toMatch(/\b(?:an_\d+|r\d+)\b/);
    expect(html).not.toMatch(/aria-label="(?:source|speed|progress|Next step|Restart)"/);
  });
});
