import type { Metadata } from "next";
import { Suspense } from "react";
import { AskWorkspace } from "@/components/ask/ask-workspace";
import { Skeleton } from "@/components/ui/skeleton";
import { container } from "@/lib/site";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "Ask the docs",
  description: "Ask about Expo or React Native for the version you are on. Streamed, cited, verified.",
};

function FormFallback() {
  return (
    <div className="rounded-lg border border-border bg-sheet p-5" aria-hidden="true">
      <div className="grid gap-4 sm:grid-cols-3">
        <Skeleton className="h-10" />
        <Skeleton className="h-10" />
        <Skeleton className="h-10" />
      </div>
      <Skeleton className="mt-4 h-24" />
    </div>
  );
}

export default function AskPage() {
  return (
    <div className={cn(container, "py-8 sm:py-12")}>
      <header className="mb-8 max-w-2xl space-y-2">
        <p className="kicker">§ ask</p>
        <h1 className="font-serif text-3xl font-semibold sm:text-4xl">Ask the docs</h1>
        <p className="text-[1.0625rem] leading-relaxed text-foreground/80">
          Pick the source and the version you are on. The answer streams in with numbered citations; each one is checked
          against the passage it points to before it is shown as verified.
        </p>
      </header>
      {/* useSearchParams (prefill from ?q=&sdk=&v=&mode=&cmp=) needs a Suspense boundary for static rendering. */}
      <Suspense fallback={<FormFallback />}>
        <AskWorkspace />
      </Suspense>
    </div>
  );
}
