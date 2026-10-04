# 0002 — Structure-aware chunking: headings as boundaries, 400-700 tokens, atomic code and tables

Date: 2026-10-05. Status: accepted.

## Context

Docs pages are written for people who scan headings. A chunk is both the unit that gets
embedded and the unit a citation links to, so it should be "one section, about one thing,
with a URL that lands on it". Fixed-size windows (every 512 tokens, 50 overlap) ignore that:
they cut code samples in half, separate a table from its header row, and produce citations
that point at the middle of an unrelated section.

## Decision (`src/docpilot/ingest/`)

1. **MDX reduction first** (`mdx.py`): imports/exports removed; `<Terminal>` becomes a
   `sh` block of its npm commands; `<Tabs>/<Tab>` become labelled text; `<Collapsible>`
   keeps its summary; `<ConfigPluginProperties>` becomes a Markdown table;
   `<APIInstallSection>` becomes the install command; `<APISection>` becomes one sentence
   pointing at the generated API reference; RN partials (`_foo.md`) are inlined. Code fences
   are copied verbatim (Expo's `/* @info */` annotations stripped), so JSX inside code is
   never mistaken for a component.
2. **Headings are boundaries** (`parse.py`): every H2-H6 starts a section with a
   `heading_path` (`Notifications › Usage › Handle push notifications`) and a GitHub-style
   anchor (`#handle-push-notifications-with-navigation`, Docusaurus `{#custom-id}` honoured,
   duplicates suffixed `-1`), which becomes the citation URL.
3. **Blocks**: prose paragraphs, fenced code, tables. Prose may be split at sentence or
   list-item boundaries; **code blocks and tables are never split**. One larger than 700
   tokens becomes its own chunk with its heading (measured: 8 such chunks in SDK 58, 32 in
   React Native, mostly long examples) - half a code sample is worse than an oversized chunk.
   It also absorbs a short lead-in paragraph so "Check out the example below" is not left
   as a 50-token fragment.
4. **Budget 400-700 tokens** (`tiktoken` `o200k_base`): blocks pack greedily to 700;
   neighbouring small sections under the same H2 merge while the chunk is under 400, with
   the common parent as heading path and anchor. The page intro (with the frontmatter
   description) may absorb the first section.
5. **Overlap = one heading sentence**: continuation chunks of a long section start with the
   section heading and its first sentence, so every chunk says what it is about.
6. **What is embedded** is `title + heading path + content`; the content hash of that text
   keys the embedding cache, and chunk ids derive from (document, anchor, hash), so an
   unchanged chunk keeps its id across re-ingests.

## Results (dry runs, 2026-10-05)

| Corpus | Pages | Chunks | Tokens | Avg | Oversized atomic |
|---|---|---|---|---|---|
| Expo v58.0.0 | 249 | 877 | 278k | 317 | 8 |
| Expo v57.0.0 | 246 | 833 | 261k | 313 | 7 |
| Expo unversioned | 444 | 2,432 | 811k | 333 | 23 |
| React Native current | 225 | 889 | 339k | 381 | 32 |

The average sits under 400 because Expo reference pages are many short H2 sections and
merging stops at an H2 boundary on purpose (a merged chunk spanning "Installation" and
"Permissions" would cite the wrong anchor for half its content).

## Consequences / open

- The spec asks for a chunk-size vs recall@5 measurement. Not run yet: each variant means
  re-embedding the corpus, which the free Gemini quota (1,000 texts/day) makes a multi-day
  job. Full-text-only variants could be measured without embeddings; listed as an open item.
- `<APISection>` content (the TypeDoc-generated method and type reference) lives in JSON
  under `docs/public/static/data/<version>/`, not in MDX. It is not ingested yet, so
  signature-level questions ("what does `scheduleNotificationAsync` return") rely on the
  prose and examples. The biggest known recall gap; open item.
