"""search_web: premierleague.com first for player availability queries (httpx mocked, synthetic data)."""
from __future__ import annotations

import importlib
from typing import Any

import pytest

# the package re-exports the search_web FUNCTION under the module's name
sw = importlib.import_module("fpl_grounded_assistant.search_web")


class _Resp:
    status_code = 200
    text = ""

    def __init__(self, body: dict[str, Any]):
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


def _item(url: str, title: str = "t", score: float = 0.9) -> dict[str, Any]:
    return {"title": title, "content": "c", "url": url, "score": score, "published_date": None}


@pytest.fixture
def posts(monkeypatch: pytest.MonkeyPatch):
    """Capture every Tavily POST; the test fills `plan` with one body per call, in order."""
    monkeypatch.setenv("TAVILY_API_KEY", "synthetic-not-a-key")
    calls: list[dict[str, Any]] = []
    plan: list[dict[str, Any]] = []

    def fake_post(url, json=None, timeout=None):  # noqa: A002
        calls.append(json)
        return _Resp(plan[len(calls) - 1])

    monkeypatch.setattr(sw.httpx, "post", fake_post)
    return calls, plan


MAIN = {
    "answer": "synthetic answer",
    "results": [
        _item("https://x.com/someone/status/1", "social post", 0.99),
        _item("https://www.dongqiudi.com/news/1", "aggregator", 0.95),
        _item("https://www.skysports.com/a", "major outlet", 0.9),
        _item("https://example.test/blog", "unlisted", 0.85),
    ],
}


def test_player_availability_query_adds_a_pl_restricted_call_and_puts_it_first(posts, bootstrap):
    calls, plan = posts
    plan += [
        MAIN,
        {"results": [
            _item("https://www.premierleague.com/news/1?_gl=1*abc&_ga=2.3", "Saka official one"),
            _item("https://www.premierleague.com/news/2", "Saka official two"),
        ]},
    ]
    out = sw.search_web("Saka injury update", bootstrap=bootstrap)
    assert len(calls) == 2
    assert "include_domains" not in calls[0]
    assert calls[1]["include_domains"] == ["premierleague.com"]
    titles = [r["title"] for r in out["results"]]
    assert titles[:2] == ["Saka official one", "Saka official two"]
    # then major outlet, then unlisted, then social / aggregator (reorder only)
    assert titles[2:] == ["major outlet", "unlisted", "social post"]
    assert out["answer"] == "synthetic answer"


def test_tracking_parameters_are_cleaned_from_shown_urls(posts, bootstrap):
    calls, plan = posts
    plan += [
        {"results": [_item("https://example.test/a?utm_source=x&id=7&_gl=1*q&fbclid=z#part")]},
        {"results": []},
    ]
    out = sw.search_web("Saka injury news", bootstrap=bootstrap)
    assert out["results"][0]["url"] == "https://example.test/a?id=7#part"
    assert out["results"][0]["source"] == "example.test"


def test_duplicates_across_the_two_calls_collapse(posts, bootstrap):
    calls, plan = posts
    plan += [
        {"results": [_item("https://premierleague.com/news/1/", "Saka same page, main call"), _item("https://example.test/z", "other")]},
        {"results": [_item("https://www.premierleague.com/news/1?_ga=2.9", "Saka same page, pl call")]},
    ]
    out = sw.search_web("Saka injury update", bootstrap=bootstrap)
    assert [r["title"] for r in out["results"]] == ["Saka same page, pl call", "other"]


def test_empty_pl_results_fall_back_to_the_normal_ones(posts, bootstrap):
    calls, plan = posts
    plan += [MAIN, {"results": []}]
    out = sw.search_web("Saka injury update", bootstrap=bootstrap)
    assert len(calls) == 2
    assert [r["title"] for r in out["results"]] == ["major outlet", "unlisted", "social post", "aggregator"]


def test_a_failing_pl_call_never_breaks_the_search(posts, bootstrap, monkeypatch):
    calls, plan = posts
    state = {"n": 0}

    def flaky(url, json=None, timeout=None):  # noqa: A002
        state["n"] += 1
        if state["n"] == 2:
            raise sw.httpx.ConnectError("boom")
        return _Resp(MAIN)

    monkeypatch.setattr(sw.httpx, "post", flaky)
    out = sw.search_web("Saka injury update", bootstrap=bootstrap)
    assert [r["title"] for r in out["results"]][0] == "major outlet"


@pytest.mark.parametrize(
    "query",
    [
        "Premier League transfer news this week",     # no player
        "Saka stats goals assists",                    # a player, but no availability word
        "FPL gameweek deadline",                       # neither
    ],
)
def test_other_queries_make_one_call_only(posts, bootstrap, query):
    calls, plan = posts
    plan += [MAIN]
    out = sw.search_web(query, bootstrap=bootstrap)
    assert len(calls) == 1 and "include_domains" not in calls[0]
    assert len(out["results"]) == 4  # still ranked and cleaned, nothing blocked


def test_no_bootstrap_means_no_extra_call(posts):
    calls, plan = posts
    plan += [MAIN]
    sw.search_web("Saka injury update")
    assert len(calls) == 1


def test_handler_passes_the_bootstrap_through(posts, bootstrap):
    calls, plan = posts
    plan += [MAIN, {"results": []}]
    out = sw._search_web_handler({"query": "Saka injury update"}, bootstrap)
    assert out["status"] == "ok" and len(calls) == 2


def _pl(n: int, title: str, published=None, content: str = "c") -> dict[str, Any]:
    return {**_item(f"https://www.premierleague.com/news/{n}", title), "content": content, "published_date": published}


def test_irrelevant_official_pages_are_dropped(posts, bootstrap):
    calls, plan = posts
    plan += [MAIN, {"results": [
        _pl(1, "Team news for the derby"),
        _pl(2, "Predicted line-ups Matchweek 11"),
        _pl(3, "Saka fitness update"),
        _pl(4, "Preview", content="Arsenal are without two players"),  # club name in the content
    ]}]
    out = sw.search_web("Saka injury update", bootstrap=bootstrap)
    official = [r["title"] for r in out["results"] if "premierleague.com" in r["url"]]
    assert sorted(official) == ["Preview", "Saka fitness update"]


def test_official_pages_are_capped_at_two_and_general_results_fill_in(posts, bootstrap):
    calls, plan = posts
    plan += [MAIN, {"results": [_pl(i, f"Saka news {i}") for i in range(1, 6)]}]
    out = sw.search_web("Saka injury update", bootstrap=bootstrap)
    titles = [r["title"] for r in out["results"]]
    assert titles[:2] == ["Saka news 1", "Saka news 2"]
    assert titles[2:] == ["major outlet", "unlisted", "social post"]
    assert len(titles) == 5


def test_official_pages_in_the_general_call_are_filtered_and_capped_too(posts, bootstrap):
    calls, plan = posts
    plan += [
        {"results": [_pl(i, "Unrelated team news") for i in range(1, 4)] + [_item("https://example.test/ok", "kept")]},
        {"results": []},
    ]
    out = sw.search_web("Saka injury update", bootstrap=bootstrap)
    assert [r["title"] for r in out["results"]] == ["kept"]


def test_no_relevant_official_page_falls_back_to_general(posts, bootstrap):
    calls, plan = posts
    plan += [MAIN, {"results": [_pl(1, "Predicted line-ups"), _pl(2, "Team news for the derby")]}]
    out = sw.search_web("Saka injury update", bootstrap=bootstrap)
    assert [r["title"] for r in out["results"]] == ["major outlet", "unlisted", "social post", "aggregator"]


def test_recent_official_pages_come_first_when_dated(posts, bootstrap):
    calls, plan = posts
    plan += [MAIN, {"results": [
        _pl(1, "Saka old", "2026-08-01T10:00:00Z"),
        _pl(2, "Saka undated"),
        _pl(3, "Saka new", "2026-11-18T10:00:00Z"),
    ]}]
    out = sw.search_web("Saka injury update", bootstrap=bootstrap)
    assert [r["title"] for r in out["results"][:2]] == ["Saka new", "Saka old"]
    assert not any(r["title"] == "Saka undated" for r in out["results"])


@pytest.mark.parametrize(
    ("url", "tier"),
    [
        ("https://www.premierleague.com/x", 0),
        ("https://fantasy.premierleague.com/y", 0),  # a premierleague.com subdomain is official
        ("https://news.bbc.co.uk/z", 1),
        ("https://www.skysports.com/q", 1),
        ("https://example.test/p", 2),
        ("https://x.com/u/status/1", 3),
        ("https://www.dongqiudi.com/n", 3),
        ("https://notbbc.co.uk/p", 2),  # a suffix match must respect the dot boundary
    ],
)
def test_domain_tiers(url: str, tier: int):
    assert sw.domain_tier(url) == tier
