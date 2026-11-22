// Ask Argus: a question in plain words, answered by the agent with the same checks it investigates with, read
// only. Every figure in an answer is a verified claim with its receipts. Opens from the sidebar or with "/",
// closes with Escape; on an incident page the question is asked about that incident.

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Fragment, type ReactNode } from "react";
import { AgentReceiptChips, useOpenReceipt } from "../../components/Receipts";
import { agentApi, type AskAnswer, type ReceiptLink } from "../../lib/agent";
import { useAgentDemo } from "../../lib/agentDemo";
import { AvatarSlot } from "./AvatarSlot";
import { useAgent } from "./agent";

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

const SUGGESTIONS = ["Why did revenue drop?", "What did you rule out?", "What did it cost so far?", "Is anything unusual right now?"];

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
  question: string;
  answer: AskAnswer | null;
  error: string | null;
}

export function AskPanel({ incident }: { incident: string | null }) {
  const agent = useAgent();
  const demo = useAgentDemo();
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
  const input = useRef<HTMLTextAreaElement>(null);
  const list = useRef<HTMLOListElement>(null);

  // "/" opens it from anywhere (not while typing); Escape closes it
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
        setAskOpen(false);
      }
    };
    window.addEventListener("keydown", onKey, { capture: true });
    return () => window.removeEventListener("keydown", onKey, { capture: true });
  }, [agent.enabled]);

  useEffect(() => {
    if (shown) input.current?.focus();
  }, [shown]);

  useEffect(() => {
    list.current?.lastElementChild?.scrollIntoView({
      block: "nearest",
      behavior: "smooth",
    });
  }, [turns]);

  if (!agent.enabled || !shown) return null;

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    setText("");
    setBusy(true);
    const index = turns.length;
    setTurns((t) => [...t, { question: q, answer: null, error: null }]);
    try {
      const same = conversation && conversation.incident === incident ? conversation.id : null;
      const answer = await agentApi.ask(q, incident, same);
      if (answer.conversation_id) setConversation({ id: answer.conversation_id, incident });
      setTurns((t) => t.map((x, i) => (i === index ? { ...x, answer } : x)));
    } catch (e) {
      setTurns((t) => t.map((x, i) => (i === index ? { ...x, error: (e as Error).message } : x)));
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside className="ws-ask" role="dialog" aria-label="Ask Argus">
      <header className="ws-ask-head">
        <div>
          <h2>Ask Argus</h2>
          <p>{incident ? `About ${incident}. ` : ""}Read only: a question never changes anything. Every number comes with its receipt.</p>
        </div>
        <button className="icon-btn" onClick={() => setAskOpen(false)} aria-label="Close Ask Argus">
          ✕
        </button>
      </header>
      <ol className="ws-ask-turns" ref={list}>
        {turns.length === 0 && (
          <li className="ws-ask-empty">
            {suggestions.length ? (
              <>
                <span>{demo ? "Recorded questions" : "Try"}</span>
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
        {turns.map((t, i) => (
          <li key={i} className="ws-ask-turn">
            <p className="ws-ask-q">{t.question}</p>
            {!t.answer && !t.error && (
              <p className="ws-ask-wait">
                <AvatarSlot role="detective" status="working" /> Checking…
              </p>
            )}
            {t.error && <p className="ws-act-error">{t.error}</p>}
            {t.answer &&
              (() => {
                const links = linksOf(t.answer);
                return (
                  <div className="ws-ask-a">
                    <span className="ws-ask-who">
                      <AvatarSlot role="narrator" nameplate /> answers
                    </span>
                    <AnswerText text={t.answer.answer} links={links} />
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
                  </div>
                );
              })()}
          </li>
        ))}
      </ol>
      <form
        className="ws-ask-form"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(text);
        }}
      >
        <textarea
          ref={input}
          name="question"
          rows={2}
          value={text}
          placeholder="Ask about the shop, an incident or a number…"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void ask(text);
            }
          }}
        />
        <button className="btn primary" type="submit" disabled={busy || !text.trim()}>
          {busy ? "Asking…" : "Ask"}
        </button>
      </form>
    </aside>
  );
}
