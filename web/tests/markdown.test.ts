import { describe, expect, it } from "vitest";
import { citedNumbers, parseInline, parseMarkdown, stripCitations } from "@/lib/markdown";
import { answerText } from "@/lib/mock";

describe("parseInline", () => {
  it("turns [n], [n, m] and [n][m] into citation groups, but not links", () => {
    expect(parseInline("A [1] B [2, 3] C [4][5] [docs](https://x.dev)")).toEqual([
      { type: "text", text: "A " },
      { type: "cite", ns: [1] },
      { type: "text", text: " B " },
      { type: "cite", ns: [2, 3] },
      { type: "text", text: " C " },
      { type: "cite", ns: [4, 5] },
      { type: "text", text: " " },
      { type: "link", href: "https://x.dev", children: [{ type: "text", text: "docs" }] },
    ]);
  });

  it("parses code, bold and italics, and leaves unclosed markers literal", () => {
    expect(parseInline("call `foo()` **now** *please*")).toEqual([
      { type: "text", text: "call " },
      { type: "code", text: "foo()" },
      { type: "text", text: " " },
      { type: "strong", children: [{ type: "text", text: "now" }] },
      { type: "text", text: " " },
      { type: "em", children: [{ type: "text", text: "please" }] },
    ]);
    expect(parseInline("half `open and **bold")).toEqual([{ type: "text", text: "half `open and **bold" }]);
  });

  it("does not treat snake_case underscores as emphasis", () => {
    expect(parseInline("use snake_case_name here")).toEqual([{ type: "text", text: "use snake_case_name here" }]);
  });

  it("never links non-http URLs", () => {
    expect(parseInline("[x](javascript:alert(1))").some((n) => n.type === "link")).toBe(false);
  });
});

describe("parseMarkdown", () => {
  it("reads paragraphs, a fenced code block and an ordered list from the fixture", () => {
    const blocks = parseMarkdown(answerText);
    expect(blocks.map((b) => b.type)).toEqual(["paragraph", "code", "paragraph", "list"]);
    const code = blocks[1];
    expect(code.type === "code" && code.lang).toBe("ts");
    expect(code.type === "code" && code.open).toBe(false);
    const list = blocks[3];
    expect(list.type === "list" && list.ordered && list.items.length).toBe(2);
  });

  it("treats an unclosed fence as code so far (streaming)", () => {
    const blocks = parseMarkdown("Intro\n\n```ts\nconst a = 1;");
    expect(blocks[1]).toEqual({ type: "code", lang: "ts", text: "const a = 1;", open: true });
  });

  it("demotes headings to h3/h4", () => {
    const blocks = parseMarkdown("# Top\n### Deep");
    expect(blocks).toMatchObject([{ type: "heading", level: 3 }, { type: "heading", level: 4 }]);
  });
});

describe("citation helpers", () => {
  it("lists cited numbers in order of first appearance", () => {
    expect(citedNumbers(answerText)).toEqual([1, 2, 3, 7]);
  });

  it("strips citation markers for the thread", () => {
    expect(stripCitations("Call it [1]. Then this [2, 3].")).toBe("Call it. Then this.");
  });
});
