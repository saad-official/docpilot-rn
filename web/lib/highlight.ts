/**
 * Find a quoted passage inside a chunk snippet so the source panel can mark
 * it. The verifier compares normalised text (spec §4), so this does too:
 * case, runs of whitespace, curly quotes and dashes are ignored. Positions map
 * back to the original snippet so the marked text is exactly what the docs say.
 */

export type Segment = { text: string; mark: boolean };

function normChar(c: string): string {
  switch (c) {
    case "‘":
    case "’":
      return "'";
    case "“":
    case "”":
      return '"';
    case "–":
    case "—":
      return "-";
    default:
      return c.toLowerCase();
  }
}

/** Normalised text plus, for each normalised character, its index in the original. */
function normalise(s: string): { text: string; map: number[] } {
  let text = "";
  const map: number[] = [];
  let lastSpace = true;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (/\s/.test(c)) {
      if (!lastSpace) {
        text += " ";
        map.push(i);
        lastSpace = true;
      }
      continue;
    }
    text += normChar(c);
    map.push(i);
    lastSpace = false;
  }
  if (text.endsWith(" ")) {
    text = text.slice(0, -1);
    map.pop();
  }
  return { text, map };
}

/** Strip wrapping quotes and ellipses a model may add around a quote. */
function cleanQuote(q: string): string {
  return q
    .trim()
    .replace(/^["'“‘]+|["'”’]+$/g, "")
    .replace(/^(\.\.\.|…)\s*|\s*(\.\.\.|…)$/g, "")
    .trim();
}

/** Split `snippet` around the first occurrence of `quote`. One segment, unmarked, when not found. */
export function splitOnQuote(snippet: string, quote: string | undefined): Segment[] {
  if (!quote) return [{ text: snippet, mark: false }];
  const q = normalise(cleanQuote(quote)).text;
  if (q.length < 3) return [{ text: snippet, mark: false }];
  const s = normalise(snippet);
  const at = s.text.indexOf(q);
  if (at === -1) return [{ text: snippet, mark: false }];
  const start = s.map[at];
  const end = s.map[at + q.length - 1] + 1;
  const out: Segment[] = [];
  if (start > 0) out.push({ text: snippet.slice(0, start), mark: false });
  out.push({ text: snippet.slice(start, end), mark: true });
  if (end < snippet.length) out.push({ text: snippet.slice(end), mark: false });
  return out;
}
