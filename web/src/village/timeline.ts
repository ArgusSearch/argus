// Pure: beats on a clock. The timeline gives every beat a start and a length in seconds (at speed 1); a case
// that changes hands spends the first part of its beat in flight from the old igloo to the new one.
// `villageAt(timeline, t)` is the whole village at time t: every role's bubble, status and log, every case orb.

import type { Beat, LogEntry, Outcome } from "./beats";
import { ROLE_IDS, type RoleId } from "./roles";

/** Seconds per unit of beat weight at speed 1. */
export const PACE = 2.4;
/** Seconds a case orb spends travelling between two igloos. */
export const TRAVEL = 1.25;

export interface Slot {
  beat: Beat;
  start: number;
  length: number;
  /** the role the beat's case comes from, when it changes hands at this beat */
  from: RoleId | null;
}

export interface Timeline {
  slots: Slot[];
  total: number;
  /** true when the last beat asks for an approval nobody gave yet: the clock stops at `total` */
  waiting: boolean;
}

export function timeline(beats: Beat[], pace = PACE): Timeline {
  const slots: Slot[] = [];
  const holder = new Map<string, RoleId>();
  let t = 0;
  for (const beat of beats) {
    let from: RoleId | null = null;
    if (beat.caseId) {
      const prev = holder.get(beat.caseId);
      if (prev && prev !== beat.role) from = prev;
      holder.set(beat.caseId, beat.role);
    }
    const length = beat.weight * pace + (from ? TRAVEL : 0);
    slots.push({ beat, start: t, length, from });
    t += length;
  }
  const last = beats[beats.length - 1];
  return { slots, total: t, waiting: Boolean(last?.gate) };
}

/** The index of the slot playing at time t (the last one once the timeline is over), or -1 before the first. */
export function slotAt(tl: Timeline, t: number): number {
  if (!tl.slots.length || t < 0) return -1;
  let lo = 0;
  let hi = tl.slots.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (tl.slots[mid].start <= t) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

export type RoleStatus = "idle" | "working" | "waiting" | "done";

export interface RoleState {
  status: RoleStatus;
  bubble: string;
  outcome: Outcome | null;
  /** the role's tool log, oldest first */
  log: LogEntry[];
  /** beats this role played so far */
  beats: number;
  /** the case the role holds right now */
  caseId: string | null;
}

export interface OrbState {
  caseId: string;
  /** where the orb is: at `at`, or in flight from `from` to `at` with `progress` in 0..1 */
  at: RoleId;
  from: RoleId | null;
  progress: number;
  /** the case waits at the approval post */
  waiting: boolean;
  /** the case is closed or handed back to the watcher for good */
  settled: boolean;
  outcome: Outcome;
}

export interface VillageState {
  index: number;
  beat: Beat | null;
  /** 0..1 inside the current beat */
  beatProgress: number;
  roles: Record<RoleId, RoleState>;
  orbs: OrbState[];
  /** the approval the village waits for, if the clock stands at a gate */
  gate: Beat["gate"];
  simTs: string | null;
  /** the role the camera should favor */
  focus: RoleId | null;
  finished: boolean;
}

const idleRoles = (idle: Record<RoleId, string>): Record<RoleId, RoleState> =>
  Object.fromEntries(ROLE_IDS.map((id) => [id, { status: "idle", bubble: idle[id], outcome: null, log: [], beats: 0, caseId: null }])) as unknown as Record<RoleId, RoleState>;

/**
 * The village at time t. `idle` holds the bubble each role shows before it did anything. A role works while
 * its beat plays, keeps its last result as "done" afterwards, and the Operator "waits" at an open gate.
 */
export function villageAt(tl: Timeline, t: number, idle: Record<RoleId, string>): VillageState {
  const roles = idleRoles(idle);
  const index = slotAt(tl, t);
  const orbs = new Map<string, OrbState>();
  let simTs: string | null = null;
  for (let i = 0; i <= index; i++) {
    const { beat, start, length, from } = tl.slots[i];
    const current = i === index;
    const r = roles[beat.role];
    r.log = r.log.concat(beat.log);
    r.beats += 1;
    r.outcome = beat.outcome;
    r.status = current ? "working" : "done";
    r.bubble = current ? beat.doing : beat.done;
    simTs = beat.simTs;
    if (beat.caseId) {
      const local = Math.max(0, t - start);
      const progress = current && from ? Math.min(1, local / TRAVEL) : 1;
      for (const other of ROLE_IDS) if (roles[other].caseId === beat.caseId) roles[other].caseId = null;
      r.caseId = beat.caseId;
      orbs.set(beat.caseId, {
        caseId: beat.caseId,
        at: beat.role,
        from: current && progress < 1 ? from : null,
        progress,
        waiting: Boolean(beat.gate),
        settled: beat.kind === "lifecycle" && beat.done.endsWith("closed"),
        outcome: beat.outcome,
      });
      // a case waits at the Operator only while nobody decided; once in flight the bubble says "receiving"
      if (current && from && progress < 1) r.bubble = `Receiving ${beat.caseId}…`;
    }
    if (current) {
      const atEnd = t >= start + length;
      if (beat.gate && atEnd && tl.waiting && i === tl.slots.length - 1) r.status = "waiting";
      else if (atEnd && i === tl.slots.length - 1) {
        r.status = "done";
        r.bubble = beat.done;
      }
    }
  }
  const slot = index >= 0 ? tl.slots[index] : null;
  const atGate = Boolean(slot?.beat.gate && tl.waiting && index === tl.slots.length - 1 && t >= slot.start + slot.length * 0.6);
  return {
    index,
    beat: slot?.beat ?? null,
    beatProgress: slot ? Math.min(1, Math.max(0, (t - slot.start) / slot.length)) : 0,
    roles,
    orbs: [...orbs.values()],
    gate: atGate ? (slot?.beat.gate ?? null) : null,
    simTs,
    focus: slot?.beat.role ?? null,
    finished: !tl.waiting && t >= tl.total,
  };
}

/** The idle bubbles, from the role table. */
export function idleBubbles(roles: readonly { id: RoleId; idle: string }[]): Record<RoleId, string> {
  return Object.fromEntries(roles.map((r) => [r.id, r.idle])) as Record<RoleId, string>;
}
