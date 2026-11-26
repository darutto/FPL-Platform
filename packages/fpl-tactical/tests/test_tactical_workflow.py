"""The workflow's go-live gate: the schedule does nothing until the repository variable is set."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "tactical-store-refresh.yml"
GATE = "github.event_name == 'workflow_dispatch' || vars.TACTICAL_SHOTS_SOURCE == 'strikerapi'"


def load():
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return doc, doc.get("on", doc.get(True))  # YAML 1.1 reads the key `on` as True


def runs(job) -> str:
    return " ".join(step.get("run", "") for step in job["steps"])


def test_the_job_that_calls_the_source_or_opens_the_issue_is_gated():
    doc, _ = load()
    assert doc["jobs"]["refresh"]["if"] == GATE


def test_before_go_live_the_schedule_only_leaves_a_notice():
    doc, _ = load()
    waiting = doc["jobs"]["waiting"]
    assert waiting["if"] == f"!({GATE})"
    assert "::notice" in runs(waiting)
    assert not any(w in str(waiting) for w in ("strikerapi-", "open_source_issue", "STRIKERAPI_KEY", "secrets."))


def test_the_first_load_is_a_manual_mode_and_never_the_default():
    doc, on = load()
    mode = on["workflow_dispatch"]["inputs"]["mode"]
    assert mode["default"] == "sync" and mode["options"] == ["sync", "first-load"]
    steps = {s.get("name"): s for s in doc["jobs"]["refresh"]["steps"]}
    first = steps["First load (202 credits, manual)"]
    assert first["if"] == "env.MODE == 'first-load'" and "strikerapi-load" in first["run"]
    assert doc["jobs"]["refresh"]["env"]["MODE"] == "${{ github.event.inputs.mode || 'sync' }}"
    for name in ("Restore the working store from R2", "Sync what is due"):
        assert steps[name]["if"] == "env.MODE == 'sync'"


def test_every_command_that_spends_keeps_its_responses_on_r2():
    doc, _ = load()
    commands = [s["run"] for s in doc["jobs"]["refresh"]["steps"]
                if "cli strikerapi-" in s.get("run", "")]
    assert len(commands) == 2 and all("--require-r2" in c for c in commands)
