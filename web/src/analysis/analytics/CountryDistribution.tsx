import type { MouseEventHandler } from "react";
import { ReceiptChips } from "../../components/Receipts";
import { wherePhrase } from "../../fx/workspace/plain";
import { Card } from "../../fx/workspace/ui";
import { pct, share } from "../../lib/format";
import type { GraphNode, Incident, Segment } from "../../lib/types";
import { dateTime, time, type DistributionRow } from "./model";

interface CountryDistributionProps {
  metric: GraphNode;
  scope: string;
  rows: DistributionRow[];
  incident?: Incident;
  measurement?: Incident["findings"]["window"];
  volumeBasis?: string;
  segmentHref?: (segment: Segment) => string;
  incidentHref?: (id: string) => string;
  onNavigate?: MouseEventHandler<HTMLAnchorElement>;
}

export function CountryDistribution({ metric, scope, rows, incident, measurement, volumeBasis, segmentHref, incidentHref, onNavigate }: CountryDistributionProps) {
  const start = time(measurement?.start);
  const end = time(measurement?.end);
  return (
    <Card title="Country Distribution" className="an-card an-distribution"
      action={incident && incidentHref && <a href={incidentHref(incident.id)} onClick={onNavigate}>{incident.id}</a>}>
      <div className="an-context">
        <strong>{metric.label} · {scope}</strong>
        {rows.length > 0 && start !== null && end !== null && (
          <span>Segment search window · {dateTime(start)}{end !== start ? ` → ${dateTime(end)}` : ""}</span>
        )}
      </div>
      {rows.length ? (
        <>
          <p className="an-source an-scroll-note">Scroll to see all columns.</p>
          <div className="an-table-scroll" tabIndex={0} role="region" aria-label="Incident country and segment distribution">
            <table>
              <thead><tr><th scope="col">Observed segment</th><th scope="col">Change vs expected</th><th scope="col">Parent volume</th><th scope="col">Deviation explained</th><th scope="col">Evidence</th></tr></thead>
              <tbody>
                {rows.map(({ segment, parent, change, volumeShare, explainedShare, receipts }) => {
                  const name = wherePhrase(segment);
                  return (
                    <tr key={JSON.stringify(segment)}>
                      <th scope="row">
                        {segmentHref ? <a href={segmentHref(segment)} onClick={onNavigate}>{name}</a> : name}
                        <small>Within {wherePhrase(parent)}</small>
                      </th>
                      <td>{pct(change * 100, 2)}</td>
                      <td>{share(volumeShare, 2)}</td>
                      <td>{share(explainedShare, 1)}</td>
                      <td><ReceiptChips ids={[...receipts]} max={receipts.length} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="an-source">Rows overlap along the incident’s segment search path. Volume is relative to each parent{volumeBasis && ` (${volumeBasis})`}. Deviation explained is relative to the start of the search.</p>
        </>
      ) : <p className="fx-empty">No measured country or segment breakdown for this scope and period.</p>}
    </Card>
  );
}
