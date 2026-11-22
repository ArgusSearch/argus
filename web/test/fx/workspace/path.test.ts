// The dashboard's affected-path card against the recorded runs: it shows the scene's preview, so it must be on
// screen exactly while the scene has an affected path to frame for an incident, and follow the same anomaly.
import { describe, expect, it } from "vitest";
import { incidentPath, sceneModel, type SceneModel } from "../../../src/fx/scene/model";
import { affectedPath, type PathSubject } from "../../../src/fx/workspace/path";
import { emptyView, fold, type RunView } from "../../../src/lib/store";
import type { ArgusEvent, Graph } from "../../../src/lib/types";
import { loadEvents, loadGraph } from "../scene/fixtures";

const SCENARIOS = ["", "quiet", "s2", "s3", "s4", "s5"];

function replay(graph: Graph, events: ArgusEvent[], each: (view: RunView, model: SceneModel, subject: PathSubject | null) => void) {
  let view = emptyView("s", "replay");
  let model = sceneModel(graph, view);
  for (const event of events) {
    view = fold(view, event);
    model = sceneModel(graph, view, model);
    each(view, model, affectedPath(view));
  }
  return view;
}

describe("the affected-path card", () => {
  it.each(SCENARIOS)("is on screen only while the scene frames a path that starts at its metric (%s)", (scenario) => {
    const graph = loadGraph(scenario);
    replay(graph, loadEvents(scenario), (view, model, subject) => {
      const path = incidentPath(model, view);
      if (subject) {
        expect(path.has(subject.node), `${view.lastSeq}: ${subject.node} on the path`).toBe(true);
        expect(subject.phase, `${view.lastSeq}`).toBe(model.phase);
      }
      if (model.phase === "anomaly" || model.phase === "investigating") expect(subject, `${view.lastSeq}`).not.toBeNull();
      if (model.phase === "idle" || model.phase === "resolved") expect(subject, `${view.lastSeq}`).toBeNull();
    });
  });

  it("walks S1 from detection through the investigation to the open incident and leaves when it resolves", () => {
    const seen: string[] = [];
    const end = replay(loadGraph(), loadEvents(), (_view, _model, subject) => {
      const key = subject ? `${subject.phase}${subject.incident ? `:${subject.incident.state}` : ""}` : "none";
      if (seen[seen.length - 1] !== key) seen.push(key);
    });
    expect(seen[0]).toBe("none");
    expect(seen.slice(1, 3)).toEqual(["anomaly", "investigating"]);
    expect(seen).toContain("verdict:monitoring");
    expect(seen[seen.length - 1]).toBe("none");
    expect(Object.values(end.incidents).every((inc) => inc.state === "resolved")).toBe(true);
  });

  it("leaves with the verdict when the walk files no incident (S2, a planned change)", () => {
    let shown = false;
    const end = replay(loadGraph("s2"), loadEvents("s2"), (_view, _model, subject) => {
      shown ||= subject !== null;
    });
    expect(shown).toBe(true);
    expect(Object.keys(end.incidents)).toHaveLength(0);
    expect(affectedPath(end)).toBeNull();
  });

  it("is absent before the first anomaly", () => {
    expect(affectedPath(emptyView())).toBeNull();
  });
});
