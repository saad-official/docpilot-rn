import { describe, expect, it } from "vitest";
import { askBody, parseAskEvent, StoredQuestionSchema, VersionsSchema } from "@/lib/api";
import { storedQuestions, versionsFixture } from "@/lib/mock";

describe("VersionsSchema", () => {
  it("drops unversioned and sorts newest first", () => {
    const v = VersionsSchema.parse({
      sources: [{ name: "expo", versions: [{ version: "v57.0.0" }, { version: "unversioned" }, { version: "v58.0.0", chunk_count: "10" }] }],
    });
    expect(v.sources[0].versions.map((x) => x.version)).toEqual(["v58.0.0", "v57.0.0"]);
    expect(v.sources[0].versions[0].chunk_count).toBe(10);
  });

  it("tolerates versions as plain strings, missing fields and junk entries", () => {
    const v = VersionsSchema.parse({ sources: [{ name: "react-native", versions: ["current", 42, null] }, { nope: true }] });
    expect(v.sources).toHaveLength(1);
    expect(v.sources[0].versions).toEqual([{ version: "current", chunk_count: undefined, ingested_at: undefined, commit_sha: undefined }]);
    expect(v.sources[0].embedding_model).toBeUndefined();
  });

  it("accepts the mock fixture", () => {
    expect(VersionsSchema.safeParse(versionsFixture).success).toBe(true);
  });
});

describe("parseAskEvent", () => {
  it("parses retrieval chunks, joining array heading paths and sorting by n", () => {
    const ev = parseAskEvent(
      JSON.stringify({
        kind: "retrieval",
        chunks: [
          { id: "b", n: 2, title: "B", heading_path: ["Guides", "Push"], url: "u2", version: "v58.0.0", score: 0.5, snippet: "s" },
          { id: 9, n: "1", url: "u1", version: "v58.0.0", snippet: "t", heading_path: "A › Setup" },
          { n: 0, title: "invalid n" },
        ],
      }),
    );
    expect(ev?.kind).toBe("retrieval");
    if (ev?.kind !== "retrieval") return;
    expect(ev.chunks.map((c) => c.n)).toEqual([1, 2]);
    expect(ev.chunks[0]).toMatchObject({ id: "9", title: "Setup", heading_path: "A › Setup" });
    expect(ev.chunks[1].heading_path).toBe("Guides › Push");
  });

  it("parses tokens, citations, diff, done and error", () => {
    expect(parseAskEvent('{"kind":"token","text":"Hi"}')).toEqual({ kind: "token", text: "Hi" });
    const c = parseAskEvent('{"kind":"citations","verified":[{"n":1,"chunk_id":"x"}],"removed":[{"n":7}],"unsupported":null}');
    expect(c).toMatchObject({ kind: "citations", citations: { verified: [{ n: 1, chunk_id: "x" }], removed: [{ n: 7 }], unsupported: false } });
    const d = parseAskEvent('{"kind":"diff","diff":{"summary":"s","changes":[{"kind":"behavior","after":"x","citations":[1,"2","x"]}]}}');
    expect(d).toMatchObject({ kind: "diff", diff: { changes: [{ kind: "behaviour", citations: [1, 2] }] } });
    const done = parseAskEvent('{"kind":"done","question_id":12,"latency_ms":"900"}');
    expect(done).toMatchObject({ kind: "done", done: { question_id: "12", latency_ms: 900, usage: { usd: 0, total_tokens: 0 } } });
    expect(parseAskEvent('{"kind":"error","code":"unavailable","message":"down"}')).toEqual({ kind: "error", code: "unavailable", message: "down" });
  });

  it("uses the SSE event name when the payload has no kind, and ignores junk", () => {
    expect(parseAskEvent('{"text":"x"}', "token")).toEqual({ kind: "token", text: "x" });
    expect(parseAskEvent("not json")).toBeNull();
    expect(parseAskEvent("[DONE]")).toBeNull();
    expect(parseAskEvent('{"kind":"mystery"}')).toBeNull();
    expect(parseAskEvent('{"kind":"token","text":""}')).toBeNull();
  });
});

describe("StoredQuestionSchema", () => {
  it("parses both stored fixtures", () => {
    const a = StoredQuestionSchema.parse(storedQuestions["demo-notifications"]);
    expect(a.mode).toBe("answer");
    expect(a.chunks).toHaveLength(5);
    expect(a.citations?.removed[0].n).toBe(7);
    const d = StoredQuestionSchema.parse(storedQuestions["demo-diff"]);
    expect(d.mode).toBe("diff");
    expect(d.diff?.changes).toHaveLength(3);
    expect(d.feedback).toBe("up");
  });

  it("finds chunks under retrieval.chunks and merges verification", () => {
    const q = StoredQuestionSchema.parse({
      id: 5,
      question: "q",
      version: "v58.0.0",
      answer: "a [1]",
      retrieval: { chunks: [{ n: 1, id: "c1", url: "u", snippet: "s" }], fused: [] },
      citations: [{ n: 1, chunk_id: "c1" }],
      verification: { removed: [{ n: 2, reason: "r" }], unsupported: false },
    });
    expect(q.id).toBe("5");
    expect(q.sdk).toBe("expo");
    expect(q.chunks[0].id).toBe("c1");
    expect(q.citations?.verified).toHaveLength(1);
    expect(q.citations?.removed).toEqual([{ n: 2, reason: "r" }]);
  });
});

describe("askBody", () => {
  it("drops compare_version outside diff mode and empty threads", () => {
    expect(askBody({ question: "  q  ", sdk: "expo", version: "v58.0.0", mode: "answer", compare_version: "v57.0.0", thread: [] })).toEqual({
      question: "q",
      sdk: "expo",
      version: "v58.0.0",
      mode: "answer",
    });
    expect(askBody({ question: "q", sdk: "expo", version: "v58.0.0", mode: "diff", compare_version: "v57.0.0" }).compare_version).toBe("v57.0.0");
  });
});
