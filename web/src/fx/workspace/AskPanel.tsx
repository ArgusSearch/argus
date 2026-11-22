// Ask Argus: a question in plain words, answered by the agent with the same checks it investigates with, read
// only. Every figure in an answer is a verified claim with its receipts, and the checks behind the answer fold out
// under it. Opens from the sidebar or with "/", closes with Escape; on an incident page the question is asked about
// that incident. Follow-ups stay in one conversation; arrow-up recalls an earlier question, Stop (or Escape while
// waiting) stops waiting for an answer. Composer and timeline behaviour follow T3 Code (pingdotgg/t3code, MIT).

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Fragment, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { evidenceChecks, groupRuns, isLive, liveLine, type CheckStep } from "../../agent-ui/activity";
import { Elapsed, JumpToLatest, useFollowTail } from "../../agent-ui/hooks";
import { caretOnEdge, loadHistory, remember, saveHistory, step, type HistoryPosition } from "../../agent-ui/history";
import { CheckRow } from "../../agent-ui/RunLog";
import { AgentReceiptChips, useOpenReceipt } from "../../components/Receipts";
import { agentApi, type ActivityRecord, type AskAnswer, type ReceiptLink } from "../../lib/agent";
import { ApiError } from "../../lib/api";
import { useAgentDemo } from "../../lib/agentDemo";
import { AvatarSlot } from "./AvatarSlot";
import { activityAvatarRole } from "../../village/avatars/state";
import { useAgent, type AgentState } from "./agent";

type Listener = () => void;
const listeners = new Set<Listener>();
let open = false;

export function setAskOpen(next: boolean) {
  if (next === open) return;
  open = next;
  for (const l of [...listeners]) l();
}

export function useAskOpen(): boolean {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => open,
    () => false,
  );
}

const SUGGESTIONS = ["Could higher traffic explain the spend?", "Why did revenue drop?", "What did you rule out?", "What did it cost so far?", "Is anything unusual right now?"];

const TAG = /\[([a-z]\d+)\]/g;
const HAS_TAG = /\[[a-z]\d+\]/;

/** A sentence whose receipt tags ([q1], [a31], [r184]) are chips that open the query behind the number. */
function Tagged({ text, links }: { text: string; links: Map<string, ReceiptLink> }) {
  const openReceipt = useOpenReceipt();
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(TAG)) {
    out.push(text.slice(last, m.index));
    const link = links.get(m[1]);
    out.push(
      link ? (
        <button key={`${m.index}`} className="rcpt" title={`Open the query behind this number (${link.run_id})`} onClick={() => openReceipt(link)}>
          {m[1]}
        </button>
      ) : (
        <span key={`${m.index}`} className="muted mono">
          [{m[1]}]
        </span>
      ),
    );
    last = (m.index ?? 0) + m[0].length;
  }
  out.push(text.slice(last));
  return <>{out}</>;
}

/** The answer as it was written: paragraphs on its line breaks, "- " lines as a list, tags as receipt chips. */
function AnswerText({ text, links }: { text: string; links: Map<string, ReceiptLink> }) {
  const blocks: { list: boolean; lines: string[] }[] = [];
  for (const raw of text.split(/\n+/)) {
    const line = raw.trim();
    if (!line) continue;
    const bullet = /^[-•*]\s+/.test(line);
    const clean = line.replace(/^[-•*]\s+/, "");
    const lastBlock = blocks[blocks.length - 1];
    if (bullet && lastBlock?.list) lastBlock.lines.push(clean);
    else blocks.push({ list: bullet, lines: [clean] });
  }
  return (
    <>
      {blocks.map((b, i) =>
        b.list ? (
          <ul key={i}>
            {b.lines.map((l, j) => (
              <li key={j}>
                <Tagged text={l} links={links} />
              </li>
            ))}
          </ul>
        ) : (
          <Fragment key={i}>
            {b.lines.map((l, j) => (
              <p key={j}>
                <Tagged text={l} links={links} />
              </p>
            ))}
          </Fragment>
        ),
      )}
    </>
  );
}

/** Every receipt the answer cites, by its id, so a tag in the prose finds its link. */
function linksOf(answer: AskAnswer): Map<string, ReceiptLink> {
  const all = [...answer.receipt_links, ...answer.claims.flatMap((c) => c.receipts)];
  return new Map(all.map((l) => [l.receipt_id, l]));
}

interface Turn {
  id: number;
  question: string;
  answer: AskAnswer | null;
  error: string | null;
  /** the reader stopped waiting for this answer */
  stopped: boolean;
  /** the newest activity seq when it was asked: the run that answers it comes after */
  after: number;
}

/** The checks behind an answer, folded under it (T3 Code shows a turn's tool work with its message). */
function Evidence({ checks }: { checks: CheckStep[] }) {
  if (!checks.length) return null;
  return (
    <details className="au-evidence">
      <summary>
        <svg className="au-chev" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M6 4l4 4-4 4" />
        </svg>
        Backed by {checks.length} check{checks.length === 1 ? "" : "s"}
      </summary>
      <ol className="au-steps">
        {checks.map((c) => (
          <CheckRow key={c.key} check={c} time={false} />
        ))}
      </ol>
    </details>
  );
}

/** While an answer is on its way: what the answering run is doing now, else that Argus is checking, with the time. */
function Waiting({ turn, records, streaming }: { turn: Turn; records: ActivityRecord[]; streaming: boolean }) {
  const { avatars } = useAgent();
  const run = useMemo(() => {
    const groups = groupRuns(records.filter((r) => r.seq > turn.after)).filter((g) => g.kind === "ask" && isLive(g, streaming));
    return groups[groups.length - 1] ?? null;
  }, [records, turn.after, streaming]);
  const now = run ? liveLine(run) : null;
  const last = run?.records[run.records.length - 1];
  const role = last ? activityAvatarRole(last) : "narrator";
  const current = avatars[role];
  return (
    <p className="ws-ask-wait" aria-live="polite">
      <AvatarSlot role={role} cue={run && current?.runId === run.runId ? current : undefined} />
      <span className="au-live-text">
        <b className="au-shine">{now ? now.verb : "Checking"}</b>
        {now?.text && <span>{now.text}</span>}
      </span>
      <Elapsed id={`ask:${turn.id}`} live className="au-wait-time" />
    </p>
  );
}

// unique across hot reloads and remounts: the runtime clock keys each wait by it
let turnIds = Date.now();

export function AskPanel({ incident }: { incident: string | null }) {
  const agent = useAgent();
  return <AskConversation key={agent.scope} agent={agent} incident={incident} />;
}

function AskConversation({ agent, incident }: { agent: AgentState; incident: string | null }) {
  const demo = useAgentDemo();
  const streaming = demo !== null;
  const suggestions = demo ? demo.snapshot?.questions ?? [] : SUGGESTIONS;
  const shown = useAskOpen();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  // the server's conversation: follow-ups keep its incident scope and its earlier turns
  const [conversation, setConversation] = useState<{
    id: string;
    incident: string | null;
  } | null>(null);
  const [history, setHistory] = useState<string[]>(loadHistory);
  const position = useRef<HistoryPosition | null>(null);
  const pending = useRef<AbortController | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  // a question and its answer are two items of the conversation: the jump button counts both
  const tail = useFollowTail(turns.reduce((n, t) => n + (t.answer || t.error || t.stopped ? 2 : 1), 0));

  const stop = () => {
    pending.current?.abort();
    input.current?.focus({ preventScroll: true });
  };

  // "/" opens it from anywhere (not while typing); Escape stops a pending answer, else closes
  useEffect(() => {
    if (!agent.enabled) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing = target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));
      if (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        setAskOpen(true);
      } else if (e.key === "Escape" && open && !document.querySelector(".modal[aria-label^='Receipt ']")) {
        e.preventDefault();
        if (pending.current) pending.current.abort();
        else setAskOpen(false);
      }
    };
    window.addEventListener("keydown", onKey, { capture: true });
    return () => window.removeEventListener("keydown", onKey, { capture: true });
  }, [agent.enabled]);

  useEffect(() => {
    if (shown) input.current?.focus();
  }, [shown]);

  // leaving the page while waiting stops waiting
  useEffect(() => () => pending.current?.abort(), []);

  if (!agent.enabled || !shown) return null;

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    setText("");
    position.current = null;
    setHistory((h) => {
      const next = remember(h, q);
      saveHistory(next);
      return next;
    });
    setBusy(true);
    tail.jump();
    const id = ++turnIds;
    const after = agent.records[agent.records.length - 1]?.seq ?? 0;
    setTurns((t) => [...t, { id, question: q, answer: null, error: null, stopped: false, after }]);
    const update = (patch: Partial<Turn>) => setTurns((t) => t.map((x) => (x.id === id ? { ...x, ...patch } : x)));
    const controller = new AbortController();
    pending.current = controller;
    try {
      const same = conversation && conversation.incident === incident ? conversation.id : null;
      let answer: AskAnswer;
      try {
        answer = await agentApi.ask(q, incident, same, controller.signal);
      } catch (e) {
        // the server forgot the conversation (a restarted API): ask again as a new one
        if (!(same && e instanceof ApiError && e.status === 404)) throw e;
        setConversation(null);
        answer = await agentApi.ask(q, incident, null, controller.signal);
      }
      if (answer.conversation_id) setConversation({ id: answer.conversation_id, incident });
      update({ answer });
    } catch (e) {
      if (controller.signal.aborted) update({ stopped: true });
      else update({ error: (e as Error).message });
    } finally {
      if (pending.current === controller) pending.current = null;
      setBusy(false);
    }
  };

  const recall = (direction: "backward" | "forward", e: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    const box = e.currentTarget;
    if (e.shiftKey || e.altKey || e.metaKey || e.ctrlKey || e.nativeEvent.isComposing) return;
    if (!caretOnEdge(box.value, box.selectionStart, box.selectionEnd, direction)) return;
    const next = step({ direction, entries: history, position: position.current, current: text });
    if (!next) return;
    e.preventDefault();
    position.current = next.position;
    setText(next.prompt);
    requestAnimationFrame(() => box.setSelectionRange(next.prompt.length, next.prompt.length));
  };

  const newConversation = () => {
    stop();
    setTurns([]);
    setConversation(null);
  };

  const following = conversation !== null && conversation.incident === incident && turns.some((t) => t.answer);

  return (
    <aside className="ws-ask" role="dialog" aria-label="Ask Argus">
      <header className="ws-ask-head">
        <div>
          <h2>Ask Argus</h2>
          <p>{incident ? `About ${incident}. ` : ""}Read only: a question never changes anything. Every number comes with its receipt.</p>
          {turns.length > 0 && (
            <p className="au-thread">
              {following ? "Follow-ups keep this conversation's context." : "Each question is answered on its own."}
              <button type="button" className="ag-link" onClick={newConversation}>
                New conversation
              </button>
            </p>
          )}
        </div>
        <button className="icon-btn" onClick={() => setAskOpen(false)} aria-label="Close Ask Argus">
          ✕
        </button>
      </header>
      <div className="au-ask-body">
        <ol className="ws-ask-turns" ref={tail.ref} tabIndex={0} aria-label="Ask transcript">
          {turns.length === 0 && (
            <li className="ws-ask-empty">
              {suggestions.length ? (
                <>
                  <span>{demo ? "Questions from the investigation" : "Try"}</span>
                  <div className="ws-ask-suggest">
                    {suggestions.map((s) => (
                      <button key={s} className="btn" onClick={() => void ask(s)}>
                        {s}
                      </button>
                    ))}
                  </div>
                </>
              ) : <span>Recorded answers appear as the investigation progresses.</span>}
            </li>
          )}
          {turns.map((t) => (
            <li key={t.id} className="ws-ask-turn">
              <p className="ws-ask-q">{t.question}</p>
              {!t.answer && !t.error && !t.stopped && <Waiting turn={t} records={agent.records} streaming={streaming} />}
              {t.stopped && <p className="ws-ask-wait au-stopped">Stopped waiting. Press ↑ in the box to ask it again.</p>}
              {t.error && <p className="ws-act-error">{t.error}</p>}
              {t.answer &&
                (() => {
                  const links = linksOf(t.answer);
                  const answered = t.answer.status === "answered" || t.answer.status === "ok";
                  const narrator = agent.avatars.narrator;
                  const cue = narrator?.runId && narrator.runId === t.answer.run_id ? narrator : undefined;
                  return (
                    <div className={`ws-ask-a${answered ? "" : " au-unanswered"}`}>
                      <span className="ws-ask-who">
                        <AvatarSlot role="narrator" nameplate cue={cue} paused={!cue} /> {answered ? "answers" : "could not answer"}
                      </span>
                      <AnswerText text={t.answer.answer} links={links} />
                      {!answered && t.answer.reason && t.answer.reason !== t.answer.answer && <p className="au-reason">{t.answer.reason}</p>}
                      {t.answer.claims.length > 0 && (
                        <>
                          <span className="ws-ask-claims">Checked figures</span>
                          <ul className="ws-ask-claimlist">
                            {t.answer.claims.map((c) => (
                              <li key={c.claim_id}>
                                <Tagged text={c.display} links={links} />
                                {!HAS_TAG.test(c.display) && <AgentReceiptChips links={c.receipts} max={3} />}
                              </li>
                            ))}
                          </ul>
                        </>
                      )}
                      {!HAS_TAG.test(t.answer.answer) && t.answer.claims.length === 0 && <AgentReceiptChips links={t.answer.receipt_links} max={6} />}
                      <Evidence checks={evidenceChecks(t.answer, agent.records)} />
                    </div>
                  );
                })()}
            </li>
          ))}
        </ol>
        <JumpToLatest tail={tail} noun="new" />
      </div>
      <form
        className="ws-ask-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (busy) stop();
          else void ask(text);
        }}
      >
        <textarea
          ref={input}
          name="question"
          rows={2}
          value={text}
          placeholder="Ask about the shop, an incident or a number…"
          aria-label="Question for Argus"
          aria-describedby="ws-ask-keys"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void ask(text);
            } else if (e.key === "ArrowUp") recall("backward", e);
            else if (e.key === "ArrowDown") recall("forward", e);
          }}
        />
        {busy ? (
          <button className="btn au-stop" type="submit" title="Stop waiting for the answer (Esc)">
            <i aria-hidden="true" /> Stop
          </button>
        ) : (
          <button className="btn primary" type="submit" disabled={!text.trim()}>
            Ask
          </button>
        )}
        <span id="ws-ask-keys" className="au-keys">
          Enter asks · Shift+Enter new line · ↑ earlier question{busy ? " · Esc stops" : ""}
        </span>
      </form>
    </aside>
  );
}
