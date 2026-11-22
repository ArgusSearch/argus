// "New metric placed": one placement as a card. The verdict, the metric, where it landed (animated diagram),
// the reasoning in Argus' own words, and the certificate behind it (every check, every receipt) one click away.

import { useState } from "react";
import { ReceiptChips } from "../components/Receipts";
import { placementView, verdictLabel } from "./model";
import { PlacementDiagram } from "./PlacementDiagram";
import type { PlacementResult } from "./types";

const fmtTs = (iso: string) => iso.replace("T", " ").slice(0, 16);

export function NewMetricCard({ placement, onClose }: { placement: PlacementResult; onClose?: () => void }) {
  const view = placementView(placement);
  const [open, setOpen] = useState(false);
  const cert = placement.certificate;
  return (
    <article className={`gx-card ${view.tone}`} aria-label={`${view.kind}: ${view.name}`} key={view.name}>
      <header className="gx-head">
        <span className="gx-kind">{view.kind}</span>
        <span className={`gx-verdict ${view.tone}`}>{verdictLabel(view.verdict)}</span>
        <span className="gx-when mono" title={`${placement.world}, data as of ${fmtTs(placement.as_of)}`}>
          {placement.mode === "recorded" ? "recorded" : "live"} · {fmtTs(placement.as_of)}
        </span>
        {onClose && (
          <button className="gx-close" onClick={onClose} aria-label="Hide the placement card">
            ✕
          </button>
        )}
      </header>
      <h3 className="gx-title">
        {view.label} <span className="mono gx-id">{view.name}</span>
      </h3>
      <p className="gx-desc">{placement.metric.description}</p>
      <PlacementDiagram view={view} placement={placement} />
      <p className={`gx-headline ${view.tone}`}>{view.headline}</p>
      {placement.repair && (
        <pre className="gx-diff" aria-label="repair diff">
          {placement.repair.diff
            .split("\n")
            .filter((l) => !l.startsWith("---") && !l.startsWith("+++") && !l.startsWith("@@"))
            .map((l, i) => (
              <span key={i} className={l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : ""}>
                {l}
                {"\n"}
              </span>
            ))}
        </pre>
      )}
      <footer className="gx-foot">
        <button className="gx-more" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? "Hide certificate" : "Certificate"}
        </button>
        <span className="muted">
          {view.tested} edges tested · {view.receipts} receipts · {placement.world}
        </span>
      </footer>
      {open && (
        <div className="gx-cert">
          {view.reasons.map((r) => (
            <p key={r} className="gx-reason">
              {r}
            </p>
          ))}
          {cert.passed.length > 0 && (
            <>
              <h4>Passed</h4>
              <ul>
                {placement.candidates
                  .filter((c) => c.lifecycle === "accepted")
                  .map((c) => (
                    <li key={c.edge.id}>
                      <span className={`gx-dot ${c.edge.status === "VALID" || c.edge.status === "SUPPORTED" ? "good" : "watch"}`} />
                      <span className="mono">{c.reads}</span> <span className="muted">{c.edge.status}</span>
                      {c.result && <ReceiptChips ids={c.result.receipts} max={1} />}
                    </li>
                  ))}
              </ul>
            </>
          )}
          {cert.uncertain.length > 0 && (
            <>
              <h4>Still uncertain</h4>
              <ul>
                {cert.uncertain.map((u) => (
                  <li key={u}>{u}</li>
                ))}
              </ul>
            </>
          )}
          <h4>Tried</h4>
          <ul className="gx-tried">
            {cert.tried.map((t) => (
              <li key={t} className="mono">
                {t}
              </li>
            ))}
            {view.verdict === "REJECTED" && cert.receipts.length > 0 && (
              <li>
                <ReceiptChips ids={cert.receipts} />
              </li>
            )}
          </ul>
        </div>
      )}
    </article>
  );
}
