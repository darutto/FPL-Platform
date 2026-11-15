"""The workflow's switch gates the schedule only: a manual smoke must not require turning the cron on."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "licensed-ingestion.yml"


def _job() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["ingest"]


def _evaluate(condition: str, event_name: str, enabled: str | None) -> bool:
    """The only expression forms the gate may use: ``a == 'x'`` / ``a != 'x'`` joined by ``||``."""
    context = {"github.event_name": event_name, "vars.LICENSED_INGEST_ENABLED": enabled}
    inner = re.fullmatch(r"\$\{\{\s*(.*?)\s*\}\}", condition.strip()).group(1)
    for clause in inner.split("||"):
        left, op, literal = re.fullmatch(r"\s*([\w.]+)\s*(==|!=)\s*'([^']*)'\s*", clause).groups()
        if (context[left] == literal) == (op == "=="):
            return True
    return False


@pytest.mark.parametrize("event,enabled,runs", [
    ("schedule", None, False),
    ("schedule", "false", False),
    ("schedule", "TRUE", False),
    ("schedule", "true", True),
    ("workflow_dispatch", None, True),
    ("workflow_dispatch", "false", True),
    ("workflow_dispatch", "true", True),
])
def test_the_switch_gates_only_the_schedule(event, enabled, runs):
    assert _evaluate(_job()["if"], event, enabled) is runs


def test_nothing_else_in_the_workflow_depends_on_the_switch():
    text = WORKFLOW.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert code.count("LICENSED_INGEST_ENABLED") == 1
    assert code.count("if:") == 1   # only the job-level condition: no step re-gates a manual run


def test_a_scheduled_run_publishes_and_a_manual_run_uses_the_chosen_mode():
    run = next(s["run"] for s in _job()["steps"] if s.get("name") == "Run the pass")
    assert 'if [ "$EVENT_NAME" = "schedule" ]; then\n  MODE=publish' in run
    assert 'MODE="$INPUT_MODE"' in run


def test_a_backfill_can_be_chosen_by_hand_and_is_never_scheduled():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert "backfill" in workflow[True]["workflow_dispatch"]["inputs"]["pass"]["options"]
    run = next(s["run"] for s in _job()["steps"] if s.get("name") == "Run the pass")
    scheduled = run.split('else\n  MODE="$INPUT_MODE"')[0]
    assert "backfill" not in scheduled     # the schedule branch names its passes itself: daily, deadline, matchday
