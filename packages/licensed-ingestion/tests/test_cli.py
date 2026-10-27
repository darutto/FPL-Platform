"""The CLI: modes, caps, refusals, and that no name, id or token reaches the output on any path (public logs)."""
from __future__ import annotations

import json

import pytest

from football_intelligence.distribution.keys import pointer_key
from football_intelligence.distribution.store import InMemoryArtifactStore
from football_intelligence.ingestion.licensed.store import POINTER_NAME
from licensed_ingestion import __main__ as cli
from licensed_ingestion import recording
from licensed_ingestion.__main__ import main
from licensed_ingestion.fetch import planned_calls

TOKEN = "synthetic-token-never-printed"
REMOTE_ENV = {"FPL_FOOTBALL_REMOTE_ENDPOINT": "https://r2.invalid", "FPL_FOOTBALL_REMOTE_BUCKET": "private-bucket",
              "FPL_FOOTBALL_REMOTE_ACCESS_KEY_ID": "synthetic-key-id", "FPL_FOOTBALL_REMOTE_SECRET_ACCESS_KEY": "synthetic-secret"}


def _cli(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def _summary(stdout):
    (line,) = stdout.strip().splitlines()
    return json.loads(line)


def _assert_clean(*texts):
    text = "\n".join(texts)
    assert sorted(i for i in recording.identifiers() if i in text) == []
    for secret in (TOKEN, *REMOTE_ENV.values()):
        assert secret not in text


# --------------------------------------------------------------- --dry-run

def test_dry_run_is_the_default_and_prints_the_planned_calls_and_their_number(tmp_path, capsys):
    code, out, err = _cli(capsys, "--pass", "daily", "--work-dir", str(tmp_path))
    summary = _summary(out)
    assert code == 0 and err == ""
    assert summary["mode"] == "dry-run" and summary["status"] == "built" and summary["published"] is False
    assert summary["planned_calls"] == 64 and summary["planned_requests"] == planned_calls("daily")
    assert summary["cap"] == 120 and summary["calls"] == 10    # the recording has two clubs


@pytest.mark.parametrize("kind,planned,cap", [("daily", 64, 120), ("matchday", 1, 10), ("deadline", 1, 10)])
def test_dry_run_of_every_pass_needs_no_work_dir_and_leaves_nothing_behind(capsys, kind, planned, cap):
    now = {"daily": [], "matchday": ["--now", "2026-10-24T13:00:00Z"], "deadline": ["--now", "2026-10-24T09:30:00Z"]}[kind]
    code, out, err = _cli(capsys, "--pass", kind, "--dry-run", *now)
    summary = _summary(out)
    assert (code, err, summary["status"]) == (0, "", "built")
    assert summary["planned_calls"] == planned and summary["cap"] == cap


def test_dry_run_never_reads_the_token_or_the_remote_config(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", TOKEN)
    for name, value in REMOTE_ENV.items():
        monkeypatch.setenv(name, value)

    def boom(*args, **kwargs):
        raise AssertionError("the dry run read the environment")

    monkeypatch.setattr("sportmonks_client.config.SportmonksConfig.from_env", boom)
    monkeypatch.setattr("sportmonks_client.config.SportmonksConfig.require_token", boom)
    monkeypatch.setattr("football_intelligence.distribution.config.RemoteStoreConfig.from_env", boom)
    code, out, err = _cli(capsys, "--pass", "daily", "--work-dir", str(tmp_path))
    assert code == 0 and err == ""
    _assert_clean(out, err)


def test_a_matchday_with_nothing_to_watch_makes_zero_calls(capsys):
    code, out, _ = _cli(capsys, "--pass", "matchday", "--now", "2026-10-26T13:00:00Z")
    summary = _summary(out)
    assert code == 0 and summary["status"] == "skipped" and summary["calls"] == 0 and summary["planned_calls"] == 1


# --------------------------------------------------------------- the cap

def test_a_cap_below_what_the_pass_needs_stops_before_the_next_call(tmp_path, capsys):
    code, out, err = _cli(capsys, "--pass", "daily", "--max-calls", "3", "--work-dir", str(tmp_path))
    assert code == 3 and err.strip() == "FAILED BudgetExceeded"
    assert _summary(out) == {"calls": 3, "cap": 3, "mode": "dry-run", "pass": "daily", "status": "budget_exceeded"}


@pytest.mark.parametrize("kind,max_calls", [("daily", "0"), ("daily", "121"), ("matchday", "11"), ("deadline", "11"),
                                           ("matchday", "-1")])
def test_a_cap_outside_the_pass_ceiling_is_refused(capsys, kind, max_calls):
    code, out, _ = _cli(capsys, "--pass", kind, "--max-calls", max_calls)
    assert code == 2 and _summary(out) == {"reason": "max_calls_out_of_range", "status": "refused"}


def test_the_ceiling_itself_is_accepted(capsys):
    code, out, _ = _cli(capsys, "--pass", "daily", "--max-calls", "120")
    assert code == 0 and _summary(out)["cap"] == 120


# --------------------------------------------------------------- modes and refusals

def test_modes_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit) as stop:
        main(["--pass", "daily", "--smoke", "--publish"])
    assert stop.value.code == 2
    capsys.readouterr()


@pytest.mark.parametrize("mode", ["--smoke", "--publish"])
def test_now_is_dry_run_only(capsys, mode):
    code, out, _ = _cli(capsys, "--pass", "daily", mode, "--now", "2026-10-24T12:00:00Z")
    assert code == 2 and _summary(out) == {"reason": "now_is_dry_run_only", "status": "refused"}


@pytest.mark.parametrize("mode", ["--smoke", "--publish"])
def test_a_live_mode_without_a_token_fails_before_any_network_read(capsys, mode):
    code, out, err = _cli(capsys, "--pass", "daily", mode)
    assert code == 1 and out == "" and err.strip() == "FAILED SportmonksConfigurationError"


def test_publish_without_the_remote_config_is_refused_before_any_read(capsys, monkeypatch):
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", TOKEN)
    code, out, err = _cli(capsys, "--pass", "daily", "--publish")
    assert code == 2 and _summary(out) == {"reason": "publish_needs_remote_config", "status": "refused"}
    _assert_clean(out, err)


# --------------------------------------------------------------- --smoke and --publish on a fake provider

@pytest.fixture
def live(monkeypatch):
    """Live modes against the recording: the provider transport, the FPL feed, the clock and the bucket are fakes."""
    from datetime import datetime

    from licensed_ingestion import fpl

    class Frozen(datetime):
        now_value = recording.NOW

        @classmethod
        def now(cls, tz=None):
            return cls.now_value

    store = InMemoryArtifactStore()
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", TOKEN)
    for name, value in REMOTE_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(fpl, "load_feed", lambda *a, **k: recording.FEED)
    monkeypatch.setattr("sportmonks_client.transport.RequestsTransport", lambda **kw: recording.RecordedTransport())
    monkeypatch.setattr("football_intelligence.distribution.store.S3ArtifactStore", lambda config: store)
    monkeypatch.setattr(cli, "datetime", Frozen)
    return store, Frozen


def test_smoke_reads_builds_and_publishes_nothing(capsys, live):
    store, _ = live
    code, out, err = _cli(capsys, "--pass", "daily", "--smoke", "--max-calls", "70")
    summary = _summary(out)
    assert code == 0 and err == "" and summary["mode"] == "smoke"
    assert summary["published"] is False and summary["calls"] == 10 and summary["cap"] == 70
    assert store.head(pointer_key(cli.PREFIX, POINTER_NAME)) is None
    _assert_clean(out, err)


def test_publish_then_a_matchday_pass_builds_on_the_published_daily(capsys, live):
    store, frozen = live
    code, out, _ = _cli(capsys, "--pass", "daily", "--publish")
    assert code == 0 and _summary(out)["published"] is True
    assert store.head(pointer_key(cli.PREFIX, POINTER_NAME)) is not None
    frozen.now_value = recording.NOW.replace(hour=13)
    code, out, err = _cli(capsys, "--pass", "matchday", "--publish")
    summary = _summary(out)
    assert code == 0 and summary["calls"] == 1 and summary["published"] is True and summary["rows"]["lineup_slots"] > 8
    _assert_clean(out, err)


def test_a_live_matchday_with_no_kickoff_in_range_skips_without_a_provider_call(capsys, live):
    _, frozen = live
    frozen.now_value = recording.NOW.replace(day=27)
    code, out, _ = _cli(capsys, "--pass", "matchday", "--smoke")
    assert code == 0 and _summary(out)["status"] == "skipped" and _summary(out)["calls"] == 0


def test_a_matchday_with_no_published_baseline_fails_with_the_type_only(capsys, live):
    _, frozen = live
    frozen.now_value = recording.NOW.replace(hour=13)
    code, out, err = _cli(capsys, "--pass", "matchday", "--smoke")
    assert code == 1 and out == "" and err.strip() == "FAILED NoBaseline"


# --------------------------------------------------------------- public logs

def test_no_name_id_or_token_reaches_the_output_on_any_path(tmp_path, capsys, monkeypatch):
    runs = [("--pass", "daily", "--work-dir", str(tmp_path)),
            ("--pass", "matchday", "--work-dir", str(tmp_path), "--now", "2026-10-24T13:00:00Z"),
            ("--pass", "deadline", "--work-dir", str(tmp_path), "--now", "2026-10-24T09:30:00Z"),
            ("--pass", "matchday", "--work-dir", str(tmp_path), "--now", "2026-10-26T13:00:00Z"),
            ("--pass", "daily", "--max-calls", "3", "--work-dir", str(tmp_path / "capped")),
            ("--pass", "daily", "--max-calls", "999")]
    outputs = [_cli(capsys, *args) for args in runs]
    assert [code for code, _, _ in outputs] == [0, 0, 0, 0, 3, 2]
    # Forced error deep in the pass: a recorded answer goes missing (the provider answers 404).
    broken = {k: v for k, v in recording.PROVIDER.items() if not k.startswith("squads/")}
    with monkeypatch.context() as patch:
        patch.setattr(recording.RecordedTransport.__init__, "__defaults__", (broken,))
        failed = _cli(capsys, "--pass", "daily", "--work-dir", str(tmp_path / "broken"))
    assert failed[0] == 1 and failed[1] == "" and failed[2].strip() == "FAILED SportmonksRequestError"
    # Forced error in the derivation: an exception whose message carries a name must never be printed.
    def leaky(*args, **kwargs):
        raise ValueError("Arlo Quintavalle 780001")

    monkeypatch.setattr("licensed_ingestion.run.derive", leaky)
    leaked = _cli(capsys, "--pass", "daily", "--work-dir", str(tmp_path / "leaky"))
    assert leaked[0] == 1 and leaked[2].strip() == "FAILED ValueError"
    _assert_clean(*(o + e for _, o, e in [*outputs, failed, leaked]))
