import { describe, expect, it } from "vitest";
import { parseAskEvent, type AskEvent, type AskInput } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import { answerCitations, answerChunks, answerDone } from "@/lib/mock";
import {
  applyEvent,
  buildThread,
  cutOffTurn,
  failTurn,
  MAX_TURNS,
  newTurn,
  pushTurn,
  stopTurn,
  THREAD_ANSWER_CHARS,
  type Turn,
} from "@/lib/turn";

const input: AskInput = { question: " How? ", sdk: "expo", version: "v58.0.0", mode: "answer", compare_version: "v57.0.0" };
const ev = (o: unknown) => parseAskEvent(JSON.stringify(o)) as AskEvent;

function finished(key: string, question: string, answer: string): Turn {
  let t = newTurn(key, { ...input, question });
  t = applyEvent(t, ev({ kind: "token", text: answer }));
  return applyEvent(t, ev({ kind: "done", question_id: key }));
}

describe("turn lifecycle", () => {
  it("goes retrieving -> answering -> done, folding every event", () => {
    let t = newTurn("k", input);
    expect(t.status).toBe("retrieving");
    expect(t.question).toBe("How?");
    expect(t.compare_version).toBeUndefined();
    t = applyEvent(t, ev({ kind: "retrieval", chunks: answerChunks() }));
    expect(t.status).toBe("answering");
    expect(t.chunks).toHaveLength(5);
    t = applyEvent(t, ev({ kind: "token", text: "Call it " }));
    t = applyEvent(t, ev({ kind: "token", text: "[1]." }));
    expect(t.answer).toBe("Call it [1].");
    t = applyEvent(t, ev({ kind: "citations", ...answerCitations }));
    expect(t.citations?.verified).toHaveLength(3);
    t = applyEvent(t, ev({ kind: "done", ...answerDone }));
    expect(t).toMatchObject({ status: "done", question_id: "demo-notifications", latency_ms: 2840 });
    expect(t.usage?.total_tokens).toBe(4622);
    // Terminal: later events are ignored.
    expect(applyEvent(t, ev({ kind: "token", text: "more" })).answer).toBe("Call it [1].");
  });

  it("records stream errors, request failures, stops and cut-offs", () => {
    const t = newTurn("k", input);
    expect(applyEvent(t, ev({ kind: "error", code: "unavailable", message: "down" })).error).toMatchObject({
      code: "unavailable",
      title: "Service unavailable",
    });
    const failed = failTurn(t, new ApiError({ status: 429, code: "rate_limited", message: "slow", retryAfter: 60 }));
    expect(failed.error).toMatchObject({ code: "rate_limited", hint: "Try again in 60 seconds." });
    expect(stopTurn(t).status).toBe("stopped");
    expect(cutOffTurn(t).error?.code).toBe("stream");
    expect(cutOffTurn(stopTurn(t)).status).toBe("stopped");
  });

  it("keeps diff mode's compare version and the diff event", () => {
    let t = newTurn("d", { ...input, mode: "diff" });
    expect(t.compare_version).toBe("v57.0.0");
    t = applyEvent(t, ev({ kind: "diff", diff: { summary: "s", changes: [{ kind: "added", after: "x", citations: [1] }] } }));
    expect(t.diff?.changes[0].kind).toBe("added");
  });
});

describe("thread", () => {
  it("keeps the newest MAX_TURNS turns", () => {
    let turns: Turn[] = [];
    for (let i = 0; i < MAX_TURNS + 2; i++) turns = pushTurn(turns, finished(`k${i}`, `q${i}`, `a${i}`));
    expect(turns).toHaveLength(MAX_TURNS);
    expect(turns[0].key).toBe(`k${MAX_TURNS + 1}`);
  });

  it("builds chronological user/assistant pairs from finished turns only, stripped and trimmed", () => {
    const long = "x".repeat(THREAD_ANSWER_CHARS + 50);
    const turns = [finished("b", "second", `B [2]`), newTurn("pending", input), finished("a", "first", long)];
    const thread = buildThread(turns);
    expect(thread.map((m) => m.role)).toEqual(["user", "assistant", "user", "assistant"]);
    expect(thread[0].content).toBe("first");
    expect(thread[1].content.length).toBe(THREAD_ANSWER_CHARS);
    expect(thread[3].content).toBe("B");
  });
});
