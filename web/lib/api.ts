import { z } from "zod";
import { API_MOCK, API_URL } from "./config";
import { compareVersionsDesc } from "./format";
import { ApiError, networkError, parseApiError } from "./errors";
import { readSse } from "./sse";
import * as mock from "./mock";

/*
  Contract with the FastAPI service (spec §6). Parsing is deliberately
  tolerant: optional fields may be missing or null, numbers may arrive as
  strings, and unknown extra fields are ignored. An event that parses at all
  renders; the UI never crashes on a partial payload.
*/

export const SDKS = ["expo", "react-native"] as const;
export type Sdk = (typeof SDKS)[number];
export const MODES = ["answer", "diff"] as const;
export type Mode = (typeof MODES)[number];
export const DIFF_KINDS = ["added", "removed", "renamed", "behaviour"] as const;
export type DiffKind = (typeof DIFF_KINDS)[number];

const optText = z.string().nullish().catch(null).transform((v) => v ?? undefined);
const text = z.string().nullish().catch(null).transform((v) => v ?? "");
const optNum = z.coerce.number().nullish().catch(null).transform((v) => (v === null || v === undefined || !Number.isFinite(v) ? undefined : v));
const count = z.coerce.number().nullish().catch(null).transform((v) => (v === null || v === undefined || !Number.isFinite(v) || v < 0 ? 0 : v));
const id = z.union([z.string(), z.number()]).transform(String);

/** Keep the items of a list that parse; drop the rest. */
function tolerantList<T extends z.ZodType>(item: T) {
  return z
    .array(z.unknown())
    .nullish()
    .catch(null)
    .transform((list): z.output<T>[] =>
      (list ?? []).flatMap((x) => {
        const r = item.safeParse(x);
        return r.success ? [r.data] : [];
      }),
    );
}

/* ---------- GET /api/versions ---------- */

export const VersionInfoSchema = z.preprocess(
  (v) => (typeof v === "string" ? { version: v } : v),
  z.object({
    version: z.string().min(1),
    chunk_count: optNum,
    ingested_at: optText,
    commit_sha: optText,
  }),
);
export type VersionInfo = z.infer<typeof VersionInfoSchema>;

export const SourceInfoSchema = z
  .object({
    name: z.string().min(1),
    versions: tolerantList(VersionInfoSchema),
    embedding_model: optText,
  })
  .transform((s) => ({
    ...s,
    // Newest first; the unversioned guides are searched with every version, never picked on their own.
    versions: s.versions.filter((v) => v.version !== "unversioned").sort((a, b) => compareVersionsDesc(a.version, b.version)),
  }));
export type SourceInfo = z.infer<typeof SourceInfoSchema>;

export const VersionsSchema = z.object({
  sources: tolerantList(SourceInfoSchema),
});
export type Versions = z.infer<typeof VersionsSchema>;

/* ---------- POST /api/ask: stream events ---------- */

const headingPath = z
  .union([z.string(), z.array(z.string())])
  .nullish()
  .catch(null)
  .transform((v) => (Array.isArray(v) ? v.join(" › ") : (v ?? "")));

export const RetrievedChunkSchema = z
  .object({
    id: id.optional().catch(undefined),
    chunk_id: id.optional().catch(undefined),
    n: z.coerce.number().int().positive(),
    title: text,
    heading_path: headingPath,
    url: text,
    version: text,
    score: optNum,
    snippet: text,
    content: optText,
    kind: optText,
  })
  .transform((c) => ({
    id: c.id ?? c.chunk_id ?? String(c.n),
    n: c.n,
    title: c.title || c.heading_path.split(" › ").at(-1) || "Untitled section",
    heading_path: c.heading_path,
    url: c.url,
    version: c.version,
    score: c.score,
    snippet: c.snippet || c.content || "",
    kind: c.kind,
  }));
export type RetrievedChunk = z.infer<typeof RetrievedChunkSchema>;

export const VerifiedCitationSchema = z.object({
  n: z.coerce.number().int().positive(),
  chunk_id: id.optional().catch(undefined),
  url: optText,
  quote: optText,
});
export type VerifiedCitation = z.infer<typeof VerifiedCitationSchema>;

export const RemovedCitationSchema = z.preprocess(
  (v) => (typeof v === "number" ? { n: v } : v),
  z.object({
    n: z.coerce.number().int().positive(),
    reason: z.string().nullish().catch(null).transform((v) => v ?? "not found in the retrieved passages"),
  }),
);
export type RemovedCitation = z.infer<typeof RemovedCitationSchema>;

export const CitationsSchema = z.object({
  verified: tolerantList(VerifiedCitationSchema),
  removed: tolerantList(RemovedCitationSchema),
  unsupported: z.boolean().nullish().catch(null).transform((v) => v ?? false),
});
export type Citations = z.infer<typeof CitationsSchema>;

const diffKind = z
  .string()
  .catch("behaviour")
  .transform((k): DiffKind => {
    const s = k.toLowerCase();
    if (s === "behavior" || s === "changed" || s === "modified") return "behaviour";
    return (DIFF_KINDS as readonly string[]).includes(s) ? (s as DiffKind) : "behaviour";
  });

export const DiffChangeSchema = z.object({
  kind: diffKind,
  before: optText,
  after: optText,
  citations: z
    .array(z.unknown())
    .nullish()
    .catch(null)
    .transform((l) => (l ?? []).map(Number).filter((n) => Number.isInteger(n) && n > 0)),
});
export type DiffChange = z.infer<typeof DiffChangeSchema>;

export const DiffSchema = z.object({
  summary: text,
  changes: tolerantList(DiffChangeSchema),
});
export type Diff = z.infer<typeof DiffSchema>;

export const UsageSchema = z
  .object({
    prompt_tokens: count,
    completion_tokens: count,
    total_tokens: optNum,
    usd: count,
  })
  .transform((u) => ({ ...u, total_tokens: u.total_tokens ?? u.prompt_tokens + u.completion_tokens }));
export type Usage = z.infer<typeof UsageSchema>;

export const EMPTY_USAGE: Usage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, usd: 0 };

export const DoneSchema = z.object({
  question_id: id.nullish().catch(null).transform((v) => v ?? undefined),
  latency_ms: optNum,
  usage: UsageSchema.nullish().catch(null).transform((u) => u ?? EMPTY_USAGE),
});
export type Done = z.infer<typeof DoneSchema>;

export type AskEvent =
  | { kind: "retrieval"; chunks: RetrievedChunk[] }
  | { kind: "token"; text: string }
  | { kind: "citations"; citations: Citations }
  | { kind: "diff"; diff: Diff }
  | { kind: "done"; done: Done }
  | { kind: "error"; code?: string; message?: string };

/**
 * Parse one SSE `data:` payload into an event. The kind comes from the JSON
 * `kind` field, or from the SSE `event:` name when the payload has none.
 * Returns null for keep-alives, junk and unknown kinds.
 */
export function parseAskEvent(raw: string, eventName?: string): AskEvent | null {
  const trimmed = raw.trim();
  if (trimmed === "" || trimmed === "[DONE]") return null;
  let json: unknown;
  try {
    json = JSON.parse(trimmed);
  } catch {
    return null;
  }
  if (typeof json !== "object" || json === null || Array.isArray(json)) return null;
  const o = json as Record<string, unknown>;
  const kind = typeof o.kind === "string" ? o.kind : typeof o.type === "string" ? o.type : eventName;
  switch (kind) {
    case "retrieval": {
      const chunks = tolerantList(RetrievedChunkSchema).parse(o.chunks ?? o.sources);
      return { kind, chunks: chunks.sort((a, b) => a.n - b.n) };
    }
    case "token": {
      const t = typeof o.text === "string" ? o.text : typeof o.delta === "string" ? o.delta : "";
      return t === "" ? null : { kind, text: t };
    }
    case "citations": {
      const r = CitationsSchema.safeParse(o.citations && typeof o.citations === "object" ? o.citations : o);
      return r.success ? { kind, citations: r.data } : null;
    }
    case "diff": {
      const r = DiffSchema.safeParse(o.diff && typeof o.diff === "object" ? o.diff : o);
      return r.success ? { kind, diff: r.data } : null;
    }
    case "done": {
      const r = DoneSchema.safeParse(o);
      return r.success ? { kind, done: r.data } : null;
    }
    case "error":
      return {
        kind,
        code: typeof o.code === "string" ? o.code : undefined,
        message: typeof o.message === "string" ? o.message : undefined,
      };
    default:
      return null;
  }
}

/* ---------- GET /api/questions/{id} ---------- */

const citationsOrUndefined = z
  .unknown()
  .transform((v): Citations | undefined => {
    if (!v || typeof v !== "object") return undefined;
    // A bare list is taken as the verified list.
    const r = CitationsSchema.safeParse(Array.isArray(v) ? { verified: v } : v);
    return r.success ? r.data : undefined;
  });

/**
 * A stored question. The API stores `retrieval` as jsonb; the chunks the UI
 * needs may sit at `chunks`, `retrieval.chunks` or `sources`. Citations may be
 * at `citations` (with `verification` holding removed/unsupported) or flat.
 */
export const StoredQuestionSchema = z
  .object({
    id: id,
    created_at: optText,
    question: text,
    sdk: optText,
    source: optText,
    version: text,
    compare_version: optText,
    mode: optText,
    answer: text,
    chunks: z.unknown().optional(),
    sources: z.unknown().optional(),
    retrieval: z.unknown().optional(),
    citations: citationsOrUndefined.optional(),
    verification: z.unknown().optional(),
    diff: z.unknown().optional(),
    usage: UsageSchema.nullish().catch(null).transform((u) => u ?? undefined),
    latency_ms: optNum,
    feedback: z
      .string()
      .nullish()
      .catch(null)
      .transform((f): "up" | "down" | null => (f === "up" || f === "down" ? f : null)),
  })
  .transform((q) => {
    const retrieval = q.retrieval && typeof q.retrieval === "object" ? (q.retrieval as Record<string, unknown>) : {};
    const rawChunks = q.chunks ?? q.sources ?? retrieval.chunks ?? (Array.isArray(q.retrieval) ? q.retrieval : undefined);
    const chunks = tolerantList(RetrievedChunkSchema).parse(rawChunks).sort((a, b) => a.n - b.n);
    const verification = q.verification && typeof q.verification === "object" ? (q.verification as Record<string, unknown>) : {};
    // Merge: `citations` wins field by field, `verification` fills the gaps.
    const ver = CitationsSchema.parse(verification);
    const hasVer = ver.verified.length > 0 || ver.removed.length > 0 || ver.unsupported;
    const c = q.citations;
    const citations: Citations | undefined = c
      ? {
          verified: c.verified.length > 0 ? c.verified : ver.verified,
          removed: c.removed.length > 0 ? c.removed : ver.removed,
          unsupported: c.unsupported || ver.unsupported,
        }
      : hasVer
        ? ver
        : undefined;
    const diffParsed = q.diff && typeof q.diff === "object" ? DiffSchema.safeParse(q.diff) : undefined;
    const sdk = q.sdk ?? q.source ?? "expo";
    const mode: Mode = q.mode === "diff" ? "diff" : "answer";
    return {
      id: q.id,
      created_at: q.created_at,
      question: q.question,
      sdk,
      version: q.version,
      compare_version: q.compare_version,
      mode,
      answer: q.answer,
      chunks,
      citations,
      diff: diffParsed?.success ? diffParsed.data : undefined,
      usage: q.usage,
      latency_ms: q.latency_ms,
      feedback: q.feedback,
    };
  });
export type StoredQuestion = z.infer<typeof StoredQuestionSchema>;

/* ---------- requests ---------- */

export type ThreadMessage = { role: "user" | "assistant"; content: string };

export type AskInput = {
  question: string;
  sdk: Sdk;
  version: string;
  mode: Mode;
  compare_version?: string;
  thread?: ThreadMessage[];
};

export const MAX_QUESTION_LENGTH = 1000;

/** The JSON body for `POST /api/ask`, with empty optional fields left out. */
export function askBody(input: AskInput): AskInput {
  const body: AskInput = { question: input.question.trim(), sdk: input.sdk, version: input.version, mode: input.mode };
  if (input.mode === "diff" && input.compare_version) body.compare_version = input.compare_version;
  if (input.thread && input.thread.length > 0) body.thread = input.thread;
  return body;
}

export const askUrl = () => `${API_URL}/api/ask`;
export const questionUrl = (qid: string) => `${API_URL}/api/questions/${encodeURIComponent(qid)}`;

async function readBody(res: Response): Promise<unknown> {
  const t = await res.text();
  try {
    return JSON.parse(t);
  } catch {
    return t;
  }
}

async function request(path: string, init?: RequestInit & { next?: { revalidate?: number } }): Promise<unknown> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      cache: "no-store",
      ...init,
      headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
    });
  } catch {
    throw networkError(API_URL);
  }
  const body = await readBody(res);
  if (!res.ok) throw parseApiError(res.status, body, res.headers.get("Retry-After"));
  return body;
}

function invalid(what: string): ApiError {
  return new ApiError({ status: 502, code: "server", message: `The API sent ${what} this page could not read.` });
}

export async function getVersions(): Promise<Versions> {
  const raw = API_MOCK ? await mock.mockVersions() : await request("/api/versions");
  const parsed = VersionsSchema.safeParse(raw);
  if (!parsed.success) throw invalid("a version list");
  return parsed.data;
}

export async function getQuestion(qid: string): Promise<StoredQuestion> {
  const raw = API_MOCK ? mock.mockGetQuestion(qid) : await request(`/api/questions/${encodeURIComponent(qid)}`);
  const parsed = StoredQuestionSchema.safeParse(raw);
  if (!parsed.success) throw invalid("a stored question");
  return parsed.data;
}

export async function sendFeedback(qid: string, feedback: "up" | "down"): Promise<void> {
  if (API_MOCK) return mock.mockFeedback(qid, feedback);
  await request(`/api/questions/${encodeURIComponent(qid)}/feedback`, { method: "POST", body: JSON.stringify({ feedback }) });
}

/**
 * `POST /api/ask` read as an SSE stream over fetch. Errors before the stream
 * (429, 400, 404, 503) throw an ApiError; events inside the stream, including
 * `{ kind: "error" }`, go to `onEvent`. Resolves with whether the stream ended
 * with a terminal event (`done` or `error`); false means it was cut off.
 */
export async function streamAsk(
  input: AskInput,
  onEvent: (event: AskEvent) => void,
  signal?: AbortSignal,
): Promise<{ terminal: boolean }> {
  const body = askBody(input);
  if (API_MOCK) return mock.mockAsk(body, onEvent, signal);
  let res: Response;
  try {
    res = await fetch(askUrl(), {
      method: "POST",
      headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      signal,
    });
  } catch (e) {
    if (signal?.aborted) return { terminal: false };
    void e;
    throw networkError(API_URL);
  }
  if (!res.ok) throw parseApiError(res.status, await readBody(res), res.headers.get("Retry-After"));
  const type = res.headers.get("Content-Type") ?? "";
  if (!res.body || (!type.includes("text/event-stream") && type.includes("application/json"))) {
    // A JSON body with 200 is not a stream: treat a `{ detail }` as an error, anything else as unreadable.
    const b = await readBody(res);
    if (b && typeof b === "object" && "detail" in b) throw parseApiError(500, b);
    throw invalid("a response");
  }
  let terminal = false;
  try {
    for await (const msg of readSse(res.body, signal)) {
      const ev = parseAskEvent(msg.data, msg.event);
      if (!ev) continue;
      if (ev.kind === "done" || ev.kind === "error") terminal = true;
      onEvent(ev);
      if (terminal) break;
    }
  } catch (e) {
    if (signal?.aborted) return { terminal };
    void e;
    throw new ApiError({ status: 0, code: "stream", message: "The connection dropped while the answer was streaming." });
  }
  return { terminal };
}
