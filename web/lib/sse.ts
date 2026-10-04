/**
 * A small Server-Sent Events parser for streams read with fetch + ReadableStream.
 * `/api/ask` is a POST, so EventSource (GET only) cannot be used.
 *
 * Follows the WHATWG event-stream rules that matter here: messages end at a
 * blank line; `data:` lines are joined with "\n"; one optional space after the
 * colon is dropped; lines starting with ":" are comments (keep-alives); CRLF,
 * CR and LF all end a line; a chunk may split a line or a CRLF pair anywhere.
 */

export type SseMessage = {
  /** The `event:` field, when the server set one. */
  event?: string;
  /** The `id:` field, when the server set one. */
  id?: string;
  data: string;
};

export class SseParser {
  private buffer = "";
  private dataLines: string[] = [];
  private event: string | undefined;
  private id: string | undefined;
  private sawField = false;

  /** Feed decoded text; returns the messages completed by it. */
  push(text: string): SseMessage[] {
    this.buffer += text;
    const out: SseMessage[] = [];
    for (;;) {
      const m = this.buffer.match(/\r\n|\r|\n/);
      if (!m || m.index === undefined) break;
      // A lone CR at the very end may be the first half of a CRLF split across chunks.
      if (m[0] === "\r" && m.index === this.buffer.length - 1) break;
      const line = this.buffer.slice(0, m.index);
      this.buffer = this.buffer.slice(m.index + m[0].length);
      const msg = this.line(line);
      if (msg) out.push(msg);
    }
    return out;
  }

  /** End of stream: a final message without a trailing blank line still counts. */
  flush(): SseMessage[] {
    const out: SseMessage[] = [];
    if (this.buffer !== "") {
      const msg = this.line(this.buffer);
      this.buffer = "";
      if (msg) out.push(msg);
    }
    const last = this.dispatch();
    if (last) out.push(last);
    return out;
  }

  private line(line: string): SseMessage | null {
    if (line === "") return this.dispatch();
    if (line.startsWith(":")) return null;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    switch (field) {
      case "data":
        this.dataLines.push(value);
        this.sawField = true;
        break;
      case "event":
        this.event = value;
        this.sawField = true;
        break;
      case "id":
        if (!value.includes("\0")) this.id = value;
        this.sawField = true;
        break;
      default:
        // `retry:` and unknown fields are ignored.
        break;
    }
    return null;
  }

  private dispatch(): SseMessage | null {
    if (!this.sawField || this.dataLines.length === 0) {
      this.reset();
      return null;
    }
    const msg: SseMessage = { data: this.dataLines.join("\n") };
    if (this.event) msg.event = this.event;
    if (this.id !== undefined) msg.id = this.id;
    this.reset();
    return msg;
  }

  private reset() {
    this.dataLines = [];
    this.event = undefined;
    this.sawField = false;
    // The last event id persists across messages per the spec, but each message reports its own.
    this.id = undefined;
  }
}

/** Read a byte stream to the end, yielding SSE messages as they complete. */
export async function* readSse(body: ReadableStream<Uint8Array>, signal?: AbortSignal): AsyncGenerator<SseMessage> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      if (signal?.aborted) return;
      const { value, done } = await reader.read();
      if (done) break;
      for (const msg of parser.push(decoder.decode(value, { stream: true }))) yield msg;
    }
    for (const msg of parser.push(decoder.decode())) yield msg;
    for (const msg of parser.flush()) yield msg;
  } finally {
    try {
      await reader.cancel();
    } catch {
      // already closed
    }
    reader.releaseLock();
  }
}
