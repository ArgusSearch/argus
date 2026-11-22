import { useMemo, useState } from "react";
import { ReceiptChips } from "../components/Receipts";
import { dayLabel, hhmm, pct } from "../lib/format";
import { AGENT_ROLES } from "../lib/agent";
import type { RunView } from "../lib/store";
import type { Graph } from "../lib/types";
import { openIncidentPage } from "../fx/nav";
import { useAgent } from "../fx/workspace/agent";
import { ROLE_TEXT } from "../fx/workspace/AvatarSlot";
import { calendarEntries, logLabel, segmentText, shiftWeek, weekOf, type CalendarEntry, type Lane } from "./model";
import { Badge, Btn, Card, Empty, PageHead, Portrait } from "./ui";

const LANES: Lane[] = ["plan", ...AGENT_ROLES];
const VISIBLE_PER_CELL = 3;
const weekday = (d: string) => new Date(`${d}T00:00:00Z`).toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" });
const dayNum = (d: string) => new Date(`${d}T00:00:00Z`).getUTCDate();
const monthOf = (d: string) => new Date(`${d}T00:00:00Z`).toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });

/** The entry to show first: the planned change Argus held an alert for, else the newest planned change, else none. */
function firstPick(entries: CalendarEntry[]): string | null {
  return (entries.findLast((e) => e.plan?.note) ?? entries.findLast((e) => e.lane === "plan"))?.id ?? null;
}

export function CalendarPage({ graph, view }: { graph: Graph | null; view: RunView }) {
  const agent = useAgent();
  const entries = useMemo(() => calendarEntries(view, graph, agent.proposals), [view, graph, agent.proposals]);
  const now = view.simTs;
  const [weekStart, setWeekStart] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  // Open on the latest held alert even after the run clock moves into a different week.
  const featured = entries.findLast((entry) => entry.plan?.note);
  const runDate = now ?? entries.at(-1)?.ts ?? new Date().toISOString();
  const week = weekOf(weekStart ?? featured?.ts ?? runDate);
  const inWeek = entries.filter((e) => week.includes(e.ts.slice(0, 10)));
  const selected = inWeek.find((e) => e.id === picked) ?? inWeek.find((e) => e.id === firstPick(inWeek)) ?? null;
  const plans = inWeek.filter((e) => e.lane === "plan");
  const held = plans.filter((e) => e.plan?.note).length;

  return (
    <div className="cs-main cs-wide">
      <PageHead
        title="Calendar"
        lead="Planned changes Argus checked against the work each agent did that week."
        actions={
          <div className="cs-weeknav" role="group" aria-label="Calendar week">
            <Btn onClick={() => setWeekStart(shiftWeek(week, -1)[0])} title="Previous week">
              <Chevron />
            </Btn>
            <Btn onClick={() => setWeekStart(weekOf(runDate)[0])} title="The week of the run's current hour">
              Run week
            </Btn>
            <Btn onClick={() => setWeekStart(shiftWeek(week, 1)[0])} title="Next week">
              <Chevron next />
            </Btn>
          </div>
        }
      >
        <div className="cs-chips">
          <Badge tone="calm">{monthOf(week[0])}</Badge>
          <Badge tone={plans.length ? "ok" : "muted"}>
            {plans.length} logged {plans.length === 1 ? "change" : "changes"} seen
          </Badge>
          <Badge tone={held ? "ok" : "muted"}>{held} held back as planned</Badge>
          {now && <Badge>Run clock {dayLabel(now)} {hhmm(now)}</Badge>}
        </div>
      </PageHead>

      <div className="cs-cal-wrap">
        <div className="cs-cal-scroll" tabIndex={0} role="region" aria-label="Weekly calendar">
          <div className="cs-card flush cs-cal" role="table" aria-label={`Week of ${week[0]}`}>
            <div className="cs-cal-row cs-cal-headrow" role="row">
              <div className="cs-cal-lane" role="columnheader">
                <span className="cs-overline">Lane</span>
              </div>
              {week.map((d) => (
                <div key={d} role="columnheader" className={`cs-cal-day${(selected?.ts ?? now)?.startsWith(d) ? " today" : ""}`}>
                  <span>{weekday(d)}</span>
                  <b>{dayNum(d)}</b>
                </div>
              ))}
            </div>
            {LANES.map((lane) => (
              <div key={lane} className="cs-cal-row" role="row">
                <div className="cs-cal-lane" role="rowheader">
                  {lane === "plan" ? (
                    <span className="cs-cal-plan">
                      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 6.5h15v13h-15zM4.5 10.5h15M8 4v5m8-5v5m-8 5h3m2 0h3m-8 3h3" /></svg>
                      <span>
                        Shop plan
                        <small>logged changes</small>
                      </span>
                    </span>
                  ) : (
                    <span className="cs-cal-agent">
                      <Portrait role={lane} size={26} />
                      <span>{ROLE_TEXT[lane].name}</span>
                    </span>
                  )}
                </div>
                {week.map((d) => {
                  const here = inWeek.filter((e) => e.lane === lane && e.ts.startsWith(d));
                  return (
                    <div key={d} role="cell" className={`cs-cal-cell${(selected?.ts ?? now)?.startsWith(d) ? " today" : ""}`}>
                      {here.slice(0, VISIBLE_PER_CELL).map((entry) => <Event key={entry.id} entry={entry} selected={selected?.id === entry.id} onPick={setPicked} />)}
                      {here.length > VISIBLE_PER_CELL && (
                        <details className="cs-cal-more">
                          <summary>{here.length - VISIBLE_PER_CELL} more</summary>
                          {here.slice(VISIBLE_PER_CELL).map((entry) => <Event key={entry.id} entry={entry} selected={selected?.id === entry.id} onPick={setPicked} />)}
                        </details>
                      )}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
        <Detail entry={selected} graph={graph} />
      </div>
      <p className="cs-foot">
        The run supplies agent activity and change logs that investigations consulted. Preview - not wired in the demo: upcoming plans Argus has yet to review.
      </p>
    </div>
  );
}

function Chevron({ next = false }: { next?: boolean }) {
  return <svg viewBox="0 0 16 16" aria-hidden="true"><path d={next ? "m6 4 4 4-4 4" : "m10 4-4 4 4 4"} /></svg>;
}

function Event({ entry, selected, onPick }: { entry: CalendarEntry; selected: boolean; onPick: (id: string) => void }) {
  return (
    <button
      type="button"
      className={`cs-ev t-${entry.tone}${selected ? " on" : ""}`}
      onClick={() => onPick(entry.id)}
      aria-pressed={selected}
      title={entry.title}
    >
      {!entry.count && <time dateTime={entry.ts}>{hhmm(entry.ts)}</time>}
      <span>{entry.title}</span>
    </button>
  );
}

function Detail({ entry, graph }: { entry: CalendarEntry | null; graph: Graph | null }) {
  if (!entry) {
    return (
      <Card title="Nothing selected" className="cs-cal-detail">
        <Empty>Pick an entry in the calendar to see its evidence.</Empty>
      </Card>
    );
  }
  const plan = entry.plan;
  const incident = entry.incident;
  const metric = entry.metric ? (graph?.nodes.find((n) => n.id === entry.metric)?.label ?? entry.metric) : null;
  return (
    <Card
      className="cs-cal-detail"
      title={entry.title}
      desc={`${entry.lane === "plan" ? (plan ? logLabel(plan.log) : "Logged") : ROLE_TEXT[entry.lane].name} · ${dayLabel(entry.ts)}${entry.count ? "" : ` ${hhmm(entry.ts)}`}`}
    >
      <div className="cs-detail-body">
        {plan && plan.uplift !== null && plan.delivered !== null && (
          <div className="cs-plan">
            <dl className="cs-dl">
              <div>
                <dt>Planned</dt>
                <dd className="cs-num">{pct(plan.uplift * 100)}</dd>
              </div>
              <div>
                <dt>Delivered</dt>
                <dd className="cs-num">{pct(plan.delivered * 100)}</dd>
              </div>
              <div>
                <dt>Where</dt>
                <dd>{segmentText(plan.scope)}</dd>
              </div>
            </dl>
            {plan.status && (
              <Badge tone={plan.status === "as planned" ? "ok" : "watch"} dot>
                {plan.status}
              </Badge>
            )}
          </div>
        )}
        {plan?.note ? (
          <div className="cs-quiet">
            <b>Alert held back</b>
            <span>The change stayed within the planned band.</span>
          </div>
        ) : null}
        {(!plan || plan.uplift === null || plan.delivered === null) && <p className="cs-detail-text">{entry.detail}</p>}
        <div className="cs-chips">
          {incident && <Btn onClick={() => openIncidentPage(incident)}>Open {incident}</Btn>}
          {metric && <Badge>{metric}</Badge>}
        </div>
        {entry.receipts.length > 0 && (
          <div>
            <span className="cs-overline">Receipts</span>
            <ReceiptChips ids={entry.receipts} max={6} />
          </div>
        )}
      </div>
    </Card>
  );
}
