import { ArrowRightIcon } from "lucide-react";
import type { Diff, DiffKind, RetrievedChunk } from "@/lib/api";
import { versionLabel } from "@/lib/format";
import { cn } from "@/lib/utils";
import { CitationChip } from "./citation-chip";

const KIND: Record<DiffKind, { label: string; mark: string; className: string }> = {
  added: { label: "added", mark: "+", className: "border-added/50 bg-added-wash text-added-ink" },
  removed: { label: "removed", mark: "−", className: "border-removed/55 bg-removed-wash text-removed-ink" },
  renamed: { label: "renamed", mark: "→", className: "border-cite/35 bg-cite-wash text-cite-ink" },
  behaviour: { label: "behaviour", mark: "~", className: "border-border bg-muted text-foreground" },
};

/** Render `inline code` spans inside a diff cell without a full Markdown pass. */
function Cell({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`)/g);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("`") && p.endsWith("`") && p.length > 2 ? (
          <code key={i} className="figure text-[0.92em]">
            {p.slice(1, -1)}
          </code>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

/**
 * The structured "What changed?" diff, above the prose: one row per change,
 * before (older version, amber) and after (newer version, green), with
 * citation chips that point at passages from either version.
 */
export function DiffTable({
  diff,
  sdk,
  olderVersion,
  newerVersion,
  chunks,
  removed,
  idPrefix,
}: {
  diff: Diff;
  sdk: string;
  olderVersion: string;
  newerVersion: string;
  chunks: RetrievedChunk[] | undefined;
  removed: Set<number>;
  idPrefix: string;
}) {
  const byN = new Map((chunks ?? []).map((c) => [c.n, c]));
  const older = versionLabel(sdk, olderVersion);
  const newer = versionLabel(sdk, newerVersion);
  return (
    <section aria-label={`What changed between ${older} and ${newer}`} className="rounded-md border border-border bg-sheet">
      {diff.summary ? <p className="border-b border-border px-4 py-3 text-[0.9375rem] leading-relaxed">{diff.summary}</p> : null}
      {diff.changes.length === 0 ? (
        <p className="px-4 py-3 text-sm text-muted-foreground">No documented change between these versions for this question.</p>
      ) : (
        <>
        {/* Phones: one stacked card per change. */}
        <ul className="divide-y divide-border sm:hidden">
          {diff.changes.map((c, i) => {
            const k = KIND[c.kind];
            const cites = c.citations.filter((n) => !removed.has(n));
            return (
              <li key={i} className="space-y-2 px-4 py-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className={cn("figure inline-flex h-6 items-center gap-1 rounded-sm border px-1.5 text-xs font-semibold", k.className)}>
                    <span aria-hidden="true">{k.mark}</span>
                    {k.label}
                  </span>
                  <span className="whitespace-nowrap">
                    {cites.map((n) => (
                      <CitationChip key={n} n={n} idPrefix={idPrefix} title={byN.get(n)?.title} state={byN.has(n) ? "verified" : "missing"} className="text-[0.8rem]" />
                    ))}
                  </span>
                </div>
                <p className="leading-relaxed [overflow-wrap:anywhere]">
                  <span className="figure mr-1.5 text-xs text-removed-ink">{older}</span>
                  {c.before ? <Cell text={c.before} /> : <span className="text-muted-foreground">nothing</span>}
                </p>
                <p className="leading-relaxed [overflow-wrap:anywhere]">
                  <span className="figure mr-1.5 text-xs text-added-ink">{newer}</span>
                  {c.after ? <Cell text={c.after} /> : <span className="text-muted-foreground">nothing</span>}
                </p>
              </li>
            );
          })}
        </ul>
        <div className="hidden overflow-x-auto sm:block">
          <table className="w-full border-collapse text-left text-sm">
            <caption className="sr-only">
              Changes from {older} to {newer}, with citations
            </caption>
            <thead>
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th scope="col" className="w-28 px-4 py-2 font-medium">
                  Change
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  <span className="figure text-removed-ink">{older}</span>
                </th>
                <th scope="col" className="w-6 px-0 py-2">
                  <span className="sr-only">becomes</span>
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  <span className="figure text-added-ink">{newer}</span>
                </th>
                <th scope="col" className="w-20 px-4 py-2 font-medium">
                  Sources
                </th>
              </tr>
            </thead>
            <tbody>
              {diff.changes.map((c, i) => {
                const k = KIND[c.kind];
                const cites = c.citations.filter((n) => !removed.has(n));
                return (
                  <tr key={i} className="border-b border-border align-top last:border-b-0">
                    <td className="px-4 py-3">
                      <span className={cn("figure inline-flex h-6 items-center gap-1 rounded-sm border px-1.5 text-xs font-semibold", k.className)}>
                        <span aria-hidden="true">{k.mark}</span>
                        {k.label}
                      </span>
                    </td>
                    <td className={cn("px-3 py-3 leading-relaxed [overflow-wrap:anywhere]", c.before ? "text-foreground/85" : "text-muted-foreground")}>
                      {c.before ? (
                        <span className={cn(c.kind === "removed" || c.kind === "renamed" ? "bg-removed-wash decoration-removed-ink/60" : "", c.kind === "removed" && "line-through")}>
                          <Cell text={c.before} />
                        </span>
                      ) : (
                        <span aria-label="nothing">—</span>
                      )}
                    </td>
                    <td className="px-0 py-3 text-muted-foreground">
                      <ArrowRightIcon className="mt-1 size-3.5" aria-hidden="true" />
                    </td>
                    <td className="px-3 py-3 leading-relaxed [overflow-wrap:anywhere]">
                      {c.after ? (
                        <span className={cn(c.kind === "added" || c.kind === "renamed" ? "bg-added-wash" : "")}>
                          <Cell text={c.after} />
                        </span>
                      ) : (
                        <span className="text-muted-foreground" aria-label="nothing">
                          —
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {cites.length > 0 ? (
                        cites.map((n) => (
                          <CitationChip key={n} n={n} idPrefix={idPrefix} title={byN.get(n)?.title} state={byN.has(n) ? "verified" : "missing"} className="text-[0.8rem]" />
                        ))
                      ) : (
                        <span className="text-xs text-muted-foreground">none</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        </>
      )}
    </section>
  );
}
