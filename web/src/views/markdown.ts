// A tiny Markdown reader for the subset the narrator's incident report uses (src/argus/narrator):
// `#`/`##`/`###` headings, paragraphs, `-` and `1.` lists, pipe tables, `inline code`, **bold** and receipt
// references like [r225]. Pure: text in, blocks out; the view renders them. No HTML is ever produced from
// the input, so nothing in a report can inject markup.

export type Inline = { t: "text"; v: string } | { t: "code"; v: string } | { t: "bold"; v: string } | { t: "receipt"; v: string };

export type Block =
  | { t: "h"; level: 1 | 2 | 3; inline: Inline[] }
  | { t: "p"; inline: Inline[] }
  | { t: "ul"; items: Inline[][] }
  | { t: "ol"; items: Inline[][] }
  | { t: "table"; head: Inline[][]; rows: Inline[][][] };

const TOKEN = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[r\d+\])/g;

export function inline(text: string): Inline[] {
  const out: Inline[] = [];
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    const at = m.index ?? 0;
    if (at > last) out.push({ t: "text", v: text.slice(last, at) });
    const [token] = m;
    if (m[1]) out.push({ t: "code", v: token.slice(1, -1) });
    else if (m[2]) out.push({ t: "bold", v: token.slice(2, -2) });
    else out.push({ t: "receipt", v: token.slice(1, -1) });
    last = at + token.length;
  }
  if (last < text.length) out.push({ t: "text", v: text.slice(last) });
  return out;
}

const cells = (line: string) =>
  line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());

const isRule = (line: string) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(line);

export function parseMarkdown(md: string): Block[] {
  const lines = md.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) blocks.push({ t: "p", inline: inline(para.join(" ")) });
    para = [];
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) {
      flush();
      continue;
    }
    const heading = /^(#{1,3})\s+(.*)$/.exec(trimmed);
    if (heading) {
      flush();
      blocks.push({ t: "h", level: heading[1].length as 1 | 2 | 3, inline: inline(heading[2]) });
      continue;
    }
    if (trimmed.startsWith("|") && i + 1 < lines.length && isRule(lines[i + 1])) {
      flush();
      const head = cells(trimmed).map(inline);
      const rows: Inline[][][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(cells(lines[i++]).map(inline));
      i--;
      blocks.push({ t: "table", head, rows });
      continue;
    }
    const bullet = /^[-*]\s+(.*)$/.exec(trimmed);
    const numbered = /^\d+[.)]\s+(.*)$/.exec(trimmed);
    if (bullet || numbered) {
      flush();
      const kind = bullet ? "ul" : "ol";
      const items: Inline[][] = [];
      const pattern = bullet ? /^[-*]\s+(.*)$/ : /^\d+[.)]\s+(.*)$/;
      while (i < lines.length) {
        const m = pattern.exec(lines[i].trim());
        if (!m) break;
        items.push(inline(m[1]));
        i++;
      }
      i--;
      blocks.push(kind === "ul" ? { t: "ul", items } : { t: "ol", items });
      continue;
    }
    para.push(trimmed);
  }
  flush();
  return blocks;
}
