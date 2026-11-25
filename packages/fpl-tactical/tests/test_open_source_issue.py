"""The one GitHub issue for a shot-source problem: created once, refreshed after that."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "open_source_issue.py"
_spec = importlib.util.spec_from_file_location("open_source_issue_under_test", _SCRIPT)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


class Recorder:
    def __init__(self, open_issues):
        self.open_issues, self.posts = open_issues, []

    def __call__(self, method, url, token, body=None):
        if method == "GET":
            return self.open_issues
        self.posts.append((url, body))
        return {}


def test_no_open_issue_creates_one_with_the_plain_title():
    rec = Recorder([{"number": 4, "title": "something else"}])
    assert mod.open_or_refresh("o/r", "t", "detail", rec) == "created"
    url, body = rec.posts[0]
    assert url.endswith("/repos/o/r/issues") and body["title"] == "shot source down or changed"


def test_an_open_issue_with_that_title_gets_a_comment_not_a_duplicate():
    rec = Recorder([{"number": 7, "title": "shot source down or changed"}])
    assert mod.open_or_refresh("o/r", "t", "detail", rec) == "refreshed"
    assert [u for u, _ in rec.posts] == ["https://api.github.com/repos/o/r/issues/7/comments"]


def test_a_pull_request_with_the_same_title_is_not_the_issue():
    rec = Recorder([{"number": 9, "title": "shot source down or changed", "pull_request": {}}])
    assert mod.open_or_refresh("o/r", "t", "detail", rec) == "created"
