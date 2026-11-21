// The recorded blind challenge (seed 11), used until POST /challenge/commit and /challenge/reveal answer.
// Recorded with `uv run argus-bench blind --seed 11` on the local integration branch; files copied verbatim
// except blind-11.argus.json, which keeps only the fields the reveal screen shows of agents/argus/incidents.json.

import argusRaw from "./fixtures/blind-11.argus.json?raw";
import jsonl from "./fixtures/blind-11.challenge.jsonl?raw";
import sealedRaw from "./fixtures/blind-11.commitment.json?raw";
import { parseChallenge, type ArgusClaim, type ChallengeState, type Reveal } from "./model";

export interface Recorded {
  states: ChallengeState[];
  commitment: string;
  reveal: Reveal;
  claims: ArgusClaim[];
  sealedAt: string;
  command: string;
}

export function recordedChallenge(): Recorded {
  const states = parseChallenge(jsonl);
  const revealed = states.find((s) => s.state === "revealed");
  if (!revealed?.reveal) throw new Error("the recorded challenge has no reveal");
  return {
    states,
    commitment: revealed.commitment,
    reveal: revealed.reveal,
    claims: (JSON.parse(argusRaw) as { incidents: ArgusClaim[] }).incidents,
    sealedAt: (JSON.parse(sealedRaw) as { sealed_at: string }).sealed_at,
    command: `uv run argus-bench blind --seed ${revealed.reveal.seed}`,
  };
}
