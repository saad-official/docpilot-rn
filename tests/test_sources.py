import pytest

from docpilot.ingest.sources import SOURCES, validate_version

EXPO = SOURCES["expo"]
RN = SOURCES["react-native"]


def test_expo_urls():
    assert EXPO.page_url("v58.0.0", "sdk/notifications.mdx") == (
        "https://docs.expo.dev/versions/v58.0.0/sdk/notifications/"
    )
    assert EXPO.page_url("v58.0.0", "index.mdx") == "https://docs.expo.dev/versions/v58.0.0/"
    assert EXPO.page_url("unversioned", "router/installation.mdx") == (
        "https://docs.expo.dev/router/installation/"
    )
    assert EXPO.page_url("unversioned", "guides/index.mdx") == "https://docs.expo.dev/guides/"


def test_rn_urls_use_id_or_slug():
    assert RN.page_url("current", "flatlist.md", {"id": "flatlist"}) == (
        "https://reactnative.dev/docs/flatlist"
    )
    assert RN.page_url("current", "the-new-architecture/pure-cxx-modules.md", {}) == (
        "https://reactnative.dev/docs/the-new-architecture/pure-cxx-modules"
    )
    assert RN.page_url("current", "x.md", {"slug": "/getting-started"}) == (
        "https://reactnative.dev/docs/getting-started"
    )


def test_include_rules():
    assert EXPO.include("v58.0.0", "docs/pages/versions/v58.0.0/sdk/camera.mdx")
    assert not EXPO.include("v58.0.0", "docs/pages/versions/v57.0.0/sdk/camera.mdx")
    assert not EXPO.include("v58.0.0", "docs/pages/versions/v58.0.0/sdk/camera.png")
    assert EXPO.include("unversioned", "docs/pages/router/installation.mdx")
    for excluded in ("versions/v58.0.0/a.mdx", "ja/a.mdx", "internal/a.mdx", "archive/a.mdx"):
        assert not EXPO.include("unversioned", f"docs/pages/{excluded}")
    assert RN.include("current", "docs/_partial.md") and RN.is_partial("_partial.md")


def test_version_validation():
    validate_version("expo", "v58.0.0")
    with pytest.raises(ValueError):
        validate_version("react-native", "v58.0.0")
    with pytest.raises(ValueError):
        validate_version("expo", "58")
