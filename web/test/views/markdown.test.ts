// The tiny Markdown reader against the narrator's real report (fixtures/report.md).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { inline, parseMarkdown } from "../../src/views/markdown";

const report = readFileSync(fileURLToPath(new URL("../../../fixtures/report.md", import.meta.url)), "utf8");

describe("parseMarkdown", () => {
  const blocks = parseMarkdown(report);

  it("reads the report's structure", () => {
    expect(blocks[0]).toMatchObject({ t: "h", level: 1 });
    const h2 = blocks.filter((b) => b.t === "h" && b.level === 2).map((b) => (b.t === "h" ? b.inline.map((i) => i.v).join("") : ""));
    expect(h2).toContain("What happened");
    expect(h2).toContain("Ruled out");
    expect(h2).toContain("Investigation trail");
    expect(blocks.some((b) => b.t === "table")).toBe(true);
    expect(blocks.some((b) => b.t === "ol")).toBe(true);
    expect(blocks.some((b) => b.t === "ul")).toBe(true);
  });

  it("reads the LMDI table with its receipts", () => {
    const table = blocks.find((b) => b.t === "table");
    if (!table || table.t !== "table") throw new Error("no table");
    expect(table.head.map((c) => c.map((i) => i.v).join(""))).toEqual(["factor", "share of the change"]);
    expect(table.rows.length).toBeGreaterThan(3);
    // every share in the table comes with the receipt of the query behind it
    const withReceipt = table.rows.filter((row) => row.flat().some((i) => i.t === "receipt"));
    expect(withReceipt.length).toBe(table.rows.length);
  });

  it("turns every [rNNN] into a receipt and keeps every other character", () => {
    const refs = report.match(/\[r\d+\]/g) ?? [];
    const found = blocks.flatMap((b) =>
      b.t === "table" ? [...b.head, ...b.rows.flat()].flat() : b.t === "ul" || b.t === "ol" ? b.items.flat() : b.inline,
    );
    expect(found.filter((i) => i.t === "receipt")).toHaveLength(refs.length);
  });

  it("reads inline code, bold and receipts, and never produces markup", () => {
    expect(inline("see `ps_payco_degraded` **now** [r9] <b>x</b>")).toEqual([
      { t: "text", v: "see " },
      { t: "code", v: "ps_payco_degraded" },
      { t: "text", v: " " },
      { t: "bold", v: "now" },
      { t: "text", v: " " },
      { t: "receipt", v: "r9" },
      { t: "text", v: " <b>x</b>" },
    ]);
  });

  it("joins wrapped lines into one paragraph and handles CRLF", () => {
    expect(parseMarkdown("one\r\ntwo\r\n\r\nthree")).toEqual([
      { t: "p", inline: [{ t: "text", v: "one two" }] },
      { t: "p", inline: [{ t: "text", v: "three" }] },
    ]);
  });
});
