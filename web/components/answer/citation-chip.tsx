import { cn } from "@/lib/utils";

export type ChipState = "verified" | "pending" | "missing";

const states: Record<ChipState, string> = {
  verified: "border-cite/40 bg-cite-wash text-cite-ink hover:bg-cite hover:text-sheet hover:border-cite",
  pending: "border-cite/45 bg-transparent text-cite-ink hover:bg-cite-wash",
  missing: "border-dashed border-pencil/50 bg-transparent text-pencil",
};

export function sourceAnchor(idPrefix: string, n: number) {
  return `${idPrefix}-src-${n}`;
}

/**
 * A numbered citation, inline in the answer or in a diff row. It is a plain
 * link to the source card (`#<prefix>-src-<n>`), so it works without
 * JavaScript and the card is highlighted through :target.
 */
export function CitationChip({
  n,
  idPrefix,
  title,
  state = "verified",
  className,
}: {
  n: number;
  idPrefix: string;
  /** Section title of the cited passage, for the accessible name. */
  title?: string;
  state?: ChipState;
  className?: string;
}) {
  const label = title ? `Source ${n}: ${title}` : `Source ${n}`;
  return (
    <a
      href={`#${sourceAnchor(idPrefix, n)}`}
      data-cite={n}
      aria-label={state === "missing" ? `${label} (not among the retrieved passages)` : label}
      title={title}
      className={cn(
        "figure mx-[0.12em] inline-flex h-[1.35em] min-w-[1.35em] -translate-y-[0.08em] items-center justify-center rounded-[0.3em] border px-[0.3em] align-middle text-[0.72em] leading-none font-semibold no-underline motion-safe:transition-colors",
        states[state],
        className,
      )}
    >
      {n}
    </a>
  );
}
