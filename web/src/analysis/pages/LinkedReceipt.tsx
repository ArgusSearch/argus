import { useEffect, useRef } from "react";
import { useOpenReceipt } from "../../components/Receipts";
import { useIncident } from "../../fx/workspace/ui";
import type { RunView } from "../../lib/store";
import { useWorkspaceSearch } from "../shell/location";
import { analysisWindow, visibleFindings } from "./model";

export function LinkedReceipt({ id, view }: { id: string; view: RunView }) {
  const search = useWorkspaceSearch();
  const receipt = new URLSearchParams(search).get("receipt");
  if (!receipt || !view.incidents[id]) return null;
  return <IncidentReceipt key={JSON.stringify([view.stream, id, receipt])} id={id} receipt={receipt} view={view} />;
}

function IncidentReceipt({ id, receipt, view }: { id: string; receipt: string; view: RunView }) {
  const summary = view.incidents[id];
  const { incident } = useIncident(id, summary.lastSeq, view.stream);
  const open = useOpenReceipt();
  const opened = useRef(false);
  useEffect(() => {
    if (opened.current || !incident || !visibleFindings(incident, summary, analysisWindow(view.simTs, "all"))) return;
    const { findings } = incident;
    if (findings.root?.change_pct.receipt !== receipt && !findings.trail.some((step) => step.receipts.includes(receipt))) return;
    opened.current = true;
    open(receipt);
  }, [incident, open, receipt, summary, view.simTs]);
  return null;
}
