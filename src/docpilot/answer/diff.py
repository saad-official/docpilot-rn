""" "What changed?" mode: a structured diff between two versions, then prose rendered by code.

The model fills `DiffAnswer` (strict JSON schema; every field required, absent values are
`null` rather than missing - Groq's strict mode and Gemini both accept that shape, while
optional keys are rejected or ignored by one of them). The prose the user reads is
rendered from the validated object, so every bullet carries the citations the verifier
checked, and a second generation call (another ~6k tokens against an 8K-per-minute free
tier) is not needed.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

ChangeKind = Literal["added", "removed", "renamed", "behaviour"]


class DiffChange(BaseModel):
    kind: ChangeKind
    subject: str = Field(description="The API, option or feature that changed")
    before: str | None = Field(description="What the older version says; null if absent")
    after: str | None = Field(description="What the newer version says; null if absent")
    citations: list[int] = Field(description="Passage numbers supporting this change")


class DiffAnswer(BaseModel):
    summary: str = Field(description="2-4 sentences for someone upgrading, citing [n]")
    changes: list[DiffChange]
    missing: str | None = Field(description="What the passages lack, or null")


KIND_LABEL = {"added": "Added", "removed": "Removed", "renamed": "Renamed", "behaviour": "Changed"}


def clean_diff(diff: DiffAnswer, valid: Sequence[int]) -> tuple[DiffAnswer, int]:
    """Drop citation numbers that name no passage, and changes left with none.

    Returns the cleaned diff and how many changes were dropped as unsupported.
    """
    allowed = set(valid)
    kept: list[DiffChange] = []
    dropped = 0
    for change in diff.changes:
        cites = [n for n in dict.fromkeys(change.citations) if n in allowed]
        if not cites:
            dropped += 1
            continue
        kept.append(change.model_copy(update={"citations": cites}))
    return diff.model_copy(update={"changes": kept}), dropped


def _inline(text: str | None) -> str:
    return re.sub(r"\s+", " ", text).strip() if text else "-"


def render_diff(diff: DiffAnswer, before_label: str, after_label: str) -> str:
    lines = [diff.summary.strip()]
    if diff.changes:
        lines += ["", f"**{before_label} → {after_label}**", ""]
        for change in diff.changes:
            cites = "".join(f"[{n}]" for n in change.citations)
            label = KIND_LABEL.get(change.kind, "Changed")
            if change.kind == "added":
                detail = _inline(change.after)
            elif change.kind == "removed":
                detail = _inline(change.before)
            else:
                detail = f"{_inline(change.before)} → {_inline(change.after)}"
            lines.append(f"- **{label}** {change.subject.strip()}: {detail} {cites}".rstrip())
    elif diff.missing:
        lines += ["", diff.missing.strip()]
    return "\n".join(lines).strip()


def version_key(version: str) -> tuple[int, ...]:
    """'v58.0.0' -> (58, 0, 0); anything else sorts last."""
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", version)
    return tuple(int(g) for g in match.groups()) if match else (10**6,)


def order_versions(a: str, b: str) -> tuple[str, str]:
    """(older, newer), whichever order the user sent them in."""
    return (a, b) if version_key(a) <= version_key(b) else (b, a)
