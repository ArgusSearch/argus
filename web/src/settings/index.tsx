import type { RunView } from "../lib/store";
import type { Graph } from "../lib/types";
import { CalendarPage } from "./CalendarPage";
import { SettingsPage } from "./SettingsPage";
import "./settings.css";

export default function SettingsSurface({
  section,
  graph,
  view,
}: {
  section: "settings" | "calendar";
  graph: Graph | null;
  view: RunView;
}) {
  return (
    <main className="fx-dash cs-surface" aria-label={section === "settings" ? "Settings" : "Calendar"}>
      {section === "settings" ? <SettingsPage graph={graph} view={view} /> : <CalendarPage key={view.stream} graph={graph} view={view} />}
    </main>
  );
}
