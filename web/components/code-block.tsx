import { cn } from "@/lib/utils";
import { CopyButton } from "./copy-button";

/** A terminal-styled snippet with a filename/label bar and a copy button. Scrolls inside itself, never the page. */
export function CodeBlock({ code, label, className }: { code: string; label: string; className?: string }) {
  return (
    <figure className={cn("min-w-0 overflow-hidden rounded-lg bg-term text-term-fg", className)}>
      <figcaption className="flex items-center justify-between gap-3 border-b border-term-rule px-4 py-2">
        <span className="figure truncate text-xs text-term-dim">{label}</span>
        <CopyButton text={code} tone="terminal" />
      </figcaption>
      <pre className="overflow-x-auto px-4 py-3.5 text-[0.8125rem] leading-relaxed" tabIndex={0} aria-label={`${label} snippet`}>
        <code className="figure">{code}</code>
      </pre>
    </figure>
  );
}
