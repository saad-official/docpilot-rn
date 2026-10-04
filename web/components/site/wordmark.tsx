import Link from "next/link";

/** `DocPilot` in Plex Serif, a citation chip for the mark, `rn` in mono teal like a version. */
export function Wordmark() {
  return (
    <Link href="/" className="inline-flex items-center gap-2 rounded-sm" aria-label="DocPilot RN, home">
      <span
        aria-hidden="true"
        className="figure inline-flex h-5 min-w-5 items-center justify-center rounded-[0.3rem] border border-cite/45 bg-cite-wash px-1 text-[0.7rem] font-semibold text-cite-ink"
      >
        1
      </span>
      <span aria-hidden="true" className="font-serif text-[1.1rem] font-semibold tracking-[-0.01em]">
        DocPilot
      </span>
      <span
        aria-hidden="true"
        className="figure -ml-0.5 rounded-sm border border-version/40 bg-version-wash px-1.5 py-px text-[0.72rem] font-medium text-version-ink"
      >
        rn
      </span>
    </Link>
  );
}
