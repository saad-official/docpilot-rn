import type { AskEvent, AskInput, Citations, Diff, Mode, RetrievedChunk, StoredQuestion, ThreadMessage, Usage } from "./api";
import { ApiError, errorTitle, retryHint, streamError, type ApiErrorCode } from "./errors";
import { stripCitations } from "./markdown";

/**
 * One question and its answer, as the ask page builds it from stream events.
 * Pure functions only, so the whole stream lifecycle is unit-tested.
 */

export type TurnStatus = "retrieving" | "answering" | "done" | "error" | "stopped";

export type TurnError = { code: ApiErrorCode; title: string; message: string; hint?: string };

/** What the answer document renders: a live turn or a stored question. */
export type AnswerView = {
  question: string;
  sdk: string;
  version: string;
  compare_version?: string;
  mode: Mode;
  status: TurnStatus;
  /** Undefined until the retrieval event arrives (the panel shows skeletons). */
  chunks?: RetrievedChunk[];
  answer: string;
  citations?: Citations;
  diff?: Diff;
  usage?: Usage;
  latency_ms?: number;
  question_id?: string;
  created_at?: string;
  error?: TurnError;
};

export type Turn = AnswerView & { key: string; input: AskInput };

/** Turns kept in the thread, newest first. Older ones are dropped. */
export const MAX_TURNS = 4;
/** Assistant text sent back in `thread` is trimmed: it is only used for query rewriting. */
export const THREAD_ANSWER_CHARS = 1000;

export function newTurn(key: string, input: AskInput): Turn {
  return {
    key,
    input: { ...input, thread: undefined },
    question: input.question.trim(),
    sdk: input.sdk,
    version: input.version,
    compare_version: input.mode === "diff" ? input.compare_version : undefined,
    mode: input.mode,
    status: "retrieving",
    answer: "",
  };
}

export function toTurnError(err: unknown): TurnError {
  const e =
    err instanceof ApiError ? err : new ApiError({ status: 0, code: "unknown", message: "Something went wrong while asking." });
  return { code: e.code, title: errorTitle(e), message: e.message, hint: retryHint(e) };
}

/** Fold one stream event into the turn. Events after a terminal state are ignored. */
export function applyEvent(turn: Turn, ev: AskEvent): Turn {
  if (turn.status === "done" || turn.status === "error" || turn.status === "stopped") return turn;
  switch (ev.kind) {
    case "retrieval":
      return { ...turn, chunks: ev.chunks, status: "answering" };
    case "token":
      return { ...turn, answer: turn.answer + ev.text, chunks: turn.chunks ?? [], status: "answering" };
    case "citations":
      return { ...turn, citations: ev.citations };
    case "diff":
      return { ...turn, diff: ev.diff };
    case "done":
      return {
        ...turn,
        status: "done",
        chunks: turn.chunks ?? [],
        usage: ev.done.usage,
        latency_ms: ev.done.latency_ms,
        question_id: ev.done.question_id,
      };
    case "error":
      return { ...turn, status: "error", error: toTurnError(streamError(ev.code, ev.message)) };
  }
}

export function failTurn(turn: Turn, err: unknown): Turn {
  return { ...turn, status: "error", error: toTurnError(err) };
}

/** The visitor pressed Stop: keep what arrived, mark it incomplete. */
export function stopTurn(turn: Turn): Turn {
  if (turn.status === "done" || turn.status === "error") return turn;
  return { ...turn, status: "stopped" };
}

/** A stream that ended without `done` or `error`. */
export function cutOffTurn(turn: Turn): Turn {
  if (turn.status === "done" || turn.status === "error" || turn.status === "stopped") return turn;
  return failTurn(turn, new ApiError({ status: 0, code: "stream", message: "The stream ended before the answer finished." }));
}

export function pushTurn(turns: Turn[], turn: Turn): Turn[] {
  return [turn, ...turns].slice(0, MAX_TURNS);
}

export function replaceTurn(turns: Turn[], key: string, update: (t: Turn) => Turn): Turn[] {
  return turns.map((t) => (t.key === key ? update(t) : t));
}

/**
 * The `thread` for the next question: the finished turns in chronological
 * order, oldest first, as user/assistant pairs (at most MAX_TURNS pairs).
 * Citation markers are stripped and long answers trimmed.
 */
export function buildThread(turnsNewestFirst: Turn[]): ThreadMessage[] {
  const finished = turnsNewestFirst.filter((t) => t.status === "done" && t.answer.trim() !== "").slice(0, MAX_TURNS);
  const out: ThreadMessage[] = [];
  for (const t of [...finished].reverse()) {
    out.push({ role: "user", content: t.question });
    let a = stripCitations(t.answer);
    if (a.length > THREAD_ANSWER_CHARS) a = `${a.slice(0, THREAD_ANSWER_CHARS - 1).trimEnd()}…`;
    out.push({ role: "assistant", content: a });
  }
  return out;
}

export function storedToView(q: StoredQuestion): AnswerView {
  return {
    question: q.question,
    sdk: q.sdk,
    version: q.version,
    compare_version: q.compare_version,
    mode: q.mode,
    status: "done",
    chunks: q.chunks,
    answer: q.answer,
    citations: q.citations,
    diff: q.diff,
    usage: q.usage,
    latency_ms: q.latency_ms,
    question_id: q.id,
    created_at: q.created_at,
  };
}

/** Citation numbers that the verifier removed: hidden in the prose, struck in the panel. */
export function removedSet(citations: Citations | undefined): Set<number> {
  return new Set((citations?.removed ?? []).map((r) => r.n));
}

/** Whether the answer is still arriving (for the caret and aria-busy). */
export function isStreaming(status: TurnStatus): boolean {
  return status === "retrieving" || status === "answering";
}
