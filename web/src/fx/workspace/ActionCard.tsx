// What to do about an incident, with the human in the loop. With the agent's routes mounted it is the proposal
// (GET /agent/actions): its exact action, the rule that says whether it worked, approve or deny (the digest the
// operator saw is sent with the decision, so a changed proposal cannot be approved by accident), then the
// lifecycle through applied to the verified outcome with its receipts. Without them it is the findings' suggested
// action with an approval kept in this browser.

import { useState } from "react";
import { AgentReceiptChips } from "../../components/Receipts";
import { agentApi, type ProposalState, type ProposalView } from "../../lib/agent";
import { ApiError } from "../../lib/api";
import { dayLabel, hhmm } from "../../lib/format";
import type { RunView } from "../../lib/store";
import type { IncidentState } from "../../lib/types";
import { proposalFor, useAgent } from "./agent";
import { approve, useApproval } from "./approvals";
import { AvatarSlot } from "./AvatarSlot";
import { Pill } from "./ui";
import type { Tone } from "./plain";

const STAGES = ["Proposed", "Approved", "Applied", "Verified"] as const;

/** How far along the four stages a proposal is, and how its state reads. */
export function stageOf(state: ProposalState): { reached: number; word: string; tone: Tone } {
  switch (state) {
    case "AWAIT_OPERATOR":
      return { reached: 0, word: "Waiting for your decision", tone: "probe" };
    case "DENIED":
      return { reached: 0, word: "Denied", tone: "muted" };
    case "EXPIRED":
      return { reached: 0, word: "Expired, nothing was changed", tone: "muted" };
    case "APPLYING":
      return { reached: 1, word: "Approved, applying", tone: "probe" };
    case "APPLIED":
      return { reached: 2, word: "Applied, checking the effect", tone: "watch" };
    case "VERIFYING":
      return { reached: 2, word: "Checking the effect", tone: "watch" };
    case "VERIFIED":
      return { reached: 3, word: "Verified: it worked", tone: "ok" };
    case "NO_EFFECT":
      return { reached: 2, word: "No effect", tone: "alarm" };
    case "INCONCLUSIVE":
      return { reached: 2, word: "Inconclusive", tone: "watch" };
  }
}

export function ActionCard({
  incidentId,
  incidentState,
  fallback,
  view,
  compact = false,
}: {
  incidentId: string;
  incidentState: IncidentState;
  /** the findings' suggested action, when the agent made no proposal */
  fallback: { text: string; needsApproval: boolean } | null;
  view: RunView;
  compact?: boolean;
}) {
  const agent = useAgent();
  const proposal = agent.enabled ? proposalFor(agent, incidentId) : null;
  if (proposal) return <Proposal proposal={proposal} compact={compact} />;
  if (!fallback) return null;
  return <LocalAction incidentId={incidentId} incidentState={incidentState} fallback={fallback} view={view} />;
}

function Proposal({ proposal, compact }: { proposal: ProposalView; compact: boolean }) {
  const agent = useAgent();
  const [busy, setBusy] = useState<"approve" | "deny" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const stage = stageOf(proposal.state);
  const decide = async (verb: "approve" | "deny") => {
    setBusy(verb);
    setError(null);
    try {
      agent.put(await agentApi.decide(proposal.id, verb, proposal.digest));
    } catch (e) {
      setError(e instanceof ApiError && e.status === 409 ? "The proposal changed since you saw it; here is the current one." : (e as Error).message);
      agent.refresh();
    } finally {
      setBusy(null);
    }
  };
  const failed = proposal.state === "NO_EFFECT" || proposal.state === "INCONCLUSIVE";
  return (
    <div className={`ws-act${compact ? " compact" : ""}`}>
      <p className="ws-act-text">
        <span className="ws-act-by">
          <AvatarSlot role="operator" nameplate status={proposal.state === "AWAIT_OPERATOR" ? "waiting" : stage.reached === 3 ? "done" : "working"} />
          applies it once you approve · {proposal.id}
        </span>
        {proposal.action}
      </p>
      <ol className="ws-act-steps" aria-label={`progress: ${stage.word}`}>
        {STAGES.map((s, i) => (
          <li key={s} className={`${i <= stage.reached ? "done" : ""}${failed && i === 3 ? " failed" : ""}`}>
            <i aria-hidden="true" />
            {i === 3 && failed ? stage.word : s}
          </li>
        ))}
      </ol>
      {!compact && (
        <p className="ws-act-rule">
          <span>It counts as working when</span>
          {proposal.success_rule.rule}
          {proposal.success_rule.comparator === "untreated_twin" ? ", measured against an untouched copy of the shop" : ""}.
        </p>
      )}
      <div className="ws-act-foot">
        <Pill tone={stage.tone}>{stage.word}</Pill>
        {proposal.state === "AWAIT_OPERATOR" && (
          <>
            <button className="btn primary" disabled={busy !== null} onClick={() => decide("approve")}>
              {busy === "approve" ? "Approving…" : "Approve"}
            </button>
            <button className="btn" disabled={busy !== null} onClick={() => decide("deny")}>
              {busy === "deny" ? "Denying…" : "Deny"}
            </button>
            <span className="ws-act-note" title="After this time the proposal lapses unapplied and nothing is changed">
              approve by {dayLabel(proposal.expires_at)} {hhmm(proposal.expires_at)}
            </span>
          </>
        )}
        {proposal.decision && proposal.state !== "AWAIT_OPERATOR" && (
          <span className="ws-act-note">
            {proposal.decision.decision === "approve" ? "approved" : "denied"} by {proposal.decision.principal} at {hhmm(proposal.decision.at)}
          </span>
        )}
      </div>
      {proposal.effect && (
        <div className={`ws-act-effect t-${proposal.effect.state === "VERIFIED" ? "ok" : proposal.effect.state === "NO_EFFECT" ? "alarm" : "watch"}`}>
          <b>{proposal.effect.state === "VERIFIED" ? "Verified outcome" : proposal.effect.state === "NO_EFFECT" ? "No effect" : "Inconclusive"}</b>
          <span>
            {proposal.effect.summary} · checked {hhmm(proposal.effect.checked_at)}
          </span>
          {proposal.effect.claims.map((c) => (
            <span key={c.claim_id} className="ws-act-claim">
              {c.display} <AgentReceiptChips links={c.receipts} max={3} />
            </span>
          ))}
          <AgentReceiptChips
            links={proposal.effect.receipt_refs.filter((r) => !proposal.effect?.claims.some((c) => c.receipts.some((x) => x.receipt_id === r.receipt_id && x.run_id === r.run_id)))}
          />
        </div>
      )}
      {!compact && proposal.evidence_refs.length > 0 && (
        <p className="ws-act-evidence">
          <span>Evidence</span>
          <AgentReceiptChips links={proposal.evidence_refs} max={6} />
        </p>
      )}
      {error && <p className="ws-act-error">{error}</p>}
    </div>
  );
}

function LocalAction({
  incidentId,
  incidentState,
  fallback,
  view,
}: {
  incidentId: string;
  incidentState: IncidentState;
  fallback: { text: string; needsApproval: boolean };
  view: RunView;
}) {
  const approvedAt = useApproval(view.stream, incidentId);
  return (
    <div className="ws-act local">
      <p className="ws-act-text">
        <span>Proposed</span>
        {fallback.text.replace(/\.?$/, ".")}
      </p>
      <div className="ws-act-foot">
        {approvedAt ? (
          <span className="ws-approved">✓ Approval recorded in this browser at {hhmm(approvedAt)}</span>
        ) : incidentState === "resolved" ? (
          <span className="ws-task-note">Recovered on its own; no action needed any more.</span>
        ) : (
          <button
            className="btn primary"
            onClick={() => approve(view.stream, incidentId, view.simTs ?? "")}
            title="Save this decision in this browser for this run"
          >
            Record local approval
          </button>
        )}
      </div>
    </div>
  );
}
