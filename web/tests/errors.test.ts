import { describe, expect, it } from "vitest";
import { errorTitle, parseApiError, retryHint, streamError } from "@/lib/errors";

describe("parseApiError", () => {
  it("reads the contract shape { detail: { code, message, retry_after } }", () => {
    const e = parseApiError(429, { detail: { code: "rate_limited", message: "Slow down", retry_after: 120 } });
    expect(e.code).toBe("rate_limited");
    expect(e.message).toBe("Slow down");
    expect(e.retryAfter).toBe(120);
    expect(errorTitle(e)).toBe("Rate limit reached");
    expect(retryHint(e)).toBe("Try again in 2 minutes.");
  });

  it("falls back to Retry-After and a default message for a bare 429", () => {
    const e = parseApiError(429, "", "30");
    expect(e.code).toBe("rate_limited");
    expect(e.retryAfter).toBe(30);
    expect(e.message).toMatch(/30 questions per hour/);
    expect(retryHint(e)).toBe("Try again in 30 seconds.");
  });

  it("maps the contract codes", () => {
    expect(parseApiError(400, { detail: { code: "invalid_input", message: "Too long" } }).code).toBe("invalid_input");
    expect(parseApiError(404, { detail: { code: "version_not_found", message: "No v12" } }).code).toBe("version_not_found");
    expect(parseApiError(503, { detail: { code: "unavailable", message: "Groq down" } }).code).toBe("unavailable");
  });

  it("maps FastAPI validation errors to fields", () => {
    const e = parseApiError(422, { detail: [{ loc: ["body", "question"], msg: "String should have at most 1000 characters" }] });
    expect(e.code).toBe("invalid_input");
    expect(e.fields.question).toMatch(/1000/);
  });

  it("guesses codes from status when none is sent", () => {
    expect(parseApiError(404, { detail: "Not Found" }).code).toBe("question_not_found");
    expect(parseApiError(404, { detail: "Version v99 not found" }).code).toBe("version_not_found");
    expect(parseApiError(503, "").code).toBe("unavailable");
    expect(parseApiError(500, "<html>").code).toBe("server");
  });

  it("accepts flat and nested error shapes and code aliases", () => {
    expect(parseApiError(400, { code: "validation", message: "bad" }).code).toBe("invalid_input");
    expect(parseApiError(503, { error: { code: "service_unavailable", message: "x" } }).code).toBe("unavailable");
  });
});

describe("streamError", () => {
  it("keeps known codes and falls back to stream", () => {
    expect(streamError("unavailable", "down").code).toBe("unavailable");
    const e = streamError("weird", undefined);
    expect(e.code).toBe("stream");
    expect(e.message).toMatch(/stopped/);
  });
});
