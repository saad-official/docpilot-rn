import pytest

from docpilot.retrieval import query as q
from docpilot.retrieval.fusion import BOOST_CAP, BOOST_HEADING, api_boost, order, rrf
from docpilot.retrieval.sql import (
    fulltext_search_sql,
    vector_literal,
    vector_search_sql,
    versions_for,
)


def test_rrf_rewards_agreement_over_a_single_first_place():
    scores = rrf({"vector": ["a", "b", "c"], "fulltext": ["c", "b", "x"]})
    assert scores["a"] == pytest.approx(1 / 61)
    assert scores["b"] == pytest.approx(2 / 62)
    assert scores["c"] == pytest.approx(1 / 63 + 1 / 61)
    assert order(scores)[:2] == ["c", "b"]  # 0.03227 vs 0.03226: agreement either way


def test_order_breaks_ties_by_id():
    assert order({"b": 1.0, "a": 1.0, "c": 2.0}) == ["c", "a", "b"]


def test_api_boost_prefers_headings_and_is_capped():
    assert api_boost(["useRouter"], "Router › useRouter", "body") == BOOST_HEADING
    assert api_boost(["useRouter"], "Router", "call useRouter()") == pytest.approx(0.008)
    assert api_boost(["a", "b", "c"], "a b c", "") == BOOST_CAP
    assert api_boost([], "anything", "anything") == 0.0


def test_api_names_and_fulltext_queries():
    question = "How do I use useRouter from expo-router and set it in app.json for SplashScreen?"
    assert q.api_names(question) == ["useRouter", "expo-router", "app.json", "SplashScreen"]
    english = q.english_query(question)
    assert english.startswith("userouter or expo-router")
    assert " or how " not in f" {english} "  # stop words dropped
    assert q.simple_query(question) == "userouter or expo-router or app.json or splashscreen"
    assert q.english_query('-rf "quoted"') == "rf or quoted"


def test_versions_filter():
    assert versions_for("expo", "v58.0.0") == ["v58.0.0", "unversioned"]
    assert versions_for("expo", "v58.0.0", include_shared=False) == ["v58.0.0"]
    assert versions_for("react-native", "current") == ["current"]


def test_sql_builders_parameterise_everything():
    sql, params = vector_search_sql("expo", ["v58.0.0", "unversioned"], [0.5, 0.25], 40)
    assert "ORDER BY c.embedding <=> %(q)s::vector" in sql
    assert "c.version = ANY(%(versions)s)" in sql
    assert params == {
        "q": "[0.5,0.25]",
        "sdk": "expo",
        "versions": ["v58.0.0", "unversioned"],
        "limit": 40,
    }
    sql, params = fulltext_search_sql(
        "expo", ["v58.0.0"], "push or token", "expo-notifications", 40
    )
    assert "websearch_to_tsquery('english', %(english)s)" in sql
    assert "websearch_to_tsquery('simple', %(simple)s)" in sql
    assert "c.tsv @@ q.qe OR c.tsv_simple @@ q.qs" in sql
    assert params["english"] == "push or token" and params["simple"] == "expo-notifications"
    assert vector_literal([1.0, 1e-9]) == "[1,1e-09]"
