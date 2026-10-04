from docpilot.ingest.parse import Slugger, parse_frontmatter, parse_page, split_blocks


def test_frontmatter_title_description_platforms():
    page = parse_page(
        "sdk/camera.mdx",
        "---\ntitle: Camera\ndescription: Take photos.\nplatforms: ['ios', 'android']\n---\n"
        "\nBody.\n",
    )
    assert page.title == "Camera"
    assert page.description == "Take photos."
    assert page.platforms == ["ios", "android"]
    # The description opens the intro section.
    assert page.sections[0].blocks[0].text == "Take photos."


def test_bad_frontmatter_is_ignored():
    assert parse_frontmatter("---\n: : :\n---\n") == {}
    assert parse_frontmatter("no frontmatter") == {}


def test_heading_paths_and_anchors():
    raw = (
        "---\ntitle: Guide\n---\nIntro.\n\n## Setup\n\nA.\n\n### Android `useRouter`\n\nB.\n\n"
        "## Setup\n\nC.\n\n## Custom {#my-id}\n\nD.\n"
        '## <div className="label">Required</div> **`renderItem`**\n\nE.\n'
    )
    sections = parse_page("guide.mdx", raw).sections
    assert [s.heading_path for s in sections] == [
        ["Guide"],
        ["Guide", "Setup"],
        ["Guide", "Setup", "Android `useRouter`"],
        ["Guide", "Setup"],
        ["Guide", "Custom"],
        ["Guide", "Required `renderItem`"],
    ]
    assert [s.anchor for s in sections] == [
        None,
        "setup",
        "android-userouter",
        "setup-1",
        "my-id",
        "required-renderitem",
    ]
    assert sections[2].anchors == [None, "setup", "android-userouter"]


def test_headings_inside_code_are_not_headings():
    raw = "---\ntitle: T\n---\n## Real\n\n```sh\n# not a heading\n```\n"
    sections = parse_page("t.mdx", raw).sections
    assert len(sections) == 1 and sections[0].blocks[0].kind == "code"


def test_blocks_split_into_prose_code_table():
    blocks = split_blocks(
        ["Para one", "", "```js", "a()", "", "b()", "```", "| a | b |", "| - | - |", "| 1 | 2 |"]
    )
    assert [b.kind for b in blocks] == ["prose", "code", "table"]
    assert blocks[1].text == "```js\na()\n\nb()\n```"


def test_slugger_matches_github_style():
    slugger = Slugger()
    assert slugger.slug("Present a local (in-app) notification!") == (
        "present-a-local-in-app-notification"
    )
    assert slugger.slug("`expo-router` v4") == "expo-router-v4"
