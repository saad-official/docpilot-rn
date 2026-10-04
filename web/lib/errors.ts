/**
 * Errors from the DocPilot RN API, normalised from whatever JSON shape the
 * server sent. The contract (spec §6) for errors before a stream starts is
 * `{ detail: { code, message, retry_after? } }`. FastAPI's defaults
 * (`{ detail: string }`, and `{ detail: [{ loc, msg }] }` for validation) and a
 * flat `{ code, message }` or `{ error: { code, message } }` are accepted too.
 * Errors inside a stream arrive as `{ kind: "error", code, message }` and are
 * turned into the same class by `streamError`.
 */

export type ApiErrorCode =
  | "rate_limited"
  | "invalid_input"
  | "version_not_found"
  | "question_not_found"
  | "unavailable"
  | "stream"
  | "network"
  | "server"
  | "unknown";

export type FieldName = "question" | "sdk" | "version" | "compare_version" | "mode";

export class ApiError extends Error {
  readonly status: number;
  readonly code: ApiErrorCode;
  /** Seconds until a rate-limited client may retry, when the server said so. */
  readonly retryAfter?: number;
  /** Field-level messages from request validation, keyed by body field. */
  readonly fields: Partial<Record<FieldName, string>>;

  constructor(opts: {
    status: number;
    code: ApiErrorCode;
    message: string;
    retryAfter?: number;
    fields?: Partial<Record<FieldName, string>>;
  }) {
    super(opts.message);
    this.name = "ApiError";
    this.status = opts.status;
    this.code = opts.code;
    this.retryAfter = opts.retryAfter;
    this.fields = opts.fields ?? {};
  }
}

const KNOWN_CODES = new Set<ApiErrorCode>([
  "rate_limited",
  "invalid_input",
  "version_not_found",
  "question_not_found",
  "unavailable",
]);

/** Aliases the API might reasonably send for the same thing. */
const CODE_ALIASES: Record<string, ApiErrorCode> = {
  validation: "invalid_input",
  validation_error: "invalid_input",
  bad_request: "invalid_input",
  not_found: "question_not_found",
  service_unavailable: "unavailable",
  provider_unavailable: "unavailable",
  too_many_requests: "rate_limited",
};

const FIELD_NAMES = new Set<FieldName>(["question", "sdk", "version", "compare_version", "mode"]);

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function str(v: unknown): string | undefined {
  return typeof v === "string" && v.trim() !== "" ? v : undefined;
}

function num(v: unknown): number | undefined {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v))) return Number(v);
  return undefined;
}

export function normaliseCode(raw: unknown): ApiErrorCode | undefined {
  const c = str(raw)?.toLowerCase();
  if (!c) return undefined;
  if (KNOWN_CODES.has(c as ApiErrorCode)) return c as ApiErrorCode;
  return CODE_ALIASES[c];
}

/** Guess a code from the status (and message) when the server did not send one. */
function codeFromStatus(status: number, message: string): ApiErrorCode {
  const m = message.toLowerCase();
  if (status === 429) return "rate_limited";
  if (status === 404) return m.includes("version") ? "version_not_found" : "question_not_found";
  if (status === 400 || status === 422) return m.includes("version") && m.includes("not") ? "version_not_found" : "invalid_input";
  if (status === 503) return "unavailable";
  if (status >= 500) return "server";
  return "unknown";
}

export function defaultMessage(code: ApiErrorCode, status: number): string {
  switch (code) {
    case "rate_limited":
      return "Too many questions from this address. The limit is 30 questions per hour.";
    case "invalid_input":
      return "The question could not be accepted. Check that it is not empty and not too long.";
    case "version_not_found":
      return "That version is not in the index. Pick one from the list.";
    case "question_not_found":
      return "No stored question with that id.";
    case "unavailable":
      return "The answering service is unavailable right now (a model provider or the database). Try again in a minute.";
    case "stream":
      return "The answer stopped before it finished.";
    case "server":
      return `The API returned an error (${status}). Try again in a minute.`;
    default:
      return `Request failed (${status}).`;
  }
}

/** Build an ApiError from a status, a parsed (or unparsable) body and an optional Retry-After header. */
export function parseApiError(status: number, body: unknown, retryAfterHeader?: string | null): ApiError {
  let code: ApiErrorCode | undefined;
  let message: string | undefined;
  let retryAfter = num(retryAfterHeader ?? undefined);
  const fields: Partial<Record<FieldName, string>> = {};

  const readObject = (o: Record<string, unknown>) => {
    code = normaliseCode(o.code) ?? code;
    message = str(o.message) ?? str(o.msg) ?? str(o.detail) ?? message;
    retryAfter = num(o.retry_after) ?? num(o.retryAfter) ?? retryAfter;
  };

  if (isRecord(body)) {
    const detail = body.detail;
    if (typeof detail === "string") {
      message = detail;
    } else if (Array.isArray(detail)) {
      // FastAPI request validation: [{ loc: ["body", "question"], msg: "Field required" }]
      const msgs: string[] = [];
      for (const d of detail) {
        if (!isRecord(d)) continue;
        const msg = str(d.msg) ?? "Invalid value";
        const loc = Array.isArray(d.loc) ? d.loc.map(String) : [];
        const field = [...loc].reverse().find((l) => FIELD_NAMES.has(l as FieldName)) as FieldName | undefined;
        if (field && !fields[field]) fields[field] = msg;
        msgs.push(field ? `${field}: ${msg}` : msg);
      }
      message = msgs.length > 0 ? msgs.join("; ") : undefined;
      code = "invalid_input";
    } else if (isRecord(detail)) {
      readObject(detail);
      const f = str(detail.field);
      if (f && FIELD_NAMES.has(f as FieldName) && message) fields[f as FieldName] = message;
    } else if (isRecord(body.error)) {
      readObject(body.error);
    } else {
      readObject(body);
    }
  } else if (typeof body === "string" && body.trim() !== "" && !body.trim().startsWith("<")) {
    message = body.trim().slice(0, 300);
  }

  const resolved = code ?? codeFromStatus(status, message ?? "");
  return new ApiError({
    status,
    code: resolved,
    message: message ?? defaultMessage(resolved, status),
    retryAfter,
    fields,
  });
}

/** An `{ kind: "error" }` event inside the SSE stream. */
export function streamError(code: string | undefined, message: string | undefined): ApiError {
  const resolved = normaliseCode(code) ?? "stream";
  return new ApiError({ status: 200, code: resolved, message: message || defaultMessage(resolved, 200) });
}

export function networkError(apiUrl: string): ApiError {
  return new ApiError({
    status: 0,
    code: "network",
    message: `Could not reach the API at ${apiUrl}. It may be starting up; try again in a few seconds.`,
  });
}

/** Short heading for an error box. */
export function errorTitle(err: ApiError): string {
  switch (err.code) {
    case "rate_limited":
      return "Rate limit reached";
    case "invalid_input":
      return "Check the question";
    case "version_not_found":
      return "Version not indexed";
    case "question_not_found":
      return "Question not found";
    case "unavailable":
      return "Service unavailable";
    case "stream":
      return "Answer interrupted";
    case "network":
      return "API unreachable";
    case "server":
      return "API error";
    default:
      return "Something went wrong";
  }
}

/** "Try again in 4 minutes" style hint for rate limits. */
export function retryHint(err: ApiError): string | undefined {
  if (err.code !== "rate_limited" || err.retryAfter === undefined) return undefined;
  const s = Math.max(1, Math.round(err.retryAfter));
  if (s < 90) return `Try again in ${s} seconds.`;
  return `Try again in ${Math.ceil(s / 60)} minutes.`;
}
