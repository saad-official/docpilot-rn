import { cn } from "@/lib/utils";
import { sourceLabel, versionLabel } from "@/lib/format";

export type VersionTone = "selected" | "plain" | "before" | "after";

const tones: Record<VersionTone, string> = {
  selected: "border-version/45 bg-version-wash text-version-ink",
  plain: "border-border bg-sheet text-pencil",
  before: "border-removed/50 bg-removed-wash text-removed-ink",
  after: "border-added/50 bg-added-wash text-added-ink",
};

/**
 * A docs version in mono: "Expo SDK 58". The selected version is teal; in
 * "What changed?" the older version is amber and the newer one green.
 */
export function VersionBadge({
  sdk,
  version,
  tone = "selected",
  withSource = true,
  className,
  title,
}: {
  sdk: string;
  version: string;
  tone?: VersionTone;
  withSource?: boolean;
  className?: string;
  title?: string;
}) {
  const label = versionLabel(sdk, version);
  return (
    <span
      className={cn(
        "figure inline-flex h-6 shrink-0 items-center gap-1.5 rounded-sm border px-2 text-xs font-medium whitespace-nowrap",
        tones[tone],
        className,
      )}
      title={title ?? (label !== version ? version : undefined)}
    >
      {withSource ? <span className="font-sans font-semibold">{sourceLabel(sdk)}</span> : null}
      <span>{label}</span>
    </span>
  );
}
