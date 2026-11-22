import { useId, useMemo, useRef, useState, type ReactNode } from "react";
import { useAppState } from "../../lib/AppState";
import { dayLabel, hhmm, segmentLabel } from "../../lib/format";
import type { RunView } from "../../lib/store";
import type { Graph } from "../../lib/types";
import { metricName } from "../../fx/workspace/plain";
import { LiveFix } from "../live-fix";
import { AnalysisPages } from "../pages/AnalysisPages";
import { analysisIncidents, analysisSignals, analysisWindow, observedSegments } from "../pages/model";
import { analysisHref, followLink, navigateWorkspaceURL } from "./location";
import { ANALYSIS_PAGES, ANALYSIS_PERIODS, segmentKey, type AnalysisPeriod, type AnalysisQuery } from "./query";
import "./analysis.css";

interface AnalysisShellProps {
  graph: Graph | null;
  view: RunView;
  query: AnalysisQuery;
  openIncident: (id: string) => void;
  secondaryLinks: ReactNode;
  streamError?: string | null;
}

export function AnalysisShell({ graph, view, query, openIncident, secondaryLinks, streamError }: AnalysisShellProps) {
  const { monitor } = useAppState();
  const heading = useRef<HTMLHeadingElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const [pagesOpen, setPagesOpen] = useState(false);
  const [shareStatus, setShareStatus] = useState("");
  const pagesId = useId();
  const menu = useRef<HTMLButtonElement>(null);
  const title = ANALYSIS_PAGES.find(([id]) => id === query.page)?.[1];
  const metrics = useMemo(() => (graph?.nodes ?? []).map((node) => ({
    id: node.id, label: metricName(graph, node.id),
  })).sort((a, b) => a.label.localeCompare(b.label)), [graph]);
  const segments = useMemo(() => observedSegments(view, graph, query.metric), [view, graph, query.metric]);
  const window = analysisWindow(view.simTs, query.period);
  const incidents = analysisIncidents(view, query, window);
  const signals = analysisSignals(view, query, window);
  const selectedScope = segmentKey(query.segment);
  const hasScope = Object.keys(query.segment).length > 0;
  const liveFix = query.page === "live-fix";
  const focusQuery = (next: AnalysisQuery) => {
    if (liveFix || next.page === "live-fix") content.current?.focus();
    else heading.current?.focus();
  };
  const navigate = (next: AnalysisQuery) => {
    setShareStatus("");
    navigateWorkspaceURL(analysisHref(next));
    if (next.page !== query.page) focusQuery(next);
  };
  const copyQuery = async () => {
    try {
      await navigator.clipboard.writeText(analysisHref(query));
      setShareStatus("Link copied");
    } catch {
      setShareStatus("Copy the link from the address bar");
    }
  };
  const label = query.page === "metrics" && query.metric ? metricName(graph, query.metric) : title;
  return (
    <main className="fx-dash ws-page analysis-shell" aria-labelledby={liveFix ? undefined : "analysis-heading"} aria-label={liveFix ? "Live Fix" : undefined}>
      <nav
        className="analysis-pages"
        aria-label="Analysis pages"
        data-open={pagesOpen}
        onKeyDown={(event) => {
          if (event.key !== "Escape" || !pagesOpen) return;
          event.stopPropagation();
          setPagesOpen(false);
          menu.current?.focus();
        }}
      >
        <button className="btn analysis-menu" type="button" ref={menu} aria-expanded={pagesOpen} aria-controls={pagesId} onClick={(event) => {
          event.currentTarget.focus();
          setPagesOpen(!pagesOpen);
        }}>
          Analysis pages
        </button>
        <div id={pagesId} className="analysis-page-links">
          <h2 className="fx-hud">Analysis</h2>
          {ANALYSIS_PAGES.map(([page, name]) => {
            const next = { ...query, page };
            return (
              <a key={page} href={analysisHref(next)} aria-current={query.page === page ? "page" : undefined} onClick={(event) => followLink(event, () => {
                navigate(next);
                setPagesOpen(false);
                if (next.page === query.page) focusQuery(next);
              })}>{name}</a>
            );
          })}
          <h2 className="fx-hud analysis-secondary">Workspace</h2>
          {secondaryLinks}
        </div>
      </nav>
      <div className="analysis-content" ref={content} tabIndex={-1}>
        {liveFix ? (
          <>
            {streamError && <p className="fx-empty" role="status">Could not refresh the recorded run. {streamError}</p>}
            <LiveFix graph={graph} view={view} incidentId={query.incidentId} runId={query.runId}
              onSelectRun={(runId) => navigate({ ...query, incidentId: undefined, runId })} onOpenIncident={openIncident} />
          </>
        ) : (
          <>
            <header className="analysis-header">
              <div className="ws-head">
                <h1 id="analysis-heading" tabIndex={-1} ref={heading}>{label}</h1>
                <p>
                  {view.mode === "live" ? "Live" : view.mode === "replay" ? "History" : "Connecting"}
                  {view.simTs && monitor.timeLabel ? ` · As of ${monitor.timeLabel} UTC` : ""}
                </p>
              </div>
              <div className="analysis-share">
                <button type="button" className="btn" onClick={() => void copyQuery()}>Copy query link</button>
                <span role="status">{shareStatus}</span>
              </div>
            </header>
            <section className="analysis-query" aria-label="Analysis query">
              <label>
                <span>Metric</span>
                <select value={query.metric} onChange={(event) => navigate({ ...query, metric: event.target.value, segment: {} })}>
                  <option value="">All metrics</option>
                  {query.metric && !metrics.some((metric) => metric.id === query.metric) && <option value={query.metric}>{metricName(graph, query.metric)}</option>}
                  {metrics.map((metric) => <option key={metric.id} value={metric.id}>{metric.label}</option>)}
                </select>
              </label>
              <label>
                <span>Segment</span>
                <select value={hasScope ? selectedScope : ""} onChange={(event) => navigate({
                  ...query, segment: segments.find((segment) => segmentKey(segment) === event.target.value) ?? {},
                })}>
                  <option value="">Any segment</option>
                  {hasScope && !segments.some((segment) => segmentKey(segment) === selectedScope) && <option value={selectedScope}>{segmentLabel(query.segment)}</option>}
                  {segments.map((segment) => <option key={segmentKey(segment)} value={segmentKey(segment)}>{segmentLabel(segment)}</option>)}
                </select>
              </label>
              <label>
                <span>Period</span>
                <select value={query.period} onChange={(event) => navigate({ ...query, period: event.target.value as AnalysisPeriod })}>
                  {ANALYSIS_PERIODS.map(([period, name]) => <option key={period} value={period}>{name}</option>)}
                </select>
              </label>
              {view.firstHour && window.end !== null && (
                <p className="analysis-coverage">
                  Run data starts {dayLabel(view.firstHour)} {hhmm(view.firstHour)} UTC
                </p>
              )}
            </section>
            {streamError && <p className="fx-empty" role="status">Could not refresh the recorded run. {streamError}</p>}
            <AnalysisPages graph={graph} view={view} query={query} window={window} incidents={incidents} signals={signals} navigate={navigate} openIncident={openIncident} />
          </>
        )}
      </div>
    </main>
  );
}
