"""Download the docs of one repository at one pinned commit.

Two transports, same result (a {repo path: text} mapping for the selected files):

  tarball  `GET codeload.github.com/<repo>/tar.gz/<sha>`, streamed through `tarfile` in
           stream mode ("r|gz"): members are filtered as they pass and only matching files
           are kept in memory, so the archive never touches the disk. What the spec asks
           for, and the right choice on a fast link (GitHub Actions). Cost: the whole
           repository's bytes cross the wire - ~150 MB for react-native-website, several
           hundred MB for expo/expo.
  tree     Git Trees API for the docs subtree (2-4 API calls), then each file from
           `raw.githubusercontent.com/<repo>/<sha>/<path>` with a few parallel workers.
           Bytes proportional to the docs only (~10 MB). Measured 2026-10-04 on the
           development machine: the RN tarball took 10.6 min at 236 KB/s; the tree mode
           fetches the same docs in about a minute.

Both pin every file to one commit SHA (recorded on the corpus), so a re-run reproduces the
same corpus. Files land in a local cache (`.cache/sources/<repo>/<sha>/`) so a failed
ingestion resumes without re-downloading.
"""

from __future__ import annotations

import io
import logging
import tarfile
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

import httpx

log = logging.getLogger(__name__)

FetchMode = Literal["tarball", "tree"]
API = "https://api.github.com"
USER_AGENT = "docpilot-rn-ingest"


class FetchError(RuntimeError):
    pass


def _headers(token: str | None, accept: str = "application/vnd.github+json") -> dict[str, str]:
    headers = {"Accept": accept, "User-Agent": USER_AGENT, "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _check(response: httpx.Response, what: str) -> None:
    if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
        raise FetchError(
            f"GitHub rate limit hit while fetching {what}; set GITHUB_TOKEN (5,000 req/h)"
        )
    if response.status_code >= 400:
        raise FetchError(f"GitHub returned {response.status_code} for {what}")


def resolve_commit(
    client: httpx.Client, repo: str, ref: str = "main", token: str | None = None
) -> str:
    """The full SHA `ref` points at right now (the default: the tip of main)."""
    if len(ref) == 40 and all(c in "0123456789abcdef" for c in ref):
        return ref
    response = client.get(
        f"{API}/repos/{repo}/commits/{ref}",
        headers=_headers(token, "application/vnd.github.sha"),
    )
    _check(response, f"{repo}@{ref}")
    sha = response.text.strip()
    if len(sha) != 40:
        raise FetchError(f"unexpected commit response for {repo}@{ref}")
    return sha


class _StreamReader(io.RawIOBase):
    """A file-like view over an iterator of byte chunks (for tarfile's stream mode)."""

    def __init__(self, chunks: Iterator[bytes]):
        self._chunks = chunks
        self._buffer = b""

    def readable(self) -> bool:
        return True

    def readinto(self, target) -> int:  # type: ignore[no-untyped-def]
        while not self._buffer:
            try:
                self._buffer = next(self._chunks)
            except StopIteration:
                return 0
        n = min(len(target), len(self._buffer))
        target[:n] = self._buffer[:n]
        self._buffer = self._buffer[n:]
        return n


def fetch_tarball(
    client: httpx.Client,
    repo: str,
    sha: str,
    include: Callable[[str], bool],
    token: str | None = None,
) -> dict[str, str]:
    files: dict[str, str] = {}
    url = f"https://codeload.github.com/{repo}/tar.gz/{sha}"
    with client.stream("GET", url, headers=_headers(token, "*/*")) as response:
        _check(response, f"tarball {repo}@{sha[:7]}")
        reader = io.BufferedReader(_StreamReader(response.iter_bytes(1 << 16)), 1 << 20)
        with tarfile.open(fileobj=reader, mode="r|gz") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                # Members are "<repo>-<sha>/<path>"; drop the top directory.
                path = member.name.split("/", 1)[1] if "/" in member.name else member.name
                if not include(path):
                    continue
                handle = archive.extractfile(member)
                if handle is not None:
                    files[path] = handle.read().decode("utf-8", errors="replace")
    return files


def list_tree(
    client: httpx.Client, repo: str, sha: str, directory: str, token: str | None = None
) -> list[str]:
    """Every blob path under `directory` at `sha` (walks to the subtree, then recursive)."""
    tree_sha = sha
    for part in [p for p in directory.strip("/").split("/") if p]:
        response = client.get(f"{API}/repos/{repo}/git/trees/{tree_sha}", headers=_headers(token))
        _check(response, f"tree {repo}:{part}")
        entries = {e["path"]: e for e in response.json()["tree"]}
        if part not in entries or entries[part]["type"] != "tree":
            raise FetchError(f"{directory} not found in {repo}@{sha[:7]}")
        tree_sha = entries[part]["sha"]
    response = client.get(
        f"{API}/repos/{repo}/git/trees/{tree_sha}",
        params={"recursive": "1"},
        headers=_headers(token),
    )
    _check(response, f"tree {repo}:{directory}")
    body = response.json()
    if body.get("truncated"):
        raise FetchError(f"tree listing for {directory} was truncated; use --fetch tarball")
    base = directory.strip("/")
    return [f"{base}/{e['path']}" for e in body["tree"] if e["type"] == "blob"]


def fetch_tree(
    client: httpx.Client,
    repo: str,
    sha: str,
    directory: str,
    include: Callable[[str], bool],
    token: str | None = None,
    cache_dir: Path | None = None,
    workers: int = 8,
) -> dict[str, str]:
    paths = [p for p in list_tree(client, repo, sha, directory, token) if include(p)]

    def one(path: str) -> tuple[str, str]:
        cached = cache_dir / path if cache_dir else None
        if cached and cached.exists():
            return path, cached.read_text(encoding="utf-8")
        url = f"https://raw.githubusercontent.com/{repo}/{sha}/{path}"
        for attempt in range(4):
            try:
                response = client.get(url, headers={"User-Agent": USER_AGENT})
                if response.status_code < 500:
                    break
            except httpx.TransportError:
                if attempt == 3:
                    raise
        _check(response, path)
        text = response.text
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(text, encoding="utf-8")
        return path, text

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(one, paths))


def fetch_docs(
    repo: str,
    sha: str,
    directory: str,
    include: Callable[[str], bool],
    *,
    mode: FetchMode = "tarball",
    token: str | None = None,
    cache_root: Path | None = Path(".cache/sources"),
    client: httpx.Client | None = None,
) -> dict[str, str]:
    """{repository path: text} for every file under `directory` that `include` accepts."""
    cache_dir = cache_root / repo.replace("/", "__") / sha if cache_root else None
    subtree = directory.strip("/").replace("/", "__")
    marker = cache_dir / f".complete-{subtree}" if cache_dir else None
    if marker and marker.exists():  # a previous run fetched this subtree completely
        return {
            path.relative_to(cache_dir).as_posix(): path.read_text(encoding="utf-8")
            for path in cache_dir.rglob("*")
            if path.is_file()
            and not path.name.startswith(".complete")
            and path.relative_to(cache_dir).as_posix().startswith(directory)
            and include(path.relative_to(cache_dir).as_posix())
        }
    own = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(60.0, connect=20.0), follow_redirects=True)
    try:
        if mode == "tree":
            files = fetch_tree(http, repo, sha, directory, include, token, cache_dir)
        else:
            files = fetch_tarball(http, repo, sha, include, token)
            if cache_dir:
                for path, text in files.items():
                    target = cache_dir / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(text, encoding="utf-8")
        if marker:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(str(len(files)), encoding="utf-8")
        return files
    finally:
        if own:
            http.close()
