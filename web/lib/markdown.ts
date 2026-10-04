/**
 * A deliberately small Markdown reader for model answers. It covers what the
 * answer prompt produces (paragraphs, short headings, lists, fenced code,
 * inline code, bold, italics, links) plus citation markers `[1]`, `[1, 3]`,
 * `[1][2]`. It never produces HTML strings: the renderer turns these nodes
 * into React elements, so model output cannot inject markup.
 *
 * It is safe on partial input: while an answer streams, an unclosed code fence
 * is a code block so far, and an unclosed `**` or backtick stays literal text.
 */

export type Inline =
  | { type: "text"; text: string }
  | { type: "code"; text: string }
  | { type: "strong"; children: Inline[] }
  | { type: "em"; children: Inline[] }
  | { type: "link"; href: string; children: Inline[] }
  | { type: "cite"; ns: number[] };

export type Block =
  | { type: "paragraph"; children: Inline[] }
  | { type: "heading"; level: 3 | 4; children: Inline[] }
  | { type: "list"; ordered: boolean; start: number; items: Inline[][] }
  | { type: "code"; lang: string; text: string; open: boolean };

const FENCE = /^\s{0,3}(```+|~~~+)\s*([\w+-]*)\s*$/;
const HEADING = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const BULLET = /^\s{0,3}[-*+]\s+(.*)$/;
const ORDERED = /^\s{0,3}(\d{1,9})[.)]\s+(.*)$/;

export function parseMarkdown(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let para: string[] = [];

  const flushPara = () => {
    if (para.length > 0) {
      const t = para.join(" ").trim();
      if (t !== "") blocks.push({ type: "paragraph", children: parseInline(t) });
      para = [];
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    const fence = line.match(FENCE);
    if (fence) {
      flushPara();
      const marker = fence[1];
      const body: string[] = [];
      let j = i + 1;
      let closed = false;
      for (; j < lines.length; j++) {
        if (lines[j].trim().startsWith(marker[0].repeat(marker.length)) && lines[j].trim().replace(/[`~]/g, "") === "") {
          closed = true;
          break;
        }
        body.push(lines[j]);
      }
      blocks.push({ type: "code", lang: fence[2] ?? "", text: body.join("\n"), open: !closed });
      i = closed ? j : lines.length;
      continue;
    }

    if (line.trim() === "") {
      flushPara();
      continue;
    }

    const heading = line.match(HEADING);
    if (heading) {
      flushPara();
      // The page owns h1 and h2; answer headings start at h3.
      const level: 3 | 4 = heading[1].length <= 2 ? 3 : 4;
      blocks.push({ type: "heading", level, children: parseInline(heading[2]) });
      continue;
    }

    const bullet = line.match(BULLET);
    const ordered = line.match(ORDERED);
    if (bullet || ordered) {
      flushPara();
      const isOrdered = !bullet;
      const start = ordered ? Number(ordered[1]) : 1;
      const items: string[] = [(bullet ? bullet[1] : ordered![2]) ?? ""];
      let j = i + 1;
      for (; j < lines.length; j++) {
        const l = lines[j];
        const b = l.match(BULLET);
        const o = l.match(ORDERED);
        if (!isOrdered && b) items.push(b[1]);
        else if (isOrdered && o) items.push(o[2]);
        else if (l.trim() !== "" && /^\s{2,}\S/.test(l) && !FENCE.test(l)) items[items.length - 1] += ` ${l.trim()}`;
        else break;
      }
      blocks.push({ type: "list", ordered: isOrdered, start, items: items.map((t) => parseInline(t.trim())) });
      i = j - 1;
      continue;
    }

    para.push(line.trim());
  }
  flushPara();
  return blocks;
}

/** `[1]`, `[1, 2]`, `[1,2,3]` and not `[1](url)` (a link). */
const CITE = /^\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\](?!\()/;
const LINK = /^\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/;

export function parseInline(src: string): Inline[] {
  const out: Inline[] = [];
  let buf = "";
  const pushText = () => {
    if (buf !== "") {
      out.push({ type: "text", text: buf });
      buf = "";
    }
  };

  let i = 0;
  while (i < src.length) {
    const rest = src.slice(i);
    const ch = src[i];

    if (ch === "\\" && i + 1 < src.length && /[\\`*_[\]()#+\-.!]/.test(src[i + 1])) {
      buf += src[i + 1];
      i += 2;
      continue;
    }

    if (ch === "`") {
      const ticks = rest.match(/^`+/)![0];
      const end = src.indexOf(ticks, i + ticks.length);
      if (end !== -1) {
        pushText();
        out.push({ type: "code", text: src.slice(i + ticks.length, end).trim() || src.slice(i + ticks.length, end) });
        i = end + ticks.length;
        continue;
      }
      buf += ticks;
      i += ticks.length;
      continue;
    }

    if (ch === "[") {
      const cite = rest.match(CITE);
      if (cite) {
        pushText();
        const ns = cite[1].split(",").map((s) => Number(s.trim()));
        // Merge `[1][2]` into one group.
        const prev = out[out.length - 1];
        if (prev && prev.type === "cite") prev.ns.push(...ns);
        else out.push({ type: "cite", ns });
        i += cite[0].length;
        continue;
      }
      const link = rest.match(LINK);
      if (link) {
        pushText();
        out.push({ type: "link", href: link[2], children: parseInline(link[1]) });
        i += link[0].length;
        continue;
      }
    }

    if ((ch === "*" || ch === "_") && rest.startsWith(ch.repeat(2))) {
      const marker = ch.repeat(2);
      const end = src.indexOf(marker, i + 2);
      if (end > i + 2) {
        pushText();
        out.push({ type: "strong", children: parseInline(src.slice(i + 2, end)) });
        i = end + 2;
        continue;
      }
    } else if (ch === "*" || (ch === "_" && (i === 0 || /\W/.test(src[i - 1])))) {
      const end = src.indexOf(ch, i + 1);
      if (end > i + 1 && src[i + 1] !== " " && src[end - 1] !== " " && (ch === "*" || end + 1 >= src.length || /\W/.test(src[end + 1]))) {
        pushText();
        out.push({ type: "em", children: parseInline(src.slice(i + 1, end)) });
        i = end + 1;
        continue;
      }
    }

    buf += ch;
    i += 1;
  }
  pushText();
  return out;
}

/** Every citation number in the answer, in order of first appearance. */
export function citedNumbers(src: string): number[] {
  const seen = new Set<number>();
  const visit = (nodes: Inline[]) => {
    for (const n of nodes) {
      if (n.type === "cite") n.ns.forEach((x) => seen.add(x));
      else if (n.type === "strong" || n.type === "em" || n.type === "link") visit(n.children);
    }
  };
  for (const b of parseMarkdown(src)) {
    if (b.type === "paragraph" || b.type === "heading") visit(b.children);
    else if (b.type === "list") b.items.forEach(visit);
  }
  return [...seen];
}

/** The answer as plain text without citation markers (for the thread sent back to the API). */
export function stripCitations(src: string): string {
  return src
    .replace(/\s?\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\](?!\()/g, "")
    .replace(/[ \t]+\n/g, "\n")
    .trim();
}
