"""FI-8 S2: the trial harness, the frozen contract, and the live-call guard.

Everything S3-S6 inherit without re-reading is pinned here: the report schema,
the four-status enum, the exit codes, the `--out` default, the gitignore rule,
and byte-stability of mock output.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import trial_auth  # noqa: E402
from _trial_common import (  # noqa: E402
    DEFAULT_OUT, EXAMPLES_DIR, EXIT_CONFIG, EXIT_OK, EXIT_REFUSED, EXIT_UNMET,
    MODE_LIVE, MODE_MOCK, NOT_APPLICABLE, OBSERVED, PACKAGE_ROOT, STATUSES,
    Objective, ReplayTransport, TrialReport, build_parser, make_client,
    render_markdown, resolve_mode, response, write_report,
)
from sportmonks_client.config import SportmonksConfig

REPO_ROOT = PACKAGE_ROOT.parent.parent


# --- The guard ----------------------------------------------------------------

def test_the_guard_fires_on_a_real_session_request():
    """The seeded violation, made permanent.

    Attempts the boundary itself -- `requests.Session().request(...)` -- rather
    than a `RequestsTransport` construction, so the proof matches what is
    guarded. Without the autouse fixture in conftest.py this call would attempt
    real network I/O.
    """
    with pytest.raises(AssertionError, match="live network call attempted"):
        requests.Session().request("GET", "https://api.sportmonks.com/v3/football/leagues")


def test_the_guard_covers_the_adapter_entry_point_too():
    with pytest.raises(AssertionError, match="live network call attempted"):
        requests.adapters.HTTPAdapter().send(requests.Request("GET", "https://x.test").prepare())


def test_default_client_construction_cannot_reach_the_network(monkeypatch):
    """The path the guard most needs to catch: no injected transport, so the
    client builds a real RequestsTransport around a real Session."""
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TOKEN")
    client = make_client(MODE_LIVE)
    with pytest.raises(AssertionError, match="live network call attempted"):
        client.leagues()


# --- Mode resolution and refusal ----------------------------------------------

def test_mock_is_the_default_mode():
    assert resolve_mode(build_parser("t").parse_args([])) == MODE_MOCK
    assert resolve_mode(build_parser("t").parse_args(["--mock"])) == MODE_MOCK


def test_live_without_acknowledgement_is_refused(capsys):
    assert trial_auth.main(["--live"]) == EXIT_REFUSED
    assert capsys.readouterr().out.startswith("REFUSED:")


def test_live_with_acknowledgement_resolves_to_live():
    args = build_parser("t").parse_args(["--live", "--i-understand-this-is-live"])
    assert resolve_mode(args) == MODE_LIVE


def test_mock_and_live_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        build_parser("t").parse_args(["--mock", "--live"])


# --- Token wiring (plan §14.1) ------------------------------------------------

def test_token_absent_degrades_cleanly(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    code = trial_auth.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path)])
    assert code == EXIT_CONFIG
    out = capsys.readouterr().out
    assert out.startswith("CONFIG: SportmonksConfigurationError")
    assert "Traceback" not in out


def test_dummy_token_surfaces_auth_failure_without_leaking_it(monkeypatch, tmp_path, capsys):
    token = "DUMMY-TRIAL-TOKEN"
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", token)
    monkeypatch.setattr(
        trial_auth, "make_client",
        lambda mode, **kw: __import__("_trial_common").make_client(
            mode, transport=ReplayTransport([response({}, status=401)]),
            config=SportmonksConfig(api_token=token), out_dir=kw.get("out_dir"),
        ),
    )
    code = trial_auth.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path)])
    assert code == EXIT_CONFIG
    printed = capsys.readouterr().out
    assert printed.startswith("AUTH: SportmonksAuthenticationError")
    assert token not in printed


# --- Pagination and rate-limit observation (objective 17) ---------------------

def test_mock_run_walks_pages_and_observes_rate_limit_headers(tmp_path):
    assert trial_auth.main(["--out", str(tmp_path)]) == EXIT_OK
    payload = json.loads((tmp_path / "reports" / "trial_auth.json").read_text(encoding="utf-8"))
    objective = payload["objectives"][0]
    assert objective["id"] == 17 and objective["status"] == OBSERVED
    assert "pages" in objective["evidence"]
    assert any(s["name"] == "rate_limit_headers" for s in payload["observed_shapes"])


# --- The frozen report schema -------------------------------------------------

def test_report_schema_keys_are_exactly_the_frozen_set(tmp_path):
    trial_auth.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / "trial_auth.json").read_text(encoding="utf-8"))
    assert list(payload) == ["script", "mode", "objectives", "observed_shapes", "warnings"]
    assert list(payload["objectives"][0]) == ["id", "title", "status", "evidence"]
    assert list(payload["observed_shapes"][0]) == ["name", "shape"]


def test_status_enum_is_exactly_four_and_excludes_not_started():
    assert STATUSES == ("observed", "unmet", "degraded", "not_applicable")
    assert "not_started" not in STATUSES


def test_objective_rejects_a_status_outside_the_frozen_four():
    with pytest.raises(ValueError, match="frozen four"):
        Objective(1, "x", "not_started")


def test_exit_code_mapping_is_the_frozen_one():
    ok = TrialReport("t", MODE_MOCK, [Objective(1, "a", OBSERVED)])
    assert ok.exit_code() == EXIT_OK
    skipped = TrialReport("t", MODE_MOCK, [Objective(1, "a", NOT_APPLICABLE)])
    assert skipped.exit_code() == EXIT_OK, "not_applicable is not a failure"
    for failing in ("unmet", "degraded"):
        assert TrialReport("t", MODE_MOCK, [Objective(1, "a", failing)]).exit_code() == EXIT_UNMET


# --- Artifact locations -------------------------------------------------------

def test_out_defaults_to_the_gitignored_trial_output_directory():
    assert build_parser("t").parse_args([]).out == DEFAULT_OUT
    assert DEFAULT_OUT.name == "trial-output"


def test_trial_output_is_gitignored_after_a_run_that_wrote_there():
    assert trial_auth.main([]) == EXIT_OK
    assert (DEFAULT_OUT / "reports" / "trial_auth.json").exists()
    tracked = subprocess.run(
        ["git", "ls-files", "packages/sportmonks-client/trial-output/"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert tracked == "", f"trial-output/ must never be tracked; found: {tracked}"


def test_no_raw_snapshot_payload_is_tracked_anywhere():
    tracked = subprocess.run(
        ["git", "ls-files", "packages/sportmonks-client/"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    assert not [p for p in tracked if "/raw/" in p or "trial-output" in p]


def test_raw_snapshots_land_under_trial_output(tmp_path):
    trial_auth.main(["--out", str(tmp_path)])
    snapshots = list((tmp_path / "raw").glob("*.json"))
    assert snapshots, "the snapshot hook must write raw payloads"
    assert "leagues" in snapshots[0].name


# --- Byte-stability -----------------------------------------------------------

def test_mock_output_is_byte_stable_across_runs(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    trial_auth.main(["--out", str(first)])
    trial_auth.main(["--out", str(second)])
    for name in ("trial_auth.json", "trial_auth.md"):
        assert (first / "reports" / name).read_bytes() == (second / "reports" / name).read_bytes()


def test_committed_example_matches_a_fresh_mock_run(tmp_path):
    """The committed example is evidence only while it matches. If this fails,
    regenerate it in the same change that altered the schema."""
    trial_auth.main(["--out", str(tmp_path)])
    for name in ("trial_auth.json", "trial_auth.md"):
        fresh = (tmp_path / "reports" / name).read_text(encoding="utf-8")
        committed = (EXAMPLES_DIR / name).read_text(encoding="utf-8")
        assert fresh == committed, f"{name} drifted from trial-reports/examples/"


def test_report_carries_no_timestamp_field(tmp_path):
    """Byte-stability is structural, not conventional: the frozen schema has no
    time field, so nothing needs freezing at render time."""
    trial_auth.main(["--out", str(tmp_path)])
    text = (tmp_path / "reports" / "trial_auth.json").read_text(encoding="utf-8")
    assert "generated_at" not in text and "timestamp" not in text
    assert "T00:00:00" not in render_markdown(TrialReport("t", MODE_MOCK))


# --- Harness plumbing ---------------------------------------------------------

def test_write_report_emits_both_artifacts(tmp_path):
    report = TrialReport("demo", MODE_MOCK, [Objective(1, "a", OBSERVED, "e")])
    json_path, md_path = write_report(report, tmp_path)
    assert json_path.name == "demo.json" and md_path.name == "demo.md"
    assert "| 1 | a | `observed` | e |" in md_path.read_text(encoding="utf-8")


def test_mock_mode_requires_an_injected_transport():
    with pytest.raises(ValueError, match="requires an injected transport"):
        make_client(MODE_MOCK)
