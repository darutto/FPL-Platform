"""run_trial_checks: a run that is done is not repeated and spends no call; an unfinished gameweek stops early."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import run_trial_checks  # noqa: E402


class Runner:
    """Stands in for every subprocess step and leaves the files the real steps leave."""

    def __init__(self, pkg: Path):
        self.pkg, self.calls = pkg, []

    def __call__(self, cmd, cwd, extra=None):
        self.calls.append([str(c) for c in cmd])
        text = " ".join(str(c) for c in cmd)
        if "live_capture.py" in text:
            target = self.pkg / "trial-output/capture/capture.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")
        if "live_trial_checks" in text:
            out = Path(str(cmd[cmd.index("--out") + 1]))
            out.mkdir(parents=True, exist_ok=True)
            (out / "aggregate.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

        class Result:
            returncode, stdout, stderr = 0, "", ""
        return Result()


def _run(tmp_path, tag="t", *, finished=lambda gw: True, runner=None, **kw):
    runner = runner or Runner(tmp_path)
    result = run_trial_checks.run(tag, 6, runner=runner, finished=finished, pkg=tmp_path, fi=tmp_path / "fi", **kw)
    return result, runner


def test_a_fresh_run_goes_through_every_step_and_leaves_its_marker(tmp_path):
    result, runner = _run(tmp_path)
    assert result == "done" and (tmp_path / "trial-output/runs/t/DONE").exists()
    joined = [" ".join(c) for c in runner.calls]
    assert any("trial_mapping.py" in c for c in joined) and any("live_capture.py" in c for c in joined)
    assert any("live_trial_checks" in c and "--holdout-gameweek 6" in c for c in joined)


def test_a_run_already_done_is_not_repeated_and_spends_no_call(tmp_path):
    _run(tmp_path)
    asked = []
    result, runner = _run(tmp_path, finished=lambda gw: asked.append(gw) or True)
    assert result == "already_done" and runner.calls == [] and asked == []


def test_force_redoes_a_done_run(tmp_path):
    _run(tmp_path)
    result, runner = _run(tmp_path, force=True)
    assert result == "done" and runner.calls


def test_an_unfinished_gameweek_stops_before_any_capture_and_leaves_no_marker(tmp_path):
    result, runner = _run(tmp_path, finished=lambda gw: False)
    assert result == "not_finished" and not (tmp_path / "trial-output/runs/t/DONE").exists()
    assert not any("live_capture" in " ".join(c) or "trial_mapping" in " ".join(c) for c in runner.calls)


def test_a_failed_step_leaves_no_marker_so_the_run_can_be_retried(tmp_path):
    class Boom(Runner):
        def __call__(self, cmd, cwd, extra=None):
            if "live_capture.py" in " ".join(str(c) for c in cmd):
                raise SystemExit("step failed")
            return super().__call__(cmd, cwd, extra)
    try:
        _run(tmp_path, runner=Boom(tmp_path))
    except SystemExit:
        pass
    assert not (tmp_path / "trial-output/runs/t/DONE").exists()
    assert _run(tmp_path)[0] == "done"


def test_update_false_skips_the_git_steps_and_default_does_them(tmp_path):
    _, runner = _run(tmp_path, "a", update=False)
    assert not any(c[0] == "git" for c in runner.calls)
    _, runner = _run(tmp_path, "b")
    assert [c[:2] for c in runner.calls if c[0] == "git"] == [["git", "fetch"], ["git", "checkout"]]


def test_the_leo_entry_is_passed_only_when_given(tmp_path):
    _, runner = _run(tmp_path, "a")
    assert not any("--leo-entry" in c for c in runner.calls)
    _, runner = _run(tmp_path, "b", leo_entry="68643")
    assert any("--leo-entry" in c and "68643" in c for c in runner.calls)


def test_the_exit_code_of_main_is_3_when_the_gameweek_is_not_finished(tmp_path, monkeypatch):
    monkeypatch.setattr(run_trial_checks, "run", lambda *a, **k: "not_finished")
    assert run_trial_checks.main(["t", "6"]) == run_trial_checks.EXIT_NOT_FINISHED
    monkeypatch.setattr(run_trial_checks, "run", lambda *a, **k: "done")
    assert run_trial_checks.main(["t", "6"]) == 0


def test_the_generated_snippets_are_valid_python():
    compile(run_trial_checks.PRECHECK.format(scripts="x", gw=6, code=3), "precheck", "exec")
    compile(run_trial_checks.BUILD.format(store="s", capture="c"), "build", "exec")
