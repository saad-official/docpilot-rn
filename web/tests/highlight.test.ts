import { describe, expect, it } from "vitest";
import { splitOnQuote } from "@/lib/highlight";

describe("splitOnQuote", () => {
  const snippet = "Schedules a notification.  Pass a time interval trigger with type\nTIME_INTERVAL and seconds.";

  it("marks the quote, ignoring case and whitespace differences, keeping the original text", () => {
    const segs = splitOnQuote(snippet, "pass a time interval trigger with type time_interval");
    expect(segs).toEqual([
      { text: "Schedules a notification.  ", mark: false },
      { text: "Pass a time interval trigger with type\nTIME_INTERVAL", mark: true },
      { text: " and seconds.", mark: false },
    ]);
  });

  it("tolerates wrapping quotes, ellipses and curly punctuation", () => {
    const segs = splitOnQuote("It’s required — always.", "“...it's required - always”");
    expect(segs.find((s) => s.mark)?.text).toBe("It’s required — always");
  });

  it("returns the snippet unmarked when the quote is missing, short or absent", () => {
    expect(splitOnQuote(snippet, "not in there")).toEqual([{ text: snippet, mark: false }]);
    expect(splitOnQuote(snippet, "a")).toEqual([{ text: snippet, mark: false }]);
    expect(splitOnQuote(snippet, undefined)).toEqual([{ text: snippet, mark: false }]);
  });
});
