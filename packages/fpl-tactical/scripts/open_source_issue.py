"""Open (or refresh) the ONE GitHub issue for a shot-source problem.

    python scripts/open_source_issue.py [--detail "text"]

Needs GITHUB_TOKEN and GITHUB_REPOSITORY (both set in Actions). Deduplicates
by exact title: an open issue with the title gets a comment, otherwise one is
created. The title is plain on purpose; the detail goes in the body and never
contains a key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

TITLE = "shot source down or changed"
API = "https://api.github.com"


def _request(method: str, url: str, token: str, body: dict | None = None):
    req = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "python-client",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https host
        return json.loads(resp.read().decode("utf-8"))


def open_or_refresh(repo: str, token: str, detail: str, request=_request) -> str:
    """Return ``"created"`` or ``"refreshed"``."""
    q = urllib.parse.urlencode({"state": "open", "per_page": 100})
    for issue in request("GET", f"{API}/repos/{repo}/issues?{q}", token):
        if issue.get("title") == TITLE and "pull_request" not in issue:
            request("POST", f"{API}/repos/{repo}/issues/{issue['number']}/comments", token, {"body": detail})
            return "refreshed"
    request("POST", f"{API}/repos/{repo}/issues", token, {"title": TITLE, "body": detail})
    return "created"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", default="The daily shot refresh failed. See the workflow run.")
    args = ap.parse_args(argv)
    token, repo = os.environ.get("GITHUB_TOKEN", ""), os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        print("GITHUB_TOKEN and GITHUB_REPOSITORY are required", file=sys.stderr)
        return 2
    run = os.environ.get("GITHUB_RUN_ID")
    detail = args.detail + (f"\n\nRun: https://github.com/{repo}/actions/runs/{run}" if run else "")
    print(open_or_refresh(repo, token, detail))
    return 0


if __name__ == "__main__":
    sys.exit(main())
