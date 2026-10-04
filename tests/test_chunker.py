from docpilot.ingest.chunker import MAX_TOKENS, chunk_page, merge_small, section_pieces
from docpilot.ingest.parse import Block, Section, parse_page
from docpilot.tokens import ApproxCounter

COUNTER = ApproxCounter()  # 4 chars per token: easy arithmetic


def chunks_for(raw: str, url: str = "https://docs.expo.dev/x/"):
    return chunk_page(
        parse_page("x.mdx", raw), sdk="expo", version="v58.0.0", url=url, counter=COUNTER
    )


def test_code_block_larger_than_budget_is_never_split():
    code = "```ts\n" + "\n".join(f"const line{i} = {i};" for i in range(400)) + "\n```"
    chunks = chunks_for(f"---\ntitle: T\n---\n## Big\n\nShort lead-in.\n\n{code}\n\nAfter.\n")
    holding = [c for c in chunks if "const line0 = 0;" in c.content]
    assert len(holding) == 1
    assert "const line399 = 399;" in holding[0].content
    assert holding[0].content.count("```") == 2
    assert holding[0].tokens > MAX_TOKENS
    # The short lead-in is absorbed by the oversized atomic block, not left alone.
    assert "Short lead-in." in holding[0].content


def test_tables_stay_whole():
    rows = "\n".join(f"| `opt{i}` | something about option {i} |" for i in range(60))
    chunks = chunks_for(f"---\ntitle: T\n---\n## Options\n\n| Name | Desc |\n| - | - |\n{rows}\n")
    table_chunks = [c for c in chunks if "| Name | Desc |" in c.content]
    assert len(table_chunks) == 1 and "`opt59`" in table_chunks[0].content


def test_long_prose_splits_under_budget_with_heading_sentence_overlap():
    sentence = "Expo Router uses files in the app directory as routes for every screen. "
    body = sentence * 120  # ~2,200 tokens at 4 chars/token
    chunks = chunks_for(f"---\ntitle: Router\n---\n## Routing\n\n{body}\n")
    assert len(chunks) >= 3
    assert all(c.tokens <= MAX_TOKENS for c in chunks)
    assert all(c.content.startswith("## Routing") for c in chunks)
    assert all("(continued) Expo Router uses files" in c.content for c in chunks[1:])
    assert all(c.url == "https://docs.expo.dev/x/#routing" for c in chunks)


def test_small_sibling_sections_merge_under_their_parent():
    raw = (
        "---\ntitle: T\n---\n## API\n\n### a\n\nAlpha text.\n\n### b\n\nBeta text.\n\n"
        "## Other\n\nX.\n"
    )
    chunks = chunks_for(raw)
    api = [c for c in chunks if "Alpha" in c.content]
    assert len(api) == 1 and "Beta text." in api[0].content
    assert api[0].heading_path == "T › API"
    assert api[0].url.endswith("#api")
    # Different H2: not merged into the API chunk.
    assert "X." not in api[0].content


def test_merge_respects_max_tokens():
    pieces = []
    for name in ("a", "b"):
        section = Section(
            ["T", "H2", name], 3, name, [Block("prose", "w " * 1200)], [None, "h2", name]
        )
        pieces.extend(section_pieces(section, COUNTER))
    assert len(merge_small(pieces)) == len(pieces)


def test_chunk_ids_are_stable_and_content_hashed():
    raw = "---\ntitle: T\n---\nIntro text.\n\n## One\n\nBody one.\n"
    first, second = chunks_for(raw), chunks_for(raw)
    assert [c.id for c in first] == [c.id for c in second]
    changed = chunks_for(raw.replace("Body one.", "Body two."))
    assert first[-1].content_hash != changed[-1].content_hash
    assert first[-1].embed_text.startswith("T\nT")
