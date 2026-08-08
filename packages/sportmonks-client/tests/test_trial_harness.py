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

import _trial_common  # noqa: E402
import trial_auth  # noqa: E402
from _trial_common import (  # noqa: E402
    DEFAULT_OUT, DEGRADED, EXAMPLES_DIR, EXIT_CONFIG, EXIT_OK, EXIT_REFUSED,
    EXIT_UNMET, MODE_LIVE, MODE_MOCK, NOT_APPLICABLE, OBSERVED, PACKAGE_ROOT,
    STATUSES, Exchange, Objective, ObservingTransport, ReplayTransport,
    TrialReport, build_parser, make_client, observed_rate_limit_fields,
    observed_retry_after, render_markdown, resolve_mode, response, write_report,
)
from sportmonks_client.config import SportmonksConfig

REPO_ROOT = PACKAGE_ROOT.parent.parent


# --- The guard ----------------------------------------------------------------

#: Loopback with nothing listening. Every test that exercises the guard aims
#: here, never at the provider: if the guard ever regresses, the suite's failure
#: mode must be a refused local connection, not an authenticated-shaped GET to
#: api.sportmonks.com. The guard fires before any DNS or socket work, so the
#: host is irrelevant to the proof and entirely relevant to the blast radius.
LOOPBACK = "http://127.0.0.1:1"


def test_the_guard_fires_on_a_real_session_request():
    """The seeded violation, made permanent.

    Attempts the boundary itself -- `requests.Session().request(...)` -- rather
    than a `RequestsTransport` construction, so the proof matches what is
    guarded. Without the autouse fixture in conftest.py this call would attempt
    real network I/O; against LOOPBACK that is a refused connection, never a
    provider call.
    """
    with pytest.raises(AssertionError, match="live network call attempted"):
        requests.Session().request("GET", f"{LOOPBACK}/leagues")


def test_the_guard_covers_the_adapter_entry_point_too():
    with pytest.raises(AssertionError, match="live network call attempted"):
        requests.adapters.HTTPAdapter().send(requests.Request("GET", LOOPBACK).prepare())


def test_default_client_construction_cannot_reach_the_network(monkeypatch):
    """The path the guard most needs to catch: no injected transport, so the
    client builds a real RequestsTransport around a real Session.

    `base_url` is pointed at loopback so that if the guard regresses this test
    fails with a refused connection rather than sending a token-bearing request
    to the provider.
    """
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TOKEN")
    monkeypatch.setenv("SPORTMONKS_BASE_URL", LOOPBACK)
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
    """The token-leak half of DoD 4, asserted against real report bytes.

    The first version of this test returned before any report was written, so
    `token not in printed` ran against stdout that the preceding assertion had
    already pinned to a single fixed line -- it could not fail for any
    implementation. The failure paths now write a report, so there are bytes to
    check.
    """
    token = "DUMMY-TRIAL-TOKEN"
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", token)
    monkeypatch.setattr(
        trial_auth, "make_client",
        lambda mode, **kw: _trial_common.make_client(
            mode, transport=ReplayTransport([response({}, status=401)]),
            config=SportmonksConfig(api_token=token), out_dir=kw.get("out_dir"),
        ),
    )
    code = trial_auth.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path)])
    assert code == EXIT_CONFIG
    printed = capsys.readouterr().out
    assert printed.startswith("AUTH: SportmonksAuthenticationError")
    assert token not in printed

    report_bytes = (tmp_path / "reports" / "trial_auth.json").read_bytes()
    markdown_bytes = (tmp_path / "reports" / "trial_auth.md").read_bytes()
    assert report_bytes, "the auth-failure path must still write a report"
    assert token.encode() not in report_bytes
    assert token.encode() not in markdown_bytes


def test_the_leak_check_would_catch_a_token_in_the_report(tmp_path):
    """Proves the assertion above is not vacuous: a report that does contain the
    token fails the same check."""
    token = "DUMMY-TRIAL-TOKEN"
    leaky = TrialReport("trial_auth", MODE_MOCK, warnings=[f"api_token={token}"])
    write_report(leaky, tmp_path)
    assert token.encode() in (tmp_path / "reports" / "trial_auth.json").read_bytes()


# --- Pagination and rate-limit observation (objective 17) ---------------------

def _run(tmp_path, **kwargs):
    """Run trial_auth against a configurable mock transport and return its report."""
    if kwargs:
        original = trial_auth.mock_transport
        trial_auth.mock_transport = lambda: original(**kwargs)
    try:
        code = trial_auth.main(["--out", str(tmp_path)])
    finally:
        if kwargs:
            trial_auth.mock_transport = original
    return code, json.loads((tmp_path / "reports" / "trial_auth.json").read_text(encoding="utf-8"))


def test_mock_run_walks_pages_and_observes_rate_limit_headers(tmp_path):
    code, payload = _run(tmp_path)
    assert code == EXIT_OK
    objective = payload["objectives"][0]
    assert objective["id"] == 17 and objective["status"] == OBSERVED
    assert "x-ratelimit-limit, x-ratelimit-remaining, x-ratelimit-reset" in objective["evidence"]
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["rate_limit_headers"] == "x-ratelimit-limit, x-ratelimit-remaining, x-ratelimit-reset"


def test_removing_the_headers_degrades_the_objective_and_drops_the_shape(tmp_path):
    """Standing DoD item 10, made falsifiable.

    The first version of this slice passed this scenario unchanged: the evidence
    string and the shape entry were literals, so deleting every header left the
    report byte-identical. That defect was found by running this experiment, not
    by reading the code -- which is why it is now a required test rather than a
    review habit.
    """
    code, payload = _run(tmp_path, rate_limit_headers=False)
    objective = payload["objectives"][0]
    assert code == EXIT_UNMET
    assert objective["status"] == DEGRADED
    assert "no rate-limit headers present" in objective["evidence"]
    assert "rate-limit fields seen: none" in objective["evidence"]
    assert not [s for s in payload["observed_shapes"] if s["name"] == "rate_limit_headers"]


def test_synthetic_retry_after_is_observed_and_reported(tmp_path):
    """S2 DoD 5: a synthetic 429 carrying Retry-After, exercised and reported."""
    _, payload = _run(tmp_path)
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert "retry_after" in shapes
    assert "HTTP 429 retry-after=2" in shapes["retry_after"]
    assert "throttled responses: 1" in payload["objectives"][0]["evidence"]


def test_removing_the_throttle_drops_the_retry_shape_and_warns(tmp_path):
    _, payload = _run(tmp_path, throttle=False)
    assert not [s for s in payload["observed_shapes"] if s["name"] == "retry_after"]
    assert any("retry pacing is unmeasured" in w for w in payload["warnings"])
    assert "throttled responses: 0" in payload["objectives"][0]["evidence"]


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


#: These tests shell out to git. Outside a checkout -- inside the backend image,
#: for instance -- that is a missing precondition, not a failure of the slice.
requires_git = pytest.mark.skipif(
    not (REPO_ROOT / ".git").exists(), reason="not a git checkout"
)


def _git_ls_files(pathspec: str) -> list[str]:
    return subprocess.run(
        ["git", "ls-files", pathspec],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()


@requires_git
def test_trial_output_is_gitignored_after_a_run_that_wrote_there():
    assert trial_auth.main([]) == EXIT_OK
    assert (DEFAULT_OUT / "reports" / "trial_auth.json").exists()
    tracked = _git_ls_files("packages/sportmonks-client/trial-output/")
    assert tracked == [], f"trial-output/ must never be tracked; found: {tracked}"


@requires_git
def test_no_raw_snapshot_payload_is_tracked_anywhere():
    tracked = _git_ls_files("packages/sportmonks-client/")
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


def test_report_mode_comes_from_the_resolved_mode_not_a_proxy():
    """`mode` was previously derived from `transport is not None`, which labels a
    live run with an injected transport as `mock`. Same species as the literal
    evidence: inferring a fact from a proxy rather than reading it."""
    client = make_client(MODE_LIVE, transport=ReplayTransport(
        [response({"data": [], "meta": {"pagination": {"current_page": 1, "has_more": False}}})]
    ), config=SportmonksConfig(api_token="X"))
    assert trial_auth.collect(client, "live").mode == "live"


def test_observation_helpers_read_only_sanctioned_headers():
    exchanges = [Exchange(200, {"x-ratelimit-limit": "3000", "content-type": "application/json"})]
    assert observed_rate_limit_fields(exchanges) == ("x-ratelimit-limit",)
    assert observed_retry_after(exchanges) == ()
    assert observed_rate_limit_fields([Exchange(200, {})]) == ()


def test_observing_transport_drops_unsanctioned_headers():
    """Reports must never carry arbitrary provider headers -- the allowlist is
    the client's existing one, reused rather than redefined."""
    inner = ReplayTransport([response({"data": []}, headers={
        "X-RateLimit-Limit": "10", "Set-Cookie": "session=secret", "Authorization": "Bearer x",
    })])
    observer = ObservingTransport(inner)
    observer.request("GET", "https://host", params={}, timeout=1)
    assert dict(observer.exchanges[0].headers) == {"x-ratelimit-limit": "10"}
