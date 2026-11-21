// Ask Argus: a question in plain words, answered by the agent with the same checks it investigates with, read
// only. Every figure in an answer is a verified claim with its receipts. Opens from the sidebar or with "/",
// closes with Escape; on an incident page the question is asked about that incident.

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { AgentReceiptChips } from "../../components/Receipts";
import { agentApi, type AskAnswer } from "../../lib/agent";
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

interface Turn {
  question: string;
  answer: AskAnswer | null;
  error: string | null;
}

export function AskPanel({ incident }: { incident: string | null }) {
  const agent = useAgent();
  const shown = useAskOpen();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
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
      } else if (e.key === "Escape" && open) {
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
    list.current?.lastElementChild?.scrollIntoView({ block: "nearest", behavior: "smooth" });
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
      const answer = await agentApi.ask(q, incident);
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
            <span>Try</span>
            <div className="ws-ask-suggest">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="btn" onClick={() => void ask(s)}>
                  {s}
                </button>
              ))}
            </div>
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
            {t.answer && (
              <div className="ws-ask-a">
                <span className="ws-ask-who">
                  <AvatarSlot role="narrator" nameplate /> answers
                </span>
                <p>{t.answer.answer}</p>
                {t.answer.claims.length > 0 && (
                  <ul>
                    {t.answer.claims.map((c) => (
                      <li key={c.claim_id}>
                        {c.display} <AgentReceiptChips links={c.receipts} max={3} />
                      </li>
                    ))}
                  </ul>
                )}
                <AgentReceiptChips links={t.answer.receipt_links} max={6} />
              </div>
            )}
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
