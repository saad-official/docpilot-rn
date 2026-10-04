"""Versioned prompt files. A prompt change is a new file (`answer.v2.md`) plus a routing.toml
bump, so stored questions say exactly which prompt produced them (`name.vN@sha8`)."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib import resources


@lru_cache
def load_prompt(name: str, version: str = "v1") -> tuple[str, str]:
    """Return (text, id) where id is `name.version@sha8` of the file contents."""
    text = (resources.files("docpilot.prompts") / f"{name}.{version}.md").read_text(
        encoding="utf-8"
    )
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return text, f"{name}.{version}@{digest}"


def render(template: str, **values: str) -> str:
    """`{{name}}` placeholders (double braces so JSON and code in prompts stay literal)."""
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template
