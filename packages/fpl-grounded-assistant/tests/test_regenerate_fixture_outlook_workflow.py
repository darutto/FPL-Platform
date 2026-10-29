"""
Regression guard: the weekly /fixtures regeneration must DELIVER its bundle.

Until 2026-10-28 regenerate-fixture-outlook.yml ended at upload-artifact. Every
run succeeded, the regenerated bundle expired as an artifact, and prod kept
serving the 2026-09-10 file (gameweeks_played=3) while the league was at GW8.
These assertions pin the delivery path so it cannot silently be dropped again.
"""
from __future__ import annotations

import os
import re

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), *[".."] * 3))
_WORKFLOW = os.path.join(_REPO, ".github", "workflows", "regenerate-fixture-outlook.yml")


def _text() -> str:
    with open(_WORKFLOW, encoding="utf-8") as fh:
        return fh.read()


def test_workflow_can_write_contents_and_open_prs():
    text = _text()
    assert re.search(r"^permissions:\n(?:  .*\n)*?  contents: write", text, re.M)
    assert re.search(r"^permissions:\n(?:  .*\n)*?  pull-requests: write", text, re.M)


def test_bundle_is_pushed_to_a_bot_branch_and_pr_opened():
    text = _text()
    assert "BUNDLE_BRANCH: bot/fixture-outlook" in text
    assert 'git push --force origin "${BUNDLE_BRANCH}"' in text
    assert "gh pr create" in text


def test_delivery_is_gated_on_a_real_diff():
    text = _text()
    assert "steps.bundle.outputs.changed == 'true'" in text
    assert "git diff --quiet -- 'packages/fpl-ui/lib/data/fixture-outlook-*.json'" in text


def test_never_pushes_to_main_never_stages_everything_never_auto_merges():
    text = _text()
    assert "HEAD:main" not in text
    assert not re.search(r"git add (-A|--all|\.)(\s|$)", text)
    assert "gh pr merge" not in text


def test_only_the_bundle_files_are_staged():
    text = _text()
    assert "git add -- packages/fpl-ui/lib/data/fixture-outlook-*.json" in text
