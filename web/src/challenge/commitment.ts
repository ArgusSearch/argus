// The blind challenge's commitment, recomputed in the browser exactly as src/bench/sealed.py writes it:
// "sha256:" + hex(SHA-256(nonce + "\n" + payload)) over the UTF-8 string.

import { sha256Hex, toHex } from "./sha256";

export type HashEngine = "webcrypto" | "built-in";

export interface Check {
  /** The commitment the browser computed from the nonce and the payload. */
  computed: string;
  /** Whether it equals the published commitment. */
  matches: boolean;
  /** WebCrypto in a secure context, the built-in FIPS 180-4 code otherwise (a phone on http://192.168.x.x). */
  engine: HashEngine;
}

/** Accept the commitment with or without its "sha256:" prefix, any case, stray spaces from a paste. */
export function normalizeCommitment(text: string): string {
  const hex = text.trim().toLowerCase().replace(/^sha256:/, "").replace(/\s+/g, "");
  return `sha256:${hex}`;
}

export function isCommitment(text: string): boolean {
  return /^sha256:[0-9a-f]{64}$/.test(normalizeCommitment(text));
}

/** The commitment of a nonce and payload with the built-in SHA-256 (synchronous, works everywhere). */
export function commitmentOf(nonce: string, payload: string): string {
  return `sha256:${sha256Hex(`${nonce}\n${payload}`)}`;
}

function subtle(): SubtleCrypto | null {
  const c = (globalThis as { crypto?: Crypto }).crypto;
  const secure = (globalThis as { isSecureContext?: boolean }).isSecureContext;
  return c?.subtle && secure !== false ? c.subtle : null;
}

/** The commitment with WebCrypto when the page may use it, the built-in code otherwise. */
export async function computeCommitment(nonce: string, payload: string): Promise<{ commitment: string; engine: HashEngine }> {
  const s = subtle();
  if (s) {
    try {
      const digest = await s.digest("SHA-256", new TextEncoder().encode(`${nonce}\n${payload}`));
      return { commitment: `sha256:${toHex(new Uint8Array(digest))}`, engine: "webcrypto" };
    } catch {
      /* fall through to the built-in code */
    }
  }
  return { commitment: commitmentOf(nonce, payload), engine: "built-in" };
}

export async function verifyCommitment(commitment: string, nonce: string, payload: string): Promise<Check> {
  const { commitment: computed, engine } = await computeCommitment(nonce, payload);
  return { computed, matches: computed === normalizeCommitment(commitment), engine };
}

/** Change one character of the payload (for the "tamper" demo): the hash must stop matching. */
export function tamper(payload: string): string {
  const i = payload.search(/[0-9]/);
  if (i < 0) return payload.length ? `${payload.slice(0, -1)}${payload.endsWith("x") ? "y" : "x"}` : "x";
  const digit = Number(payload[i]);
  return `${payload.slice(0, i)}${(digit + 1) % 10}${payload.slice(i + 1)}`;
}
