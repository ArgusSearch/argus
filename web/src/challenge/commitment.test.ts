import { describe, expect, it } from "vitest";
import { commitmentOf, computeCommitment, isCommitment, normalizeCommitment, tamper, verifyCommitment } from "./commitment";
import { compareRows, parseChallenge, passed, truthOf, verdictLabel } from "./model";
import { recordedChallenge } from "./sample";
import { sha256, sha256Hex, toHex } from "./sha256";

// Known answers: FIPS 180-4 examples (NIST CSRC "SHA256.pdf" / "SHA2_Additional.pdf").
describe("sha256 (FIPS 180-4)", () => {
  it("hashes the empty string", () => {
    expect(sha256Hex("")).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  });

  it('hashes "abc" (one block)', () => {
    expect(sha256Hex("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });

  it("hashes the 448-bit message (two blocks)", () => {
    expect(sha256Hex("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq")).toBe(
      "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
    );
  });

  it("hashes the 896-bit message", () => {
    expect(
      sha256Hex("abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmnhijklmnoijklmnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu"),
    ).toBe("cf5b16a778af8380036ce59e7b0492370b249b11e8f07a51afac45037afee9d1");
  });

  it("hashes one million 'a'", () => {
    expect(toHex(sha256(new Uint8Array(1_000_000).fill(0x61)))).toBe(
      "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0",
    );
  });

  it("pads correctly at the 55, 56 and 64 byte block edges", async () => {
    for (const n of [55, 56, 63, 64, 65, 119, 120]) {
      const bytes = new Uint8Array(n).fill(0x5a);
      const expected = toHex(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)));
      expect(toHex(sha256(bytes)), `length ${n}`).toBe(expected);
    }
  });

  it("hashes multi-byte UTF-8 like WebCrypto", async () => {
    const text = "Größe · 東京 · €75,556 · 🙂";
    const expected = toHex(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text))));
    expect(sha256Hex(text)).toBe(expected);
  });
});

describe("blind challenge commitment", () => {
  const rec = recordedChallenge();

  it("recomputes the recorded commitment from the reveal", () => {
    expect(commitmentOf(rec.reveal.nonce, rec.reveal.payload)).toBe(rec.commitment);
    expect(rec.commitment).toBe("sha256:ee519191b65afd00566bdadd4997619933b28cbd58bc531a96634bf0e21a7a12");
  });

  it("matches with WebCrypto and with the built-in code", async () => {
    const web = await verifyCommitment(rec.commitment, rec.reveal.nonce, rec.reveal.payload);
    expect(web).toEqual({ computed: rec.commitment, matches: true, engine: "webcrypto" });
    const subtle = crypto.subtle;
    Object.defineProperty(globalThis.crypto, "subtle", { value: undefined, configurable: true });
    try {
      const builtIn = await verifyCommitment(rec.commitment, rec.reveal.nonce, rec.reveal.payload);
      expect(builtIn).toEqual({ computed: rec.commitment, matches: true, engine: "built-in" });
    } finally {
      Object.defineProperty(globalThis.crypto, "subtle", { value: subtle, configurable: true });
    }
  });

  it("fails when one character of the payload changes", async () => {
    const changed = tamper(rec.reveal.payload);
    expect(changed).not.toBe(rec.reveal.payload);
    expect(changed.length).toBe(rec.reveal.payload.length);
    expect([...changed].filter((c, i) => c !== rec.reveal.payload[i])).toHaveLength(1);
    const check = await verifyCommitment(rec.commitment, rec.reveal.nonce, changed);
    expect(check.matches).toBe(false);
    expect(check.computed).not.toBe(rec.commitment);
  });

  it("fails when one character of the nonce changes", async () => {
    const nonce = `${rec.reveal.nonce.slice(0, -1)}${rec.reveal.nonce.endsWith("0") ? "1" : "0"}`;
    expect((await verifyCommitment(rec.commitment, nonce, rec.reveal.payload)).matches).toBe(false);
  });

  it("accepts a pasted commitment with or without the prefix", async () => {
    const bare = rec.commitment.replace("sha256:", "").toUpperCase();
    expect(normalizeCommitment(`  ${bare} `)).toBe(rec.commitment);
    expect(isCommitment(bare)).toBe(true);
    expect(isCommitment("sha256:1234")).toBe(false);
    expect((await verifyCommitment(bare, rec.reveal.nonce, rec.reveal.payload)).matches).toBe(true);
  });

  it("uses the built-in code outside a secure context", async () => {
    const g = globalThis as { isSecureContext?: boolean };
    const before = g.isSecureContext;
    g.isSecureContext = false;
    try {
      expect((await computeCommitment("n", "p")).engine).toBe("built-in");
    } finally {
      g.isSecureContext = before;
    }
  });
});

describe("challenge model", () => {
  const rec = recordedChallenge();

  it("reads the three recorded states in order", () => {
    expect(rec.states.map((s) => s.state)).toEqual(["committed", "running", "revealed"]);
    expect(new Set(rec.states.map((s) => s.commitment)).size).toBe(1);
    expect(parseChallenge('{"state":"bogus","commitment":"x"}\n\n')).toEqual([]);
  });

  it("parses the hidden truth and lines it up with the grade", () => {
    expect(truthOf(rec.reveal)?.events.map((e) => e.event_id)).toEqual(["s1_payco_outage", "s1_release_red_herring"]);
    expect(truthOf({ ...rec.reveal, payload: "{" })).toBeNull();
    const rows = compareRows(rec.reveal);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ truth: "Supported cause on DE · android · PayCo", argus: "Supported cause (INC-0001)", hit: true, ttd: "2 h" });
  });

  it("grades the recorded run as PASS like the bench", () => {
    expect(passed(rec.reveal.grade)).toBe(true);
    expect(passed({ ...rec.reveal.grade, false_alarms: [{}] })).toBe(false);
    expect(passed({ ...rec.reveal.grade, verified: false })).toBe(false);
  });

  it("labels verdicts for people", () => {
    expect(verdictLabel("DATA_ISSUE")).toBe("Data issue");
    expect(verdictLabel(null)).toBe("no claim");
  });
});
