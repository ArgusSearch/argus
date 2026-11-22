import "./live-fix.css";
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { firstSentence, gateOf, groupSummary, liveLine } from "../../agent-ui/activity";
import { formatElapsed } from "../../agent-ui/clock";
import { Elapsed, JumpToLatest, useFollowTail } from "../../agent-ui/hooks";
import { CheckRow } from "../../agent-ui/RunLog";
import { AgentReceiptChips, Num, ReceiptChips } from "../../components/Receipts";
import { openIncidentPage } from "../../fx/nav";
import { Proposal } from "../../fx/workspace/ActionCard";
import { useAgent } from "../../fx/workspace/agent";
import { incidentWhere, metricName, STATE, VERDICT, wherePhrase } from "../../fx/workspace/plain";
import { Pill, useIncident } from "../../fx/workspace/ui";
import { useAgentDemo } from "../../lib/agentDemo";
import { dayLabel, eur, hhmm, humanize, share } from "../../lib/format";
import type { RunView } from "../../lib/store";
import type { ProposalView } from "../../lib/agent";
import type { Anomaly, Graph, Incident, Quantity, Verdict } from "../../lib/types";
import { AgentAvatar, agentName, PERSONAS } from "../../village/avatars";
import { Ask } from "./Ask";
import { lineageOf, liveFixThreads, matchesThread, recordedSpan, threadForIncident, uniqueReceipts, type LiveFixThread } from "./model";

export interface LiveFixProps {
  view: Pick<RunView, "stream" | "mode" | "incidents" | "anomalies">;
  graph?: Graph | null;
  incidentId?: string | null;
  runId?: string | null;
  /** Supply to put run selection in the host URL. Omit for local selection. */
  onSelectRun?: (runId: string) => void;
  onOpenIncident?: (incidentId: string) => void;
}

export function LiveFix(props: LiveFixProps) {
  const agent = useAgent();
  const replay = useAgentDemo();
  const scope = replay?.runId ? `replay:${replay.runId}` : agent.scope ?? props.view.stream;
  const selection = props.runId ?? props.incidentId ?? null;
  return <LiveFixWorkspace key={JSON.stringify([scope, selection])} {...props} scope={scope} />;
}

function LiveFixWorkspace({ view, graph = null, incidentId, runId, onSelectRun, onOpenIncident = openIncidentPage, scope }: LiveFixProps & { scope: string | null }) {
  const agent = useAgent();
  const replay = useAgentDemo();
  const playback = replay ? replay.snapshot?.state.status ?? "loading" : null;
  const threads = useMemo(() => liveFixThreads(agent.records, agent.runs, agent.proposals, playback), [agent.records, agent.runs, agent.proposals, playback]);
  const [selected, setSelected] = useState<string | null>(null);
  const [mobileView, setMobileView] = useState("work");
  const [initialRun, setInitialRun] = useState<string | null>(null);
  const requested = selected ?? runId ?? null;
  const first = threads[0]?.id;
  useEffect(() => {
    if (!requested && !incidentId && first) setInitialRun((current) => current ?? first);
  }, [requested, incidentId, first]);
  const thread = requested ? threads.find((entry) => entry.id === requested)
    : incidentId ? threadForIncident(threads, incidentId)
    : threads.find((entry) => entry.id === (initialRun ?? first));
  const subject = requested ? thread?.incidentId ?? null : incidentId ?? thread?.incidentId ?? null;
  const source = replay ? "History" : view.mode === "live" ? "Live" : view.mode === "replay" ? "History" : null;
  const choose = (id: string) => {
    setSelected(id);
    setMobileView("work");
    onSelectRun?.(id);
  };
  return (
    <section className="lf" aria-label="Live Fix" data-mobile-view={mobileView}>
      <header className="lf-header">
        <div><h1>Live Fix</h1>{source && <span className="lf-source mono">{source}</span>}</div>
        <span className="lf-incident-id mono">{subject ?? thread?.id}</span>
        <nav aria-label="Live Fix panels" className="lf-mobile-nav">
          {[["work", "Work"], ["runs", "Runs"], ["insights", "Insights"]].map(([id, label]) => (
            <button type="button" className="btn" aria-pressed={mobileView === id} key={id} onClick={() => setMobileView(id)}>{label}</button>
          ))}
        </nav>
      </header>
      <div className="lf-layout">
        <Threads threads={threads} selected={thread?.id} onSelect={choose} />
        <Subject key={JSON.stringify([requested, subject])} view={view} graph={graph} thread={thread} incidentId={subject} onOpenIncident={onOpenIncident} scope={scope} missingRun={Boolean(requested && !thread)} />
      </div>
    </section>
  );
}

function Threads({ threads, selected, onSelect }: { threads: LiveFixThread[]; selected?: string; onSelect: (id: string) => void }) {
  const [filter, setFilter] = useState("");
  const inputId = useId();
  const working = threads.filter((thread) => thread.state !== "settled" && thread.state !== "unknown");
  const settled = threads.filter((thread) => thread.state === "settled");
  const unknown = threads.filter((thread) => thread.state === "unknown");
  const shelves = [{ name: "Working", entries: working }, { name: "Settled", entries: settled }, { name: "Status unavailable", entries: unknown }];
  return (
    <aside className="lf-runs" aria-label="Agent runs">
      <h2>Agent runs</h2>
      <label className="sr-only" htmlFor={inputId}>Search runs</label>
      <input className="lf-search" type="search" id={inputId} placeholder="Search runs…" value={filter} onChange={(event) => setFilter(event.target.value)} />
      {threads.length === 0 && <p className="lf-muted">No agent runs reported for this source.</p>}
      {threads.length > 0 && !threads.some((entry) => matchesThread(entry, filter)) && <p className="lf-muted">No runs match your search.</p>}
      {shelves.filter((shelf) => shelf.name !== "Status unavailable" || shelf.entries.length > 0).map(({ name, entries }) => {
        const visible = entries.filter((thread) => matchesThread(thread, filter));
        return (
          <details className="lf-shelf" key={name} open>
            <summary>{name} <span className="mono">{visible.length}</span></summary>
            <ul>{visible.map((thread) => (
              <li key={thread.id}>
                <button type="button" className="lf-thread" aria-current={selected === thread.id ? "true" : undefined} onClick={() => onSelect(thread.id)}>
                  <strong>{thread.title}</strong>
                  <span className="lf-thread-meta mono"><span>{thread.id}</span>{thread.at && <time dateTime={thread.at}>{hhmm(thread.at)}</time>}</span>
                  {thread.state !== "settled" && <small>{thread.state}</small>}
                </button>
              </li>
            ))}</ul>
          </details>
        );
      })}
    </aside>
  );
}

type SubjectProps = {
  thread: LiveFixThread | undefined;
  graph: Graph | null;
  view: LiveFixProps["view"];
  incidentId: string | null;
  scope: string | null;
  onOpenIncident: (id: string) => void;
  missingRun: boolean;
};

function Subject(props: SubjectProps) {
  if (props.incidentId) return <IncidentSubject {...props} incidentId={props.incidentId} />;
  return <Investigation {...props} incident={null} />;
}

function IncidentSubject(props: SubjectProps & { incidentId: string }) {
  const { incidentId, view } = props;
  const { incident, error } = useIncident(incidentId, view.incidents[incidentId]?.lastSeq ?? 0, view.stream);
  return <Investigation {...props} incident={incident} incidentError={error} />;
}

function Investigation({ thread, incident, incidentId, incidentError, graph, view, scope, onOpenIncident, missingRun }: SubjectProps & { incident: Incident | null; incidentError?: string | null }) {
  const agent = useAgent();
  const replay = useAgentDemo();
  const trigger = view.anomalies.find((anomaly) => anomaly.id === incident?.findings.anomaly_id);
  const roles = useMemo(() => thread ? lineageOf(thread) : [], [thread]);
  const line = thread?.state === "working" && thread.group ? liveLine(thread.group) : null;
  const clockId = line ? JSON.stringify(["live-fix", scope, thread?.id]) : undefined;
  return (
    <>
      <Ask enabled={agent.enabled && !missingRun} incidentId={incidentId} records={agent.records} replayQuestions={agent.enabled ? replay?.snapshot?.questions : undefined}>
        {(turns, composer, count) => (
          <Transcript count={count + (line ? thread?.group?.records.length ?? 0 : 0)} composer={composer} turns={turns} heading={
            <header className="lf-work-heading">
              <h2>{incident ? `${metricName(graph, incident.root_node)} · ${wherePhrase(incidentWhere(incident))}` : thread?.title ?? "Investigation"}</h2>
              {incident && <Pill tone={STATE[incident.state].tone}>{STATE[incident.state].label}</Pill>}
              {incident && <button type="button" className="ag-link" onClick={() => onOpenIncident(incident.id)}>Open incident report</button>}
            </header>
          }>
            {incidentId && !incident && <p className="lf-muted" role="status">{incidentError ?? "Loading incident evidence…"}</p>}
            {missingRun && <p className="lf-muted">The requested run is unavailable in this source.</p>}
            {!missingRun && !incidentId && !thread && <p className="lf-muted">Select an incident or an agent run to see its work.</p>}
            {incident && <IncidentEvidence incident={incident} />}
            {thread && <RunWork thread={thread} roles={roles} clockId={clockId} />}
            {line && clockId && <div className="lf-live" role="status">
              <AgentAvatar role={line.role} status="working" size={32} badge={false} />
              <div><strong>{line.verb}</strong>{line.text && <p>{line.text}</p>}</div>
              <span className="mono" title="Time observed in this browser">Watching for <Elapsed id={clockId} live /></span>
            </div>}
          </Transcript>
        )}
      </Ask>
      <Insights incident={incident} thread={thread} trigger={trigger} graph={graph} roles={roles} clockId={clockId} />
    </>
  );
}

function Transcript({ count, composer, turns, heading, children }: { count: number; composer: ReactNode; turns: ReactNode; heading: ReactNode; children: ReactNode }) {
  const tail = useFollowTail(count);
  return (
    <section className="lf-main" aria-label="Investigation work">
      {heading}
      <div className="lf-transcript-wrap">
        <div className="lf-transcript" ref={count > 0 ? tail.ref : undefined} tabIndex={0} aria-label="Investigation transcript" onClick={(event) => {
          if (event.target instanceof Element && event.target.closest("summary")) tail.release();
        }}>
          {children}
          <ol className="lf-turns">{turns}</ol>
        </div>
        {count > 0 && <JumpToLatest tail={tail} noun="updates" />}
      </div>
      {composer}
    </section>
  );
}

function IncidentEvidence({ incident }: { incident: Incident }) {
  const { findings } = incident;
  const cause = findings.root?.evidence;
  return (
    <article className="lf-findings">
      <h3>Findings</h3>
      <p>{findings.headline}</p>
      {cause && <div className="lf-finding-note">
        <strong>{cause.description}</strong>
        <span>{dayLabel(cause.ts)} · {hhmm(cause.ts)} UTC</span>
      </div>}
      {findings.trail.length > 0 && <details className="lf-disclosure">
        <summary>{findings.trail.length} investigation steps</summary>
        <ol className="lf-inc-steps">
          {findings.trail.map((step) => (
            <li key={step.step}>
              <strong>{step.hypothesis ?? humanize(step.kind)}</strong>
              {step.prediction && <p>Expected if true · {step.prediction}</p>}
              <p>{step.result}</p>
              {step.why && <p className="lf-muted">{step.why}</p>}
              <ReceiptChips ids={step.receipts} max={step.receipts.length} />
            </li>
          ))}
        </ol>
      </details>}
    </article>
  );
}

function RunWork({ thread, roles, clockId }: { thread: LiveFixThread; roles: ReturnType<typeof lineageOf>; clockId?: string }) {
  const [workOpen, setWorkOpen] = useState(false);
  const { group, proposals, run } = thread;
  const span = recordedSpan(group?.records[0]?.sim_ts, thread.at ?? undefined);
  const origin = (id: string) => group?.records.find((record) => record.kind === "action_proposed" && record.action_id === id);
  const featured = proposals.filter((proposal) => proposal.state === "AWAIT_OPERATOR" && (!workOpen || !origin(proposal.id)));
  const orphaned = proposals.filter((proposal) => proposal.state !== "AWAIT_OPERATOR" && !origin(proposal.id));
  const summary = group ? groupSummary(group, thread.state === "working") : run ? `${run.tool_calls} checks` : "Run details";
  return (
    <article className="lf-work">
      <details className="lf-disclosure" onToggle={(event) => setWorkOpen(event.currentTarget.open)}>
        <summary>{span && thread.state === "settled" ? <>Worked for {formatElapsed(span)} <small>elapsed time</small></> : "Agent work"} <small>{summary}</small></summary>
        {group?.steps.length ? <ol className="au-steps">
          {group.steps.map((step) => {
            if (step.kind === "check") return <CheckRow key={step.key} check={step} />;
            const record = step.record;
            const proposal = record.kind === "action_proposed" ? proposals.find((entry) => entry.id === record.action_id) : undefined;
            if (proposal) {
              if (origin(proposal.id)?.seq !== record.seq || (proposal.state === "AWAIT_OPERATOR" && !workOpen)) return null;
              return <Approval key={step.key} proposal={proposal} at={record.sim_ts} />;
            }
            if (!record.text && !record.receipt_links.length) return null;
            return <li className="lf-record" key={step.key}>
              <span className="mono">{hhmm(record.sim_ts)} UTC · {humanize(record.kind)}</span>
              <p>{record.text}</p>
              <AgentReceiptChips links={record.receipt_links} max={record.receipt_links.length} />
            </li>;
          })}
        </ol> : <p className="lf-muted">No detailed activity is available for this run.</p>}
        {orphaned.length > 0 && <ol className="au-steps">{orphaned.map((proposal) => <Approval key={proposal.id} proposal={proposal} />)}</ol>}
      </details>
      {roles.length > 0 && <details className="lf-disclosure">
        <summary>
          <span className="lf-avatar-stack" aria-hidden="true">{roles.map(({ role }) => <AgentAvatar key={role} role={role} size={23} badge={false} />)}</span>
          {roles.length} {roles.length === 1 ? "role" : "roles"} <small>{roles.some((role) => role.working) ? "1 working" : "Observed in this run"}</small>
        </summary>
        <Lineage roles={roles} clockId={clockId} />
      </details>}
      <ol className="lf-approvals au-steps">
        {featured.map((proposal) => <Approval key={proposal.id} proposal={proposal} at={origin(proposal.id)?.sim_ts} />)}
      </ol>
    </article>
  );
}

function Approval({ proposal, at }: { proposal: ProposalView; at?: string }) {
  const waiting = proposal.state === "AWAIT_OPERATOR";
  return (
    <li className={`au-step au-approval lf-approval${waiting ? " waiting" : ""}`} aria-label={waiting ? "Proposal awaiting approval" : "Proposal"}>
      <span className="ag-time mono">{at ? hhmm(at) : ""}</span>
      <div className="ag-body"><Proposal proposal={proposal} compact={false} /></div>
    </li>
  );
}

function Lineage({ roles, clockId }: { roles: ReturnType<typeof lineageOf>; clockId?: string }) {
  return (
    <ul className="lf-lineage">
      {roles.map(({ role, last, seconds, working, checks }) => (
        <li key={role}>
          <AgentAvatar role={role} size={29} status={working ? "working" : "idle"} badge={false} />
          <div>
            <strong>{agentName(role)}</strong>
            <span>{PERSONAS[role].title} · {checks.length ? `${checks.length} ${checks.length === 1 ? "check" : "checks"}` : humanize(last.kind)}{working && " · Working"}</span>
            <AgentReceiptChips links={uniqueReceipts([...last.receipt_links, ...(last.observation?.receipt_refs ?? [])])} />
          </div>
          {working && clockId ? <span title="Time observed in this browser"><Elapsed id={clockId} live className="mono" /></span>
            : seconds && <span className="mono" title="Time between role events">{formatElapsed(seconds)}</span>}
        </li>
      ))}
    </ul>
  );
}

function Insights({ incident, trigger, thread, graph, roles, clockId }: { incident: Incident | null; trigger?: Anomaly; thread?: LiveFixThread; graph: Graph | null; roles: ReturnType<typeof lineageOf>; clockId?: string }) {
  const findings = incident?.findings;
  const gate = (thread?.group && gateOf(thread.group)?.admitted) ?? thread?.run?.gate?.admitted;
  const verdict = incident?.verdict ?? gate;
  const verdictLabel = verdict ? VERDICT[verdict as Verdict] : undefined;
  const observed = findings?.observed;
  const metric = observed ? metricName(graph, observed.node) : null;
  const unit = graph?.nodes.find((node) => node.id === observed?.node)?.unit;
  const value = (q: Quantity) => {
    let text: string | undefined;
    if (q.unit === "value") {
      if (unit === "share") text = share(q.value, 1);
      if (unit === "eur" || unit === "eur_per_unit") text = eur(q.value);
    }
    return <Num q={q} text={text} />;
  };
  return (
    <aside className="lf-insights" aria-label="Insights and lineage">
      <h2>Insights</h2>
      <section className="lf-verdict" aria-label="Verdict">
        <h3>Verdict</h3>
        {verdictLabel ? <Pill tone={verdictLabel.tone} title={verdictLabel.help}>{verdictLabel.label}</Pill> : <p className="lf-muted">{verdict ? humanize(verdict) : "No verdict reported yet."}</p>}
        {findings && <time dateTime={findings.as_of} className="lf-muted">As of {dayLabel(findings.as_of)} · {hhmm(findings.as_of)} UTC</time>}
      </section>
      {incident && observed && <section className="lf-measure" aria-label="Observed metrics">
        <h3>{metric}</h3>
        <p>{wherePhrase(observed.segment)}</p>
        <dl>
          <div><dt>Observed</dt><dd>{value(observed.observed)}</dd></div>
          <div><dt>Expected</dt><dd>{value(observed.expected)}</dd></div>
          <div><dt>Change vs expected</dt><dd><Num q={observed.change_pct} /></dd></div>
        </dl>
        {trigger && <dl><div><dt>Anomaly z-score</dt><dd><Num q={{ value: trigger.z, unit: "z", receipt: trigger.receipts[0] ?? null }} /></dd></div></dl>}
      </section>}
      {findings && findings.ruled_out.length > 0 && <details className="lf-disclosure lf-hypotheses">
        <summary>Other hypotheses <span className="mono">{findings.ruled_out.length}</span></summary>
        <ul>{findings.ruled_out.map((item, index) => <li key={index}>
          <strong>{firstSentence(item.hypothesis)}</strong>
          <p>{item.result === "refuted" ? "Ruled out" : "Inconclusive"} · {item.reason}</p>
          <ReceiptChips ids={item.receipts} max={item.receipts.length} />
        </li>)}</ul>
      </details>}
      <section className="lf-lineage-panel">
        <h3>Lineage</h3>
        {roles.length ? <Lineage roles={roles} clockId={clockId} /> : <p className="lf-muted">No role activity reported for this run.</p>}
      </section>
      <small className="lf-credit">Inspired by <a href="https://github.com/pingdotgg/t3code/tree/11224f63d2a3d444ca1fd1f67cd3ff21c1f5f8a1" target="_blank" rel="noreferrer">T3 Code (MIT)</a></small>
    </aside>
  );
}

export default LiveFix;
