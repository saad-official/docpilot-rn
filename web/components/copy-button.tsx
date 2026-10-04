"use client";

import { useState } from "react";
import { CheckIcon, CopyIcon } from "lucide-react";
import { toast } from "sonner";
import { copyText } from "@/lib/clipboard";
import { cn } from "@/lib/utils";

/**
 * Copies `text`; on failure the toast says so and `onFallback` (if given) can
 * reveal the text for manual selection.
 */
export function CopyButton({
  text,
  label = "Copy",
  copiedLabel = "Copied",
  className,
  onFallback,
  tone = "paper",
  srLabel,
}: {
  text: string;
  label?: string;
  copiedLabel?: string;
  className?: string;
  onFallback?: () => void;
  tone?: "paper" | "terminal";
  /** Extra context for screen readers, e.g. which document. */
  srLabel?: string;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        const ok = await copyText(text);
        if (ok) {
          setCopied(true);
          setTimeout(() => setCopied(false), 1800);
        } else {
          toast.error("Could not copy automatically. The text is selected below; press Ctrl+C or Cmd+C.");
          onFallback?.();
        }
      }}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-semibold motion-safe:transition-colors focus-visible:outline-2 focus-visible:outline-offset-2",
        tone === "terminal"
          ? "border-term-rule bg-transparent text-term-fg hover:bg-white/8 focus-visible:outline-term-fg"
          : "border-input bg-sheet text-foreground hover:bg-muted focus-visible:outline-cite",
        className,
      )}
    >
      {copied ? <CheckIcon className="size-3.5" aria-hidden="true" /> : <CopyIcon className="size-3.5" aria-hidden="true" />}
      <span aria-live="polite">{copied ? copiedLabel : label}</span>
      {srLabel ? <span className="sr-only">{srLabel}</span> : null}
    </button>
  );
}
