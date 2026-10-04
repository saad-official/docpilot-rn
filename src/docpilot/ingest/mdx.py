"""MDX -> plain Markdown: keep what a reader sees, drop what only a bundler needs.

Expo's and React Native's docs are MDX: Markdown plus JSX components and ES imports. An
embedding model and a full-text index want the *text*, so each component is reduced to the
text or commands it renders:

    <Terminal cmd={['$ npx expo install expo-notifications']} />   -> a ```sh block
    <Tabs><Tab label="Expo Router"> ... </Tab></Tabs>                -> "**Expo Router:**" + body
    <Collapsible summary="Manual setup"> ... </Collapsible>          -> "**Manual setup**" + body
    <ConfigPluginProperties properties={[{ name, platform, ... }]} /> -> a Markdown table
    <APISection packageName="expo-notifications" />                  -> one sentence pointing
                                                                        at the API reference
    <APIInstallSection />                                            -> the install command
    import ... / export ...                                          -> removed

Code fences are copied verbatim (minus Expo's `/* @info */` annotation comments), so a
`<View>` inside a code sample is never mistaken for a component.

Why a hand-written line scanner instead of an MDX parser: the real parser is JavaScript
(`@mdx-js/mdx`), and a Python port would still need a per-component policy, which is the
part that matters. The scanner is ~300 lines, tested against real pages, and degrades
safely: an unknown component keeps its children and drops its tag.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from dataclasses import dataclass, field

FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
EXPO_ANNOTATION_RE = re.compile(r"\s*/\*\s*@(?:info|end|hide|tutinfo)\b.*?\*/", re.DOTALL)
JSX_COMMENT_RE = re.compile(r"\{/\*.*?\*/\}", re.DOTALL)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")
SELF_CLOSING_INLINE_RE = re.compile(r"<([A-Z][\w.]*)\b(?:[^<>{}]|\{[^{}]*\})*/>")
OPEN_CLOSE_INLINE_RE = re.compile(r"</?([A-Za-z][\w.]*)\b(?:[^<>{}]|\{[^{}]*\})*>")
JSX_SPACE_RE = re.compile(r"\{\s*['\"`](\s*)['\"`]\s*\}")
ADMONITION_RE = re.compile(r"^\s*:::\s*(\w+)?\s*(.*)$")
STRING_LITERAL_RE = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"|`((?:[^`\\$]|\\.)*)`")

# Components whose tags are dropped while their children are kept (layout wrappers).
TRANSPARENT = {
    "Tabs",
    "Step",
    "Steps",
    "SnackInline",
    "ConfigReactNative",
    "ConfigClassic",
    "Prerequisites",
    "ContentSpotlight",
    "Callout",
    "Container",
    "Grid",
    "Row",
    "Col",
    "TabsGroup",
    "PaddedAPIBox",
    "Badge",
}


@dataclass
class ReduceContext:
    """Page-level facts some components need (APIInstallSection uses the package name)."""

    package_name: str | None = None
    # RN docs import partials (`import Foo from './_foo.md'`) and render `<Foo />`.
    # Given a relative path, return the partial's raw text (or None when unknown).
    resolve_partial: Callable[[str], str | None] | None = None
    partials: dict[str, str] = field(default_factory=dict)  # component name -> path
    depth: int = 0


def js_strings(raw: str) -> list[str]:
    """Every string literal in a JS expression, in order, unescaped."""
    out: list[str] = []
    for match in STRING_LITERAL_RE.finditer(raw):
        value = next(group for group in match.groups() if group is not None)
        out.append(value.replace("\\'", "'").replace('\\"', '"').replace("\\n", "\n"))
    return out


def _balanced_end(text: str, start: int, open_char: str, close_char: str) -> int:
    """Index just past the bracket matching text[start] (quote-aware); -1 if unbalanced."""
    depth = 0
    quote: str | None = None
    i = start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
        elif ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def parse_attributes(raw: str) -> dict[str, str]:
    """`label="X" cmd={[...]} hidden` -> {"label": "X", "cmd": "[...]", "hidden": "true"}."""
    attrs: dict[str, str] = {}
    i = 0
    while i < len(raw):
        match = re.compile(r"\s*([A-Za-z_][\w-]*)").match(raw, i)
        if not match:
            i += 1
            continue
        name = match.group(1)
        i = match.end()
        if i < len(raw) and raw[i] == "=":
            i += 1
            if i < len(raw) and raw[i] in "'\"":
                end = raw.find(raw[i], i + 1)
                end = len(raw) if end == -1 else end
                attrs[name] = raw[i + 1 : end]
                i = end + 1
            elif i < len(raw) and raw[i] == "{":
                end = _balanced_end(raw, i, "{", "}")
                end = len(raw) if end == -1 else end
                attrs[name] = raw[i + 1 : end - 1].strip()
                i = end
        else:
            attrs[name] = "true"
    return attrs


def _top_level_objects(raw: str) -> list[str]:
    """The `{...}` object literals directly inside an array literal."""
    objects: list[str] = []
    i = raw.find("[")
    if i == -1:
        return objects
    i += 1
    while i < len(raw):
        if raw[i] == "{":
            end = _balanced_end(raw, i, "{", "}")
            if end == -1:
                break
            objects.append(raw[i + 1 : end - 1])
            i = end
        else:
            i += 1
    return objects


_KV_RE = re.compile(
    r"(\w+)\s*:\s*("
    r"(?:'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|`(?:[^`\\]|\\.)*`)"
    r"(?:\s*\+\s*(?:'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|`(?:[^`\\]|\\.)*`))*"
    r"|true|false|-?\d+(?:\.\d+)?|\[[^\]]*\])"
)


def js_object_fields(raw: str) -> dict[str, str]:
    """Flat key/value pairs of a JS object literal; string concatenations are joined."""
    fields: dict[str, str] = {}
    for key, value in _KV_RE.findall(raw):
        if key in fields:
            continue
        if value.startswith("["):
            fields[key] = ", ".join(js_strings(value))
        elif value[:1] in "'\"`":
            fields[key] = "".join(js_strings(value))
        else:
            fields[key] = value
    return fields


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _terminal(attrs: dict[str, str]) -> list[str]:
    raw = attrs.get("cmd", "")
    if raw.startswith("{"):  # {{ npm: [...], yarn: [...] }}: the npm variant is enough
        npm = re.search(r"\bnpm\s*:\s*\[", raw)
        if npm:
            start = raw.index("[", npm.start())
            end = _balanced_end(raw, start, "[", "]")
            raw = raw[start:end]
        else:
            first = raw.find("[")
            raw = raw[first : _balanced_end(raw, first, "[", "]")] if first != -1 else raw
    commands = [line[2:] if line.startswith("$ ") else line for line in js_strings(raw)]
    if not commands:
        return []
    return ["```sh", *commands, "```"]


def _config_properties(attrs: dict[str, str]) -> list[str]:
    rows = [js_object_fields(obj) for obj in _top_level_objects(attrs.get("properties", ""))]
    rows = [row for row in rows if row.get("name")]
    if not rows:
        return []
    lines = ["| Name | Default | Platform | Description |", "| --- | --- | --- | --- |"]
    for row in rows:
        default = row.get("default", "")
        lines.append(
            f"| `{_cell(row['name'])}` | {('`' + _cell(default) + '`') if default else '-'} "
            f"| {_cell(row.get('platform', '')) or '-'} | {_cell(row.get('description', ''))} |"
        )
    return lines


def _self_closing(name: str, attrs: dict[str, str], ctx: ReduceContext) -> list[str]:
    """Text for a component with no children."""
    if name == "Terminal":
        return _terminal(attrs)
    if name == "ConfigPluginProperties":
        return _config_properties(attrs)
    if name == "APIInstallSection":
        package = attrs.get("packageName") or ctx.package_name
        if not package:
            return []
        return [f"Install the package with `npx expo install {package}`."]
    if name == "APISection":
        package = attrs.get("packageName") or ctx.package_name or "this library"
        api_name = attrs.get("apiName")
        label = f"`{package}`" + (f" (`{api_name}`)" if api_name else "")
        return [
            f"API reference for {label}: methods, hooks, components, types and constants "
            "are listed in the API section of this page."
        ]
    if name in ("AndroidPermissions", "IOSPermissions"):
        perms = js_strings(attrs.get("permissions", ""))
        platform = "Android" if name.startswith("Android") else "iOS"
        return [f"{platform} permissions: {', '.join(perms)}."] if perms else []
    if name == "FileTree":
        files = js_strings(attrs.get("files", ""))
        return ["```text", *files, "```"] if files else []
    if name in ("BoxLink", "VideoBoxLink"):
        title, href = attrs.get("title"), attrs.get("href")
        description = attrs.get("description", "")
        if title and href:
            return [f"See [{title}]({href}){': ' + description if description else ''}"]
        return []
    if name in ctx.partials and ctx.resolve_partial and ctx.depth < 2:
        partial = ctx.resolve_partial(ctx.partials[name])
        if partial:
            nested = ReduceContext(
                package_name=ctx.package_name,
                resolve_partial=ctx.resolve_partial,
                depth=ctx.depth + 1,
            )
            return reduce_mdx(strip_frontmatter(partial), nested).splitlines()
    # Anything else: keep human-readable string attributes, if any.
    for key in ("title", "summary", "label", "caption", "description"):
        if attrs.get(key):
            return [attrs[key]]
    return []


def _opening(name: str, attrs: dict[str, str]) -> list[str]:
    """Text emitted where a block component with children opens."""
    if name in ("Tab", "TabItem"):
        label = attrs.get("label") or attrs.get("value")
        return [f"**{label}:**", ""] if label else []
    if name == "Collapsible":
        summary = attrs.get("summary")
        return [f"**{summary}**", ""] if summary else []
    if name == "Requirement":
        title = attrs.get("title")
        return [f"**{title}**", ""] if title else []
    return []


def clean_inline(line: str) -> str:
    """Strip inline JSX/HTML tags outside inline code, unescape entities."""
    parts: list[str] = []
    last = 0
    for match in INLINE_CODE_RE.finditer(line):
        parts.append(_clean_text(line[last : match.start()]))
        parts.append(match.group(0))
        last = match.end()
    parts.append(_clean_text(line[last:]))
    return "".join(parts)


def _clean_text(text: str) -> str:
    text = JSX_SPACE_RE.sub(r"\1", text)
    text = SELF_CLOSING_INLINE_RE.sub("", text)
    text = OPEN_CLOSE_INLINE_RE.sub("", text)
    return html.unescape(text).replace(" ", " ").replace("\xa0", " ")


def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[text.find("\n", end + 1) + 1 :] if "\n" in text[end + 1 :] else ""
    return text


def _is_statement_complete(statement: str) -> bool:
    """An import/export statement is complete once its brackets balance."""
    depth = 0
    for ch in statement:
        if ch in "{([":
            depth += 1
        elif ch in "})]":
            depth -= 1
    return depth <= 0


_IMPORT_PARTIAL_RE = re.compile(r"^import\s+(\w+)\s+from\s+['\"](\./[^'\"]+\.mdx?)['\"]")


def reduce_mdx(body: str, ctx: ReduceContext | None = None) -> str:
    """Reduce an MDX body (frontmatter already removed) to Markdown text."""
    ctx = ctx or ReduceContext()
    body = body.replace("\r\n", "\n")
    lines = body.split("\n")
    out: list[str] = []
    fence: str | None = None
    i = 0

    def emit_text(line: str) -> None:
        out.append(clean_inline(line))

    pending: list[str] = []  # remainder of a line after a tag, processed next
    while i < len(lines) or pending:
        if pending:
            line = pending.pop(0)
        else:
            line = lines[i]
            i += 1

        # ---- inside a code fence: verbatim, minus Expo annotations ----------------
        if fence is not None:
            match = FENCE_RE.match(line)
            if match and match.group(2).startswith(fence) and not match.group(3).strip():
                fence = None
                out.append(line.strip())
                continue
            cleaned = EXPO_ANNOTATION_RE.sub("", line)
            if cleaned.strip() or not line.strip():
                out.append(cleaned.rstrip())
            continue

        match = FENCE_RE.match(line)
        if match:
            fence = match.group(2)
            out.append(f"{match.group(2)}{match.group(3)}".rstrip())
            continue

        stripped = line.strip()

        # ---- ES module statements ---------------------------------------------------
        if re.match(r"^(import|export)\s", stripped) and not line.startswith((" ", "\t")):
            statement = stripped
            while not _is_statement_complete(statement) and i < len(lines):
                statement += "\n" + lines[i]
                i += 1
            partial = _IMPORT_PARTIAL_RE.match(statement)
            if partial:
                ctx.partials[partial.group(1)] = partial.group(2)
            continue

        # ---- comments ----------------------------------------------------------------
        if stripped.startswith(("{/*", "<!--")):
            closer = "*/}" if stripped.startswith("{/*") else "-->"
            buffer = line
            while closer not in buffer and i < len(lines):
                buffer += "\n" + lines[i]
                i += 1
            rest = buffer[buffer.find(closer) + len(closer) :]
            if rest.strip():
                pending.insert(0, rest)
            continue

        # ---- Docusaurus admonitions (:::note Title ... :::) -------------------------
        admonition = ADMONITION_RE.match(line)
        if admonition:
            kind, title = admonition.group(1), admonition.group(2).strip()
            if kind:
                out.append(f"**{kind.capitalize()}:** {title}".rstrip())
            continue

        # ---- block-level JSX component tags -------------------------------------------
        tag_start = re.match(r"^(\s*)<(/?)([A-Z][\w.]*)", line)
        if tag_start:
            buffer = line[len(tag_start.group(1)) :]
            end = _tag_end(buffer)
            while end == -1 and i < len(lines):
                buffer += "\n" + lines[i]
                i += 1
                end = _tag_end(buffer)
            if end == -1:
                end = len(buffer)
            tag = buffer[:end]
            rest = buffer[end:]
            closing = tag_start.group(2) == "/"
            name = tag_start.group(3)
            self_closing = tag.rstrip().endswith("/>")
            if not closing:
                inner = tag[len(name) + 1 : -2 if self_closing else -1]
                attrs = parse_attributes(inner)
                emitted = (
                    _self_closing(name, attrs, ctx)
                    if self_closing
                    else ([] if name in TRANSPARENT else _opening(name, attrs))
                )
                out.extend(emitted)
            if rest.strip():
                pending.insert(0, rest)
            continue

        emit_text(line)

    text = "\n".join(out)
    text = JSX_COMMENT_RE.sub("", text)
    text = HTML_COMMENT_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def _tag_end(buffer: str) -> int:
    """Index just past the `>` closing the tag that starts at buffer[0]; -1 if not yet."""
    depth = 0
    quote: str | None = None
    i = 1
    while i < len(buffer):
        ch = buffer[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif (ch in "'\"`" and depth > 0) or ch == '"' or ch == "'":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == ">" and depth == 0:
            return i + 1
        i += 1
    return -1
