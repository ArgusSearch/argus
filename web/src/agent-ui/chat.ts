// The chat window's pure parts: saved threads, the streamed reveal of a finished answer, and the composer's
// model chip. Layout and behaviour follow T3 Code (pingdotgg/t3code, MIT); no code is copied from it.

import type { AgentHealth, AskAnswer } from "../lib/agent";

export interface ChatTurn {
  id: number;
  question: string;
  answer: AskAnswer | null;
  error: string | null;
  /** the reader stopped waiting for this answer */
  stopped: boolean;
  /** the newest activity seq when it was asked: the run that answers it comes after */
  after: number;
  /** when it was asked and when the answer came, for "Worked for 4.2s" */
  askedAt: number;
  answeredAt: number | null;
}

export interface ChatThread {
  id: string;
  title: string;
  /** the incident the thread is about, or null for the whole shop */
  incident: string | null;
  /** the server's conversation, so a follow-up keeps its context */
  conversation: string | null;
  turns: ChatTurn[];
  updatedAt: number;
}

const KEY = "argus.chat.threads.v1";
const MAX_THREADS = 20;
const TITLE_CHARS = 60;

/** The thread's name in the list: its first question, cut at a word. */
export function threadTitle(question: string): string {
  const q = question.trim().replace(/\s+/g, " ");
  if (q.length <= TITLE_CHARS) return q;
  const cut = q.slice(0, TITLE_CHARS);
  const space = cut.lastIndexOf(" ");
  return `${(space > 30 ? cut.slice(0, space) : cut).replace(/[\s,.;:]+$/, "")}…`;
}

function storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

function validTurn(t: unknown): t is ChatTurn {
  const turn = t as ChatTurn;
  return Boolean(turn) && typeof turn.id === "number" && typeof turn.question === "string";
}

/** Saved threads, newest first; a broken or foreign value reads as none. */
export function loadThreads(scope: string): ChatThread[] {
  const raw = storage()?.getItem(`${KEY}:${scope}`);
  if (!raw) return [];
  try {
    const list = JSON.parse(raw) as ChatThread[];
    if (!Array.isArray(list)) return [];
    return list
      .filter((t) => t && typeof t.id === "string" && Array.isArray(t.turns))
      .map((t) => ({
        ...t,
        // an answer that was on its way when the page closed will not come: show it as stopped
        turns: t.turns.filter(validTurn).map((x) => (x.answer || x.error ? x : { ...x, stopped: true })),
      }))
      .sort((a, b) => b.updatedAt - a.updatedAt);
  } catch {
    return [];
  }
}

export function saveThreads(scope: string, threads: ChatThread[]): void {
  try {
    storage()?.setItem(`${KEY}:${scope}`, JSON.stringify(threads.slice(0, MAX_THREADS)));
  } catch {
    /* full or blocked storage: the thread lives on in memory */
  }
}

/** Put a thread first in the list (new or updated); empty threads are not kept. */
export function upsertThread(threads: ChatThread[], thread: ChatThread): ChatThread[] {
  const rest = threads.filter((t) => t.id !== thread.id);
  if (!thread.turns.length) return rest;
  return [thread, ...rest].slice(0, MAX_THREADS);
}

/** "now", "5m", "3h", "2d": how long ago a thread was last used. */
export function ago(then: number, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - then) / 1000));
  if (s < 60) return "now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

/** "Worked for 4.2s" / "Worked for 1m 12s", like T3 Code's turn separator. */
export function workedFor(ms: number): string {
  const s = Math.max(0, ms) / 1000;
  if (s < 10) return `${s.toFixed(1)}s`;
  if (s < 60) return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s - m * 60)}s`;
}

/**
 * The answer split for the streamed reveal: each word keeps the space before it, so any prefix of the tokens is a
 * valid text and a receipt tag such as "[q1]" is never cut in half.
 */
export function revealTokens(text: string): string[] {
  return text.match(/\s*\S+/g) ?? [];
}

/** The first `count` tokens of the answer, as text. */
export function revealed(tokens: string[], count: number): string {
  return tokens.slice(0, Math.max(0, count)).join("");
}

/** How many tokens appear per frame: short answers stream word by word, long ones finish in about 1.6 s. */
export function revealStep(total: number): number {
  return Math.max(1, Math.ceil(total / 96));
}

/** The composer's model chip: the model the live agent answers with, else its mode. */
export function modelLabel(health: AgentHealth | null): string {
  if (!health) return "Agent offline";
  const models = health.models;
  const name = Array.isArray(models) ? models[0] : models.ask ?? models.chat ?? models.narrator ?? Object.values(models)[0];
  if (typeof name === "string" && name) return name.replace(/^(anthropic|openai)\//, "");
  return health.mode === "replay" ? "Recorded agent" : "Live agent";
}
