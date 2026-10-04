import { Fragment, type ReactNode } from "react";
import { CodeBlock } from "@/components/code-block";
import type { RetrievedChunk } from "@/lib/api";
import { parseMarkdown, type Inline } from "@/lib/markdown";
import { CitationChip, type ChipState } from "./citation-chip";

type Ctx = {
  idPrefix: string;
  chunksByN: Map<number, RetrievedChunk>;
  /** Citation numbers the verifier removed: not rendered. */
  removed: Set<number>;
  /** Whether the verifier has reported yet (chips are "pending" until it has). */
  verified: boolean;
};

function chipState(n: number, ctx: Ctx): ChipState {
  if (!ctx.chunksByN.has(n)) return "missing";
  return ctx.verified ? "verified" : "pending";
}

function renderInline(nodes: Inline[], ctx: Ctx, key = "i"): ReactNode[] {
  return nodes.map((node, i) => {
    const k = `${key}.${i}`;
    switch (node.type) {
      case "text":
        return <Fragment key={k}>{node.text}</Fragment>;
      case "code":
        return <code key={k}>{node.text}</code>;
      case "strong":
        return (
          <strong key={k} className="font-semibold">
            {renderInline(node.children, ctx, k)}
          </strong>
        );
      case "em":
        return <em key={k}>{renderInline(node.children, ctx, k)}</em>;
      case "link":
        return (
          <a key={k} href={node.href} rel="noopener noreferrer" target="_blank">
            {renderInline(node.children, ctx, k)}
          </a>
        );
      case "cite": {
        const shown = [...new Set(node.ns)].filter((n) => !ctx.removed.has(n));
        if (shown.length === 0) return null;
        return (
          <span key={k} className="whitespace-nowrap">
            {shown.map((n) => (
              <CitationChip key={n} n={n} idPrefix={ctx.idPrefix} title={ctx.chunksByN.get(n)?.title} state={chipState(n, ctx)} />
            ))}
          </span>
        );
      }
    }
  });
}

/** The answer text as a document: paragraphs, lists, code, and inline citation chips. */
export function AnswerProse({
  text,
  chunks,
  removed,
  verified,
  idPrefix,
  streaming,
}: {
  text: string;
  chunks: RetrievedChunk[] | undefined;
  removed: Set<number>;
  verified: boolean;
  idPrefix: string;
  streaming?: boolean;
}) {
  const ctx: Ctx = { idPrefix, chunksByN: new Map((chunks ?? []).map((c) => [c.n, c])), removed, verified };
  const blocks = parseMarkdown(text);
  const caret = streaming ? <span className="caret ml-0.5 text-cite" aria-hidden="true" /> : null;
  const lastIndex = blocks.length - 1;

  return (
    <div className="prose-answer min-w-0">
      {blocks.map((b, i) => {
        const tail = i === lastIndex ? caret : null;
        switch (b.type) {
          case "paragraph":
            return (
              <p key={i}>
                {renderInline(b.children, ctx, `p${i}`)}
                {tail}
              </p>
            );
          case "heading": {
            const H = b.level === 3 ? "h3" : "h4";
            return <H key={i}>{renderInline(b.children, ctx, `h${i}`)}</H>;
          }
          case "list": {
            const items = b.items.map((it, j) => (
              <li key={j}>
                {renderInline(it, ctx, `l${i}.${j}`)}
                {j === b.items.length - 1 ? tail : null}
              </li>
            ));
            return b.ordered ? (
              <ol key={i} start={b.start !== 1 ? b.start : undefined}>
                {items}
              </ol>
            ) : (
              <ul key={i}>{items}</ul>
            );
          }
          case "code":
            return (
              <div key={i}>
                <CodeBlock code={b.text} label={b.lang || "code"} />
                {tail}
              </div>
            );
        }
      })}
      {blocks.length === 0 && caret ? <p>{caret}</p> : null}
    </div>
  );
}
