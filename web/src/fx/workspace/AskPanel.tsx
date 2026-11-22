// Ask Argus: the chat window. A question in plain words, answered by the live agent with the same checks it
// investigates with, read only. Every figure in an answer is a verified claim with its receipts; the checks behind
// the answer fold out above it and its sources sit under it as chips. Threads are kept on this device and listed in
// the window's left rail; follow-ups stay in one server conversation.
// Opens from the sidebar or with "/", closes with Escape; on an incident page the question is asked about that
// incident. Arrow-up recalls an earlier question, Stop (or Escape while waiting) stops waiting for an answer.
// Layout, composer and timeline follow T3 Code (pingdotgg/t3code, MIT); the patterns are reimplemented here.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Fragment, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { evidenceChecks, groupRuns, isLive, liveLine, type CheckStep } from "../../agent-ui/activity";
import {
  agentQuestion,
  ago,
  loadThreads,
  modelLabel,
  revealed,
  revealStep,
  revealTokens,
  saveThreads,
  threadTitle,
  upsertThread,
  workedFor,
  type ChatThread,
  type ChatTurn,
} from "../../agent-ui/chat";
import { Elapsed, JumpToLatest, useFollowTail } from "../../agent-ui/hooks";
import { caretOnEdge, loadHistory, remember, saveHistory, step, type HistoryPosition } from "../../agent-ui/history";
import { CheckRow } from "../../agent-ui/RunLog";
import { useOpenReceipt } from "../../components/Receipts";
import { AGENT_ROLES, agentApi, roleOf, type ActivityRecord, type AgentRole, type AskAnswer, type ReceiptLink } from "../../lib/agent";
import { ApiError } from "../../lib/api";
import { useAgentDemo } from "../../lib/agentDemo";
import { monitoringText } from "../../lib/format";
import { AvatarSlot } from "./AvatarSlot";
import { PERSONAS } from "../../village/avatars/personas";
import { ROLE } from "../../village/roles";
import { activityAvatarRole } from "../../village/avatars/state";
import { useAgent, type AgentState } from "./agent";
import { isAskOpen, readFlag, setAskOpen, useAgentRequest, useAskOpen, writeFlag } from "./chatStore";
import "./chat.css";

const RAIL_KEY = "argus.chat.rail";

export { setAskOpen, useAskOpen } from "./chatStore";

const SUGGESTIONS = [
  { title: "Why did revenue drop?", hint: "Trace the cause through the metric tree" },
  { title: "Could higher traffic explain the spend?", hint: "Test a hypothesis against the data" },
  { title: "What did you rule out?", hint: "The checks that came back negative" },
  { title: "Is anything unusual right now?", hint: "This hour against the last four weeks" },
];

/** An agent's name, job and what to ask it first; the names are the village's personas. */
function voiceOf(role: AgentRole) {
  const p = PERSONAS[role];
  return { acronym: p.names[0].acronym, title: p.title, ability: ROLE[role].job };
}

const AGENT_SUGGESTIONS: Record<AgentRole, string[]> = {
  watcher: ["Which metrics are outside their band right now?", "What did you check this hour?"],
  cartographer: ["Do all the formulas still hold?", "How is revenue built from the other metrics?"],
  detective: ["Which segment explains the change?", "What is your current lead?"],
  market: ["Is the market moving the same way?", "Could the market explain this change?"],
  skeptic: ["What did you rule out?", "How sure are you about the cause?"],
  narrator: ["What happened since I was away?", "What did this incident cost?"],
  operator: ["What action do you propose?", "What would the fix change?"],
};

/** The agent's own latest steps, as one line each, for the question's framing. */
function stepsOf(role: AgentRole, records: ActivityRecord[]): string[] {
  const out: string[] = [];
  for (let i = records.length - 1; i >= 0 && out.length < 4; i--) {
    const r = records[i];
    if (!r.text || roleOf(r) !== role) continue;
    out.unshift(r.tool ? `${r.tool}: ${r.text}` : r.text);
  }
  return out;
}

const TAG = /\[([a-z]\d+)\]/g;

const reducedMotion = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** A sentence whose receipt tags ([q1], [a31], [r184]) are chips that open the query behind the number. */
function Tagged({ text, links }: { text: string; links: Map<string, ReceiptLink> }) {
  const openReceipt = useOpenReceipt();
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(TAG)) {
    out.push(monitoringText(text.slice(last, m.index)));
    const link = links.get(m[1]);
    out.push(
      link ? (
        <button key={`${m.index}`} type="button" className="cw-cite" title="Open the query behind this number" onClick={() => openReceipt(link)}>
          {m[1]}
        </button>
      ) : (
        <span key={`${m.index}`} className="cw-cite off" title="Query unavailable">
          {m[1]}
        </span>
      ),
    );
    last = (m.index ?? 0) + m[0].length;
  }
  out.push(monitoringText(text.slice(last)));
  return <>{out}</>;
}

/** The answer as it was written: paragraphs on its line breaks, "- " lines as a list, tags as receipt chips. */
function AnswerText({ text, links, caret }: { text: string; links: Map<string, ReceiptLink>; caret?: boolean }) {
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
  const end = caret ? <i className="cw-caret" aria-hidden="true" /> : null;
  return (
    <div className="cw-md">
      {blocks.map((b, i) => {
        const tail = i === blocks.length - 1 ? end : null;
        return b.list ? (
          <ul key={i}>
            {b.lines.map((l, j) => (
              <li key={j}>
                <Tagged text={l} links={links} />
                {j === b.lines.length - 1 && tail}
              </li>
            ))}
          </ul>
        ) : (
          <Fragment key={i}>
            {b.lines.map((l, j) => (
              <p key={j}>
                <Tagged text={l} links={links} />
                {j === b.lines.length - 1 && tail}
              </p>
            ))}
          </Fragment>
        );
      })}
      {!blocks.length && end}
    </div>
  );
}

/**
 * A finished, number-checked answer revealed word by word, the way T3 Code streams a reply. The text is complete
 * and verified before the first word shows, so streaming never displays an unchecked figure.
 */
function Streamed({ text, links, fresh, onDone }: { text: string; links: Map<string, ReceiptLink>; fresh: boolean; onDone: () => void }) {
  const tokens = useMemo(() => revealTokens(text), [text]);
  const [count, setCount] = useState(() => (fresh && !reducedMotion() ? 0 : tokens.length));
  const done = count >= tokens.length;
  useEffect(() => {
    if (done) {
      onDone();
      return;
    }
    const per = revealStep(tokens.length);
    const frame = requestAnimationFrame(() => setCount((c) => Math.min(tokens.length, c + per)));
    return () => cancelAnimationFrame(frame);
  }, [count, done, tokens.length, onDone]);
  return <AnswerText text={revealed(tokens, count)} links={links} caret={!done} />;
}

/** Every receipt the answer cites, by its id, so a tag in the prose finds its link. */
function linksOf(answer: AskAnswer): Map<string, ReceiptLink> {
  const all = [...answer.receipt_links, ...answer.claims.flatMap((c) => c.receipts)];
  return new Map(all.map((l) => [l.receipt_id, l]));
}

/** The answer's sources as chips under it, like T3 Code's citation chips: one per receipt, each opens its query. */
function Sources({ links }: { links: ReceiptLink[] }) {
  const openReceipt = useOpenReceipt();
  const unique = [...new Map(links.map((l) => [`${l.run_id}/${l.receipt_id}`, l])).values()];
  if (!unique.length) return null;
  const shown = unique.slice(0, 8);
  return (
    <div className="cw-sources" aria-label="Sources">
      {shown.map((l) => (
        <button key={`${l.run_id}/${l.receipt_id}`} type="button" className="cw-source" title="Open the query behind this number" onClick={() => openReceipt(l)}>
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M3.5 2.5h6l3 3v8h-9zM9.5 2.5v3h3M5.5 8.5h5M5.5 11h3.5" />
          </svg>
          Query {l.receipt_id}
        </button>
      ))}
      {unique.length > shown.length && <span className="cw-source more">+{unique.length - shown.length}</span>}
    </div>
  );
}

/** The turn's work as one folded separator ("Worked for 4.2s · 5 checks"), opening to the checks themselves. */
function Work({ ms, checks }: { ms: number | null; checks: CheckStep[] }) {
  const label = (
    <>
      {ms !== null && ms >= 500 ? `Worked for ${workedFor(ms)}` : "Answered"}
      {checks.length > 0 && ` · ${checks.length} check${checks.length === 1 ? "" : "s"}`}
    </>
  );
  if (!checks.length)
    return (
      <div className="cw-work" role="separator">
        <span>{label}</span>
        <span className="cw-rule" />
      </div>
    );
  return (
    <details className="cw-work-fold">
      <summary className="cw-work">
        <span>
          {label}
          <svg className="cw-chev" viewBox="0 0 16 16" aria-hidden="true">
            <path d="M6 4l4 4-4 4" />
          </svg>
        </span>
        <span className="cw-rule" />
      </summary>
      <ol className="au-steps cw-steps">
        {checks.map((c) => (
          <CheckRow key={c.key} check={c} time={false} />
        ))}
      </ol>
    </details>
  );
}

/** While an answer is on its way: what the answering run is doing now, else that Argus is working, with the time. */
function Waiting({ turn, records, streaming }: { turn: ChatTurn; records: ActivityRecord[]; streaming: boolean }) {
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
    <div className="cw-waiting" aria-live="polite">
      <AvatarSlot role={role} size="sm" cue={run && current?.runId === run.runId ? current : undefined} />
      <span className="cw-waiting-text">
        <b className="au-shine">{now ? now.verb : "Working"}</b>
        {now?.text && <span>{now.text}</span>}
      </span>
      <Elapsed id={`ask:${turn.id}`} live className="cw-waiting-time" />
    </div>
  );
}

function Assistant({ turn, agent, who, fresh, onStreamed }: { turn: ChatTurn & { answer: AskAnswer }; agent: AgentState; who: AgentRole | null; fresh: boolean; onStreamed: (id: number) => void }) {
  const answer = turn.answer;
  const links = useMemo(() => linksOf(answer), [answer]);
  const answered = answer.status === "answered" || answer.status === "ok";
  const checks = useMemo(() => evidenceChecks(answer, agent.records), [answer, agent.records]);
  const [streaming, setStreaming] = useState(fresh);
  const done = useCallback(() => {
    setStreaming(false);
    onStreamed(turn.id);
  }, [onStreamed, turn.id]);
  const role = who ?? "narrator";
  const current = agent.avatars[role];
  const cue = current?.runId && current.runId === answer.run_id ? current : undefined;
  const allLinks = [...answer.receipt_links, ...answer.claims.flatMap((c) => c.receipts)];
  return (
    <div className={`cw-assistant${answered ? "" : " unanswered"}`}>
      <Work ms={turn.answeredAt ? turn.answeredAt - turn.askedAt : null} checks={checks} />
      <div className="cw-author">
        <AvatarSlot role={role} size="sm" cue={cue} paused={!cue} />
        <b>{who ? voiceOf(who).acronym : "Argus"}</b>
        {who && <span className="cw-role">{voiceOf(who).title}</span>}
        {!answered && <span className="cw-flag">could not answer</span>}
        {typeof answer.usd === "number" && answer.usd > 0 && <span className="cw-cost">${answer.usd.toFixed(3)}</span>}
      </div>
      <Streamed text={answer.answer} links={links} fresh={fresh} onDone={done} />
      {!streaming && (
        <>
          {!answered && answer.reason && answer.reason !== answer.answer && <p className="cw-reason">{answer.reason}</p>}
          {answer.claims.length > 0 && (
            <div className="cw-claims">
              <span className="cw-label">Checked figures</span>
              <ul>
                {answer.claims.map((c) => (
                  <li key={c.claim_id}>
                    <svg viewBox="0 0 16 16" aria-hidden="true">
                      <path d="M3.5 8.5l3 3 6-7" />
                    </svg>
                    <span>
                      <Tagged text={c.display} links={links} />
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <Sources links={allLinks} />
        </>
      )}
    </div>
  );
}

// unique across hot reloads and remounts: the runtime clock keys each wait by it
let turnIds = Date.now();

const newThreadId = () => `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;

export function AskPanel({ incident }: { incident: string | null }) {
  const agent = useAgent();
  const demo = useAgentDemo();
  // threads are kept per presentation run, or for the live shop
  const store = demo?.runId ? `demo:${demo.runId}` : "live";
  return <ChatWindow key={store} store={store} agent={agent} incident={incident} />;
}

function ChatWindow({ store, agent, incident }: { store: string; agent: AgentState; incident: string | null }) {
  const demo = useAgentDemo();
  const streamingRun = demo !== null;
  const shown = useAskOpen();
  const requested = useAgentRequest();
  const [threads, setThreads] = useState<ChatThread[]>(() => loadThreads(store));
  const [thread, setThread] = useState<ChatThread>(() => ({ id: newThreadId(), title: "", agent: requested?.agent ?? null, incident, conversation: null, turns: [], updatedAt: Date.now() }));
  const who = thread.agent ?? null;
  const suggestions = who
    ? AGENT_SUGGESTIONS[who].map((title) => ({ title, hint: `Ask ${voiceOf(who).acronym}` }))
    : demo
      ? (demo.snapshot?.questions ?? []).map((title) => ({ title, hint: "From the investigation" }))
      : SUGGESTIONS;
  const [fresh, setFresh] = useState<Set<number>>(() => new Set());
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  // the rail starts hidden on narrow screens, where it covers the conversation
  const [rail, setRailState] = useState(() => typeof window !== "undefined" && window.innerWidth >= 1280 && readFlag(RAIL_KEY, true));
  const [history, setHistory] = useState<string[]>(loadHistory);
  const position = useRef<HistoryPosition | null>(null);
  const pending = useRef<AbortController | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const turns = thread.turns;
  // a question and its answer are two items of the conversation: the jump button counts both
  const tail = useFollowTail(turns.reduce((n, t) => n + (t.answer || t.error || t.stopped ? 2 : 1), 0));
  const offline = !agent.enabled;

  const setRail = (next: boolean) => {
    setRailState(next);
    writeFlag(RAIL_KEY, next);
  };

  // every change to the current thread is saved with the others
  useEffect(() => {
    setThreads((list) => {
      const next = upsertThread(list, thread);
      saveThreads(store, next);
      return next;
    });
  }, [store, thread]);

  const stop = () => {
    pending.current?.abort();
    input.current?.focus({ preventScroll: true });
  };

  // someone clicked an agent (or the Ask button): show that agent's latest thread, else a new one with it
  const handled = useRef(requested?.seq ?? 0);
  useEffect(() => {
    if (!requested || requested.seq === handled.current) return;
    handled.current = requested.seq;
    pending.current?.abort();
    const agentOf = (t: ChatThread) => t.agent ?? null;
    setThread((current) => {
      if (agentOf(current) === requested.agent) return current;
      const latest = threads.find((t) => agentOf(t) === requested.agent);
      return latest ?? { id: newThreadId(), title: "", agent: requested.agent, incident, conversation: null, turns: [], updatedAt: Date.now() };
    });
  }, [requested, threads, incident]);

  // "/" opens it from anywhere (not while typing); Escape stops a pending answer, else closes
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing = target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));
      if (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        setAskOpen(true);
      } else if (e.key === "Escape" && isAskOpen() && !document.querySelector(".modal[aria-label^='Receipt ']")) {
        e.preventDefault();
        if (pending.current) pending.current.abort();
        else setAskOpen(false);
      }
    };
    window.addEventListener("keydown", onKey, { capture: true });
    return () => window.removeEventListener("keydown", onKey, { capture: true });
  }, []);

  useEffect(() => {
    if (shown) input.current?.focus({ preventScroll: true });
  }, [shown, thread.id]);

  // leaving the page while waiting stops waiting
  useEffect(() => () => pending.current?.abort(), []);

  const streamed = useCallback((id: number) => {
    setFresh((s) => {
      if (!s.has(id)) return s;
      const next = new Set(s);
      next.delete(id);
      return next;
    });
  }, []);

  if (!shown) return null;

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || busy || offline) return;
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
    const turn: ChatTurn = { id, question: q, answer: null, error: null, stopped: false, after, askedAt: Date.now(), answeredAt: null };
    // a thread is about one incident: asking from another page starts a new thread
    const base = thread.turns.length && thread.incident !== incident ? { id: newThreadId(), title: "", agent: who, incident, conversation: null, turns: [], updatedAt: 0 } : thread;
    // an agent's thread asks the same live agent, framed to answer in that role from its own latest steps
    // (a recorded presentation answers its own questions word for word, so there the question goes as typed)
    const sent = who && !streamingRun ? agentQuestion(voiceOf(who), stepsOf(who, agent.records), q) : q;
    const threadId = base.id;
    setThread({ ...base, incident, title: base.title || threadTitle(q), turns: [...base.turns, turn], updatedAt: Date.now() });
    const update = (patch: Partial<ChatTurn>, conversation?: string | null) =>
      setThread((t) =>
        t.id !== threadId
          ? t
          : { ...t, conversation: conversation === undefined ? t.conversation : conversation, turns: t.turns.map((x) => (x.id === id ? { ...x, ...patch } : x)), updatedAt: Date.now() },
      );
    const controller = new AbortController();
    pending.current = controller;
    try {
      const same = base.conversation;
      let answer: AskAnswer;
      try {
        answer = await agentApi.ask(sent, incident, same, controller.signal);
      } catch (e) {
        // the server forgot the conversation (a restarted API): ask again as a new one
        if (!(same && e instanceof ApiError && e.status === 404)) throw e;
        update({}, null);
        answer = await agentApi.ask(sent, incident, null, controller.signal);
      }
      setFresh((s) => new Set(s).add(id));
      update({ answer, answeredAt: Date.now() }, answer.conversation_id ?? undefined);
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

  const newThread = (with_: AgentRole | null = who) => {
    stop();
    setThread({ id: newThreadId(), title: "", agent: with_, incident, conversation: null, turns: [], updatedAt: Date.now() });
    if (window.innerWidth < 1280) setRail(false);
  };

  const openAgent = (role: AgentRole | null) => {
    if (role === who && thread.turns.length === 0) return;
    const latest = threads.find((t) => (t.agent ?? null) === role);
    if (latest) openThread(latest);
    else newThread(role);
  };

  const openThread = (t: ChatThread) => {
    stop();
    setThread(t);
    if (window.innerWidth < 1280) setRail(false);
  };

  const title = thread.title || (who ? `Chat with ${voiceOf(who).acronym}` : "New thread");
  const status = offline ? "Offline" : agent.health?.mode === "replay" || streamingRun ? "Replay" : "Live";

  return (
    <aside className={`cw${rail ? " rail-open" : ""}`} role="dialog" aria-label="Ask Argus">
      <nav className="cw-rail" aria-label="Threads">
        <div className="cw-rail-head">
          <span className="cw-rail-title">Threads</span>
          <button type="button" className="cw-icon" onClick={() => setRail(false)} aria-label="Hide threads" title="Hide threads">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M2.5 3.5h11v9h-11zM6 3.5v9M10.5 6.5L9 8l1.5 1.5" />
            </svg>
          </button>
        </div>
        <button type="button" className="cw-new" onClick={() => newThread()}>
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M8 3.5v9M3.5 8h9" />
          </svg>
          New thread
        </button>
        <span className="cw-rail-label">Agents</span>
        <ul className="cw-agents">
          <li>
            <button type="button" className={`cw-agent${who === null ? " on" : ""}`} onClick={() => openAgent(null)} aria-current={who === null ? "true" : undefined}>
              <span className="cw-agent-mark" aria-hidden="true">
                <svg viewBox="0 0 16 16">
                  <path d="M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2z" />
                </svg>
              </span>
              <span className="cw-agent-text">
                <b>Argus</b>
                <span>All agents together</span>
              </span>
            </button>
          </li>
          {AGENT_ROLES.map((role) => {
            const cue = agent.avatars[role];
            const v = voiceOf(role);
            const state = cue?.status ?? "idle";
            return (
              <li key={role}>
                <button type="button" className={`cw-agent${who === role ? " on" : ""}`} onClick={() => openAgent(role)} aria-current={who === role ? "true" : undefined} title={`Chat with ${v.acronym}, the ${v.title}`}>
                  <AvatarSlot role={role} size="sm" cue={cue} paused={!cue} />
                  <span className="cw-agent-text">
                    <b>{v.acronym}</b>
                    <span>{cue?.text || v.title}</span>
                  </span>
                  <i className={`cw-agent-dot a-${state}`} aria-label={state} />
                </button>
              </li>
            );
          })}
        </ul>
        <span className="cw-rail-label">Recent</span>
        <ol className="cw-threads">
          {threads.length === 0 && <li className="cw-threads-empty">Your questions appear here.</li>}
          {threads.map((t) => (
            <li key={t.id}>
              <button type="button" className={`cw-thread${t.id === thread.id ? " on" : ""}`} onClick={() => openThread(t)} aria-current={t.id === thread.id ? "true" : undefined}>
                <span className="cw-thread-title">{t.title}</span>
                <span className="cw-thread-meta">
                  {t.agent ? `${voiceOf(t.agent).acronym} · ` : ""}
                  {t.incident ? `${t.incident} · ` : ""}
                  {ago(t.updatedAt)}
                </span>
              </button>
            </li>
          ))}
        </ol>
      </nav>
      <section className="cw-main" aria-label="Conversation">
        <header className="cw-head">
          {!rail && (
            <button type="button" className="cw-icon" onClick={() => setRail(true)} aria-label="Show threads" title="Show threads">
              <svg viewBox="0 0 16 16" aria-hidden="true">
                <path d="M2.5 3.5h11v9h-11zM6 3.5v9M9 6.5L10.5 8 9 9.5" />
              </svg>
            </button>
          )}
          <div className="cw-head-title">
            {who && <AvatarSlot role={who} size="sm" cue={agent.avatars[who]} paused={!agent.avatars[who]} />}
            <h2 title={title}>{title}</h2>
            <span className="cw-badge">{incident ?? thread.incident ?? "Boreal Outfitters"}</span>
            <span className={`cw-status s-${status.toLowerCase()}`}>
              <i aria-hidden="true" />
              {status}
            </span>
          </div>
          <button type="button" className="cw-icon" onClick={() => newThread()} aria-label="New thread" title="New thread">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M9.5 2.5h-6v10h10v-6M7 9l.5-2.5L12.5 1.5l2 2-5 5z" />
            </svg>
          </button>
          <button type="button" className="cw-icon" onClick={() => setAskOpen(false)} aria-label="Close Ask Argus" title="Close (Esc)">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" />
            </svg>
          </button>
        </header>
        <div className="cw-body">
          <ol className="cw-timeline" ref={tail.ref} tabIndex={0} aria-label="Ask transcript">
            {turns.length === 0 && (
              <li className="cw-empty">
                <AvatarSlot role={who ?? "narrator"} size="lg" paused />
                <h3>{who ? `Ask ${voiceOf(who).acronym}, the ${voiceOf(who).title}` : "What do you want to know?"}</h3>
                <p>
                  {who ? `${voiceOf(who).ability} ` : ""}
                  {incident ? `Ask about ${incident}. ` : ""}Read only: a question never changes anything. Every number comes with its receipt.
                </p>
                {suggestions.length > 0 && !offline && (
                  <div className="cw-suggest">
                    {suggestions.map((s) => (
                      <button key={s.title} type="button" onClick={() => void ask(s.title)}>
                        <b>{s.title}</b>
                        <span>{s.hint}</span>
                      </button>
                    ))}
                  </div>
                )}
              </li>
            )}
            {turns.map((t) => (
              <li key={t.id} className="cw-turn">
                <div className="cw-user">
                  <p>{t.question}</p>
                </div>
                {!t.answer && !t.error && !t.stopped && <Waiting turn={t} records={agent.records} streaming={streamingRun} />}
                {t.stopped && !t.answer && <p className="cw-note">Stopped waiting. Press ↑ in the box to ask it again.</p>}
                {t.error && (
                  <p className="cw-note error" role="alert">
                    {t.error}
                  </p>
                )}
                {t.answer && <Assistant turn={t as ChatTurn & { answer: AskAnswer }} agent={agent} who={who} fresh={fresh.has(t.id)} onStreamed={streamed} />}
              </li>
            ))}
          </ol>
          <JumpToLatest tail={tail} noun="new" />
        </div>
        <form
          className="cw-composer"
          onSubmit={(e) => {
            e.preventDefault();
            if (busy) stop();
            else void ask(text);
          }}
        >
          {offline && (
            <p className="cw-offline" role="status">
              The live agent is not reachable right now. Ask again when the connection is back.
            </p>
          )}
          <div className="cw-box">
            <textarea
              ref={input}
              name="question"
              rows={2}
              value={text}
              disabled={offline}
              placeholder={who ? `Message ${voiceOf(who).acronym}` : incident ? `Ask about ${incident}…` : "Ask about the shop, an incident or a number…"}
              aria-label="Question for Argus"
              aria-describedby="cw-keys"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  void ask(text);
                } else if (e.key === "ArrowUp") recall("backward", e);
                else if (e.key === "ArrowDown") recall("forward", e);
              }}
            />
            <div className="cw-bar">
              <span className="cw-chip" title="What the question is about">
                <svg viewBox="0 0 16 16" aria-hidden="true">
                  <path d="M2.5 6.5L8 2.5l5.5 4v7h-11z" />
                </svg>
                {incident ?? "Whole shop"}
              </span>
              <span className="cw-chip" title="A question never changes anything">
                <svg viewBox="0 0 16 16" aria-hidden="true">
                  <path d="M4.5 7.5v-2a3.5 3.5 0 017 0v2M3.5 7.5h9v6h-9z" />
                </svg>
                Read only
              </span>
              <span className="cw-chip cw-model" title="The model the agent answers with">
                <i className={`cw-dot s-${status.toLowerCase()}`} aria-hidden="true" />
                {modelLabel(agent.health)}
              </span>
              {busy ? (
                <button className="cw-send stop" type="submit" title="Stop waiting for the answer (Esc)" aria-label="Stop">
                  <i aria-hidden="true" />
                </button>
              ) : (
                <button className="cw-send" type="submit" disabled={!text.trim() || offline} title="Ask (Enter)" aria-label="Ask">
                  <svg viewBox="0 0 16 16" aria-hidden="true">
                    <path d="M8 13V3.5M3.5 8L8 3.5 12.5 8" />
                  </svg>
                </button>
              )}
            </div>
          </div>
          <span id="cw-keys" className="cw-keys">
            <kbd>Enter</kbd> ask · <kbd>Shift</kbd>+<kbd>Enter</kbd> new line · <kbd>↑</kbd> earlier question · <kbd>Esc</kbd> {busy ? "stop" : "close"}
          </span>
        </form>
      </section>
    </aside>
  );
}
