import { describe, expect, it } from "vitest";
import { readSse, SseParser } from "@/lib/sse";

describe("SseParser", () => {
  it("parses id and data lines into messages at blank lines", () => {
    const p = new SseParser();
    const out = p.push('id: 1\ndata: {"kind":"token","text":"a"}\n\nid: 2\ndata: {"kind":"token","text":"b"}\n\n');
    expect(out).toEqual([
      { id: "1", data: '{"kind":"token","text":"a"}' },
      { id: "2", data: '{"kind":"token","text":"b"}' },
    ]);
  });

  it("handles chunks that split lines and CRLF pairs anywhere", () => {
    const p = new SseParser();
    const whole = 'id: 7\r\ndata: {"kind":"done"}\r\n\r\n';
    const msgs = [];
    for (const ch of whole) msgs.push(...p.push(ch));
    expect(msgs).toEqual([{ id: "7", data: '{"kind":"done"}' }]);
  });

  it("joins multi-line data, ignores comments and keeps the event name", () => {
    const p = new SseParser();
    const out = p.push(": keep-alive\n\nevent: citations\ndata: line1\ndata:line2\n\n");
    expect(out).toEqual([{ event: "citations", data: "line1\nline2" }]);
  });

  it("flushes a final message without a trailing blank line", () => {
    const p = new SseParser();
    expect(p.push("data: last")).toEqual([]);
    expect(p.flush()).toEqual([{ data: "last" }]);
  });
});

describe("readSse", () => {
  it("reads a byte stream with multi-byte characters split across chunks", async () => {
    const bytes = new TextEncoder().encode('data: {"text":"Notifications › API"}\n\n');
    const cut = bytes.indexOf(0xe2) + 1; // split inside the UTF-8 sequence of ›
    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(bytes.slice(0, cut));
        c.enqueue(bytes.slice(cut));
        c.close();
      },
    });
    const got = [];
    for await (const m of readSse(stream)) got.push(m);
    expect(got).toEqual([{ data: '{"text":"Notifications › API"}' }]);
  });
});
