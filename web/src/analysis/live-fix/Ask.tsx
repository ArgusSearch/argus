import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { evidenceChecks, groupRuns, liveLine } from "../../agent-ui/activity";
import { Elapsed } from "../../agent-ui/hooks";
import { caretOnEdge, loadHistory, remember, saveHistory, step, type HistoryPosition } from "../../agent-ui/history";
import { CheckRow } from "../../agent-ui/RunLog";
import { AgentReceiptChips, useOpenReceipt } from "../../components/Receipts";
import { agentApi, type ActivityRecord, type AskAnswer, type ReceiptLink } from "../../lib/agent";
import { ApiError } from "../../lib/api";
import { monitoringText } from "../../lib/format";
import { AgentAvatar } from "../../village/avatars";
import { uniqueReceipts } from "./model";

interface Turn {
  id: number;
  question: string;
  after: number;
  answer?: AskAnswer;
  stopped?: boolean;
  error?: string;
}

function AnswerBody({ answer, records }: { answer: AskAnswer; records: ActivityRecord[] }) {
  const open = useOpenReceipt();
  const cited = uniqueReceipts([...answer.receipt_links, ...answer.claims.flatMap((claim) => claim.receipts)]);
  const links = new Map(cited.map((link) => [link.receipt_id, link]));
  const checks = evidenceChecks(answer, records);
  const text = (body: string, receipts: ReceiptLink[] = []) => {
    const pieces: ReactNode[] = [];
    let offset = 0;
    for (const match of body.matchAll(/\[([a-z]\d+)\]/g)) {
      const link = receipts.find((receipt) => receipt.receipt_id === match[1]) ?? links.get(match[1]);
      pieces.push(monitoringText(body.slice(offset, match.index)));
      pieces.push(link ? <button key={match.index} className="rcpt" type="button" onClick={() => open(link)}>View query</button> : "[Query unavailable]");
      offset = match.index + match[0].length;
    }
    pieces.push(monitoringText(body.slice(offset)));
    return pieces;
  };
  return (
    <div className="lf-answer">
      <strong>Argus</strong>
      {answer.answer && <p>{text(answer.answer)}</p>}
      {answer.status !== "answered" && answer.status !== "ok" && answer.reason && answer.reason !== answer.answer && <p>{text(answer.reason)}</p>}
      {answer.claims.length > 0 && (
        <ul className="lf-claims">
          {answer.claims.map((claim) => <li key={claim.claim_id}>{text(claim.display, claim.receipts)}</li>)}
        </ul>
      )}
      <AgentReceiptChips links={cited} max={cited.length} />
      {checks.length > 0 && (
        <details className="au-evidence">
          <summary>{checks.length} {checks.length === 1 ? "check" : "checks"} behind this answer</summary>
          <ol className="au-steps">{checks.map((check) => <CheckRow key={check.key} check={check} time={false} />)}</ol>
        </details>
      )}
    </div>
  );
}

function askActivity(records: ActivityRecord[], turn: Turn, incidentId: string | null) {
  const newer = records.filter((record) => record.seq > turn.after);
  const questions = newer.filter((record) => record.kind === "chat_question" && record.text === turn.question && record.incident_id === incidentId);
  if (questions.length !== 1 || !questions[0].run_id) return null;
  const matching = groupRuns(newer.filter((record) => record.run_id === questions[0].run_id))[0];
  return matching && !matching.finished ? liveLine(matching) : null;
}

let nextTurn = 0;

/** Embedded read-only Ask. The parent keys this component by source and selected subject. */
export function Ask({ enabled, incidentId, records, replayQuestions, children }: {
  enabled: boolean;
  incidentId: string | null;
  records: ActivityRecord[];
  replayQuestions?: string[];
  children: (turns: ReactNode, controls: ReactNode, count: number) => ReactNode;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [history, setHistory] = useState(loadHistory);
  const conversation = useRef<string | null>(null);
  const position = useRef<HistoryPosition | null>(null);
  const pending = useRef<AbortController | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const helpId = useId();
  const waiting = turns.find((turn) => !turn.answer && !turn.stopped && !turn.error);
  const working = waiting ? askActivity(records, waiting, incidentId) : null;

  useEffect(() => () => pending.current?.abort(), []);

  const stopWaiting = () => {
    pending.current?.abort();
    input.current?.focus({ preventScroll: true });
  };

  const ask = async () => {
    const question = draft.trim();
    if (!enabled || !question || pending.current) return;
    const id = ++nextTurn;
    const controller = new AbortController();
    pending.current = controller;
    position.current = null;
    setDraft("");
    const remembered = remember(history, question);
    setHistory(remembered);
    saveHistory(remembered);
    setTurns((all) => [...all, { id, question, after: records.at(-1)?.seq ?? 0 }]);
    const update = (patch: Partial<Turn>) => setTurns((all) => all.map((turn) => turn.id === id ? { ...turn, ...patch } : turn));
    try {
      let answer: AskAnswer;
      try {
        answer = await agentApi.ask(question, incidentId, conversation.current, controller.signal);
      } catch (error) {
        if (controller.signal.aborted || !(conversation.current && error instanceof ApiError && error.status === 404)) throw error;
        // The server discarded the conversation. Retry the read-only question with a fresh context.
        conversation.current = null;
        answer = await agentApi.ask(question, incidentId, null, controller.signal);
      }
      if (controller.signal.aborted) update({ stopped: true });
      else {
        conversation.current = answer.conversation_id ?? null;
        update({ answer: replayQuestions && answer.status === "unavailable"
          ? { ...answer, answer: "This investigation has no answer to that question." }
          : answer });
      }
    } catch (error) {
      update(controller.signal.aborted ? { stopped: true } : { error: error instanceof Error && error.message ? error.message : "Ask could not load an answer." });
    } finally {
      if (pending.current === controller) pending.current = null;
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.nativeEvent.isComposing) return;
    if (event.key === "Escape" && pending.current) {
      event.preventDefault();
      event.stopPropagation();
      stopWaiting();
      return;
    }
    if (event.key === "Enter" && !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      void ask();
      return;
    }
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    if (event.shiftKey || event.altKey || event.ctrlKey || event.metaKey) return;
    const box = event.currentTarget;
    const direction = event.key === "ArrowUp" ? "backward" : "forward";
    if (!caretOnEdge(box.value, box.selectionStart, box.selectionEnd, direction)) return;
    const next = step({ direction, entries: history, position: position.current, current: draft });
    if (!next) return;
    event.preventDefault();
    position.current = next.position;
    setDraft(next.prompt);
    requestAnimationFrame(() => box.setSelectionRange(next.prompt.length, next.prompt.length));
  };

  const transcript = turns.map((turn) => (
    <li className="lf-turn" key={turn.id}>
      <p className="lf-question">{turn.question}</p>
      {turn.answer ? <AnswerBody answer={turn.answer} records={records} /> : (
        <div className="lf-turn-status" role="status">
          {turn.stopped ? "Stopped waiting. Argus may still finish this request." : turn.error ?? (
            <div className="lf-live">
              {working && <AgentAvatar role={working.role} status="working" size={32} badge={false} />}
              <div><strong>{working?.verb ?? "Waiting for Argus"}</strong>{working?.text && <p>{working.text}</p>}</div>
              <Elapsed id={`live-fix:ask:${turn.id}`} live className="mono" />
            </div>
          )}
        </div>
      )}
    </li>
  ));

  return children(transcript,
    <form className="lf-composer" onSubmit={(event) => { event.preventDefault(); void ask(); }}>
      <label htmlFor={helpId}>Ask Argus <small>{incidentId ?? "Shop"} · Read only</small></label>
      {!turns.length && replayQuestions && replayQuestions.length > 0 && (
        <div className="lf-suggest">
          {replayQuestions.map((question) => <button className="btn" type="button" key={question} onClick={() => { setDraft(question); position.current = null; input.current?.focus(); }}>{question}</button>)}
        </div>
      )}
      <textarea id={helpId} value={draft} rows={2} maxLength={4000} disabled={!enabled} placeholder="Ask about the evidence or outcome…" aria-describedby={`${helpId}-help`} onChange={(event) => { setDraft(event.target.value); position.current = null; }} onKeyDown={onKeyDown} ref={input} />
      <div className="lf-compose-footer">
        <span id={`${helpId}-help`}>{enabled ? "Enter to send · Shift+Enter for a new line" : "Ask is unavailable for this source."}</span>
        {waiting ? <button type="button" className="btn" onClick={stopWaiting}>Stop waiting</button> : <button type="submit" className="btn primary" disabled={!enabled || !draft.trim()}>Send</button>}
      </div>
    </form>,
    turns.reduce((count, turn) => count + (turn.answer || turn.error || turn.stopped ? 2 : 1), 0),
  );
}
