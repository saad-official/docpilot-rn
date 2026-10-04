"""What to ingest from each upstream repository, and how a file path becomes a public URL.

    expo  --version v58.0.0      docs/pages/versions/v58.0.0/**.mdx
    expo  --version unversioned  docs/pages/**.mdx minus versions/, ja/, internal/, archive/
    react-native --version current   docs/**.md(x) of react/react-native-website

URLs (what a citation links to):

    https://docs.expo.dev/versions/v58.0.0/sdk/notifications/#setup
    https://docs.expo.dev/router/installation/
    https://reactnative.dev/docs/flatlist#renderitem
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import Sdk

DOC_EXTENSIONS = (".md", ".mdx")
EXPO_EXCLUDED_TOP = ("versions/", "ja/", "internal/", "archive/")
VERSION_RE = re.compile(r"^(v\d+\.\d+\.\d+|unversioned|current)$")


@dataclass(frozen=True)
class SourceSpec:
    sdk: Sdk
    repo: str
    licence: str
    attribution_url: str
    root: str  # repository directory that holds the docs

    def prefix(self, version: str) -> str:
        """Repository path whose subtree is downloaded for `version`."""
        if self.sdk == "expo" and version != "unversioned":
            return f"{self.root}/versions/{version}/"
        return f"{self.root}/"

    def include(self, version: str, repo_path: str) -> bool:
        """Is this repository file part of the corpus (or a partial it needs)?"""
        prefix = self.prefix(version)
        if not repo_path.startswith(prefix) or not repo_path.endswith(DOC_EXTENSIONS):
            return False
        rel = repo_path[len(prefix) :]
        if self.sdk == "expo" and version == "unversioned":
            return not rel.startswith(EXPO_EXCLUDED_TOP)
        return True

    def is_partial(self, rel_path: str) -> bool:
        """RN's `_foo.md` files are fragments included by other pages, not pages."""
        return rel_path.rsplit("/", 1)[-1].startswith("_")

    def page_url(self, version: str, rel_path: str, frontmatter: dict | None = None) -> str:
        """Public URL of a page (no anchor). `rel_path` is relative to `prefix(version)`."""
        frontmatter = frontmatter or {}
        stem = re.sub(r"\.mdx?$", "", rel_path)
        if self.sdk == "expo":
            stem = re.sub(r"(^|/)index$", "", stem)
            base = "https://docs.expo.dev/"
            if version != "unversioned":
                base += f"versions/{version}/"
            return base + (f"{stem}/" if stem else "")
        # Docusaurus: the URL segment is the frontmatter `slug` or `id`, else the file name.
        directory, _, name = stem.rpartition("/")
        slug = frontmatter.get("slug")
        if isinstance(slug, str) and slug.startswith("/"):
            return "https://reactnative.dev/docs" + slug.rstrip("/")
        doc_id = str(slug or frontmatter.get("id") or name)
        return "https://reactnative.dev/docs/" + (f"{directory}/" if directory else "") + doc_id


SOURCES: dict[str, SourceSpec] = {
    "expo": SourceSpec(
        sdk="expo",
        repo="expo/expo",
        licence="MIT",
        attribution_url="https://github.com/expo/expo/tree/main/docs",
        root="docs/pages",
    ),
    "react-native": SourceSpec(
        sdk="react-native",
        repo="react/react-native-website",
        licence="CC-BY-4.0",
        attribution_url="https://github.com/react/react-native-website",
        root="docs",
    ),
}


def validate_version(sdk: str, version: str) -> None:
    if not VERSION_RE.match(version):
        raise ValueError(
            f"version must look like v58.0.0, 'unversioned' or 'current', got {version!r}"
        )
    if sdk == "react-native" and version != "current":
        raise ValueError("react-native is ingested as version 'current' only (spec section 3)")
    if sdk == "expo" and version == "current":
        raise ValueError("expo versions are v<major>.0.0 or 'unversioned'")
