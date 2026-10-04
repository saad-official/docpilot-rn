"use client";

import Link from "next/link";
import { LinkIcon } from "lucide-react";
import { CopyButton } from "@/components/copy-button";

export function questionPath(id: string) {
  return `/q/${encodeURIComponent(id)}`;
}

/** The shareable link for a stored answer, with a copy button for the absolute URL. */
export function ShareLink({ questionId }: { questionId: string }) {
  const path = questionPath(questionId);
  const absolute = typeof window === "undefined" ? path : `${window.location.origin}${path}`;
  return (
    <div className="flex min-w-0 items-center gap-2">
      <Link
        href={path}
        className="figure inline-flex min-w-0 items-center gap-1 truncate text-xs text-cite-ink underline decoration-cite-ink/30 underline-offset-3 hover:decoration-cite-ink"
      >
        <LinkIcon className="size-3 shrink-0" aria-hidden="true" />
        <span className="truncate">{path}</span>
        <span className="sr-only">(permanent link to this answer)</span>
      </Link>
      <CopyButton text={absolute} label="Copy link" copiedLabel="Copied" srLabel="to this answer" />
    </div>
  );
}
