"use client";

import { useState } from "react";
import { ThumbsDownIcon, ThumbsUpIcon } from "lucide-react";
import { toast } from "sonner";
import { sendFeedback } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import { cn } from "@/lib/utils";

type Vote = "up" | "down";

const btn =
  "inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-semibold motion-safe:transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cite disabled:cursor-not-allowed disabled:opacity-60";

/**
 * Thumbs up/down for a stored answer: `POST /api/questions/{id}/feedback`.
 * Recorded, not acted on (spec §3). A second click on the other thumb changes the vote.
 */
export function FeedbackButtons({ questionId, initial = null }: { questionId: string; initial?: Vote | null }) {
  const [vote, setVote] = useState<Vote | null>(initial);
  const [sending, setSending] = useState<Vote | null>(null);

  async function send(v: Vote) {
    if (sending || vote === v) return;
    setSending(v);
    try {
      await sendFeedback(questionId, v);
      setVote(v);
      toast.success(v === "up" ? "Thanks. Marked as useful." : "Thanks. Marked as not useful.");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not record the feedback.");
    } finally {
      setSending(null);
    }
  }

  return (
    <div role="group" aria-label="Was this answer useful?" className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground" aria-hidden="true">
        Useful?
      </span>
      {(["up", "down"] as const).map((v) => {
        const Icon = v === "up" ? ThumbsUpIcon : ThumbsDownIcon;
        const pressed = vote === v;
        return (
          <button
            key={v}
            type="button"
            aria-pressed={pressed}
            disabled={sending !== null}
            onClick={() => send(v)}
            className={cn(
              btn,
              pressed ? "border-cite/50 bg-cite-wash text-cite-ink" : "border-input bg-sheet text-foreground hover:bg-muted",
            )}
          >
            <Icon className={cn("size-3.5", sending === v && "motion-safe:animate-pulse")} aria-hidden="true" />
            {v === "up" ? "Yes" : "No"}
          </button>
        );
      })}
    </div>
  );
}
