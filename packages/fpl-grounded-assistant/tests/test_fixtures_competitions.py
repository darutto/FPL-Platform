"""GET /fixtures/competitions: dev-gated data, server-side tier gating. No network.

The capture is synthetic and built in tmp: the real trial capture is local-only
and never enters the repo or a test.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import fpl_server
from fpl_grounded_assistant import competition_calendar as cc

REPO = Path(__file__).resolve().parents[3]
OPPONENT = "Zzyzx Rovers"
SECRET_OPP2 = "Qwerty United"


def _fx(fid, league, home, away, when, state="NS", rnd=None):
    parts = [{"id": h, "name": n, "short_code": n[:3].upper(), "meta": {"location": loc}}
             for (h, n), loc in ((home, "home"), (away, "away"))]
    return {"id": fid, "league_id": league, "starting_at": when, "state": {"developer_name": state},
            "round": {"name": str(rnd)} if rnd else None,
            "participants": parts}


@pytest.fixture()
def capture(tmp_path, monkeypatch):
    arsenal, city, opp1, opp2, other = (1, "Arsenal"), (2, "Manchester City"), (90, OPPONENT), (91, SECRET_OPP2), (3, "Chelsea")
    data = {"schema_version": 1,
            "teams": [{"id": 1, "short_code": "ARS"}, {"id": 2, "short_code": "MCI"}, {"id": 3, "short_code": "CHE"}],
            "team_fixtures": [
                _fx(1, 8, arsenal, other, "2026-10-10 11:30:00", "FT", 7),
                _fx(2, 2, arsenal, opp1, "2026-10-13 19:00:00"),
                _fx(3, 8, other, arsenal, "2026-10-18 15:30:00", rnd=8),
                _fx(4, 27, opp2, arsenal, "2026-10-14 19:00:00"),
                _fx(5, 8, city, other, "2026-10-17 15:30:00", rnd=8),
                _fx(6, 24, city, opp1, "2026-10-20 19:00:00", "POSTPONED"),
            ]}
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv(cc.ENV_ALLOW, "1")
    monkeypatch.setenv(cc.ENV_CAPTURE, str(path))
    cc._cache.clear()
    return path


def _get(tier=None, **params):
    headers = {} if tier is None else {"X-User-Tier": tier}
    return TestClient(fpl_server.app).get("/fixtures/competitions", params=params, headers=headers)


# -- dev gate ---------------------------------------------------------------

def test_default_serves_nothing(monkeypatch):
    monkeypatch.delenv(cc.ENV_ALLOW, raising=False)
    monkeypatch.delenv(cc.ENV_CAPTURE, raising=False)
    cc._cache.clear()
    for tier in (None, "free", "patreon_premium"):
        r = _get(tier)
        assert r.status_code == 200 and r.json() == {"available": False}


def test_flag_without_capture_serves_nothing(monkeypatch):
    monkeypatch.setenv(cc.ENV_ALLOW, "1")
    monkeypatch.delenv(cc.ENV_CAPTURE, raising=False)
    assert _get("patreon_premium").json() == {"available": False}


def test_capture_without_flag_serves_nothing(capture, monkeypatch):
    for value in ("", "0", "true"):
        monkeypatch.setenv(cc.ENV_ALLOW, value)
        assert _get("patreon_premium").json() == {"available": False}


def test_dev_variables_appear_in_no_prod_path():
    prod = [p for pat in ("**/Dockerfile*", "**/railway*.json", "**/railway*.toml", "**/vercel.json",
                          ".github/**/*.yml", ".github/**/*.yaml", "**/.env.example", "**/*.env")
            for p in REPO.glob(pat) if "node_modules" not in p.parts and ".worktrees" not in p.parts]
    for path in prod:
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "FI_DEV_ALLOW_LIVE_TRIAL_LOCAL" not in text, path
        assert "FI_DEV_LIVE_TRIAL_CAPTURE" not in text, path
    users = [p for p in (REPO / "packages").rglob("*.py")
             if "node_modules" not in p.parts and "tests" not in p.parts
             and "FI_DEV_ALLOW_LIVE_TRIAL_LOCAL" in p.read_text(encoding="utf-8", errors="ignore")]
    assert [p.name for p in users] == ["competition_calendar.py"]


# -- premium ----------------------------------------------------------------

def test_premium_shape_and_rest_days(capture):
    body = _get("patreon_premium", team="ars").json()
    assert body["available"] is True and body["tier"] == "premium" and list(body["teams"]) == ["ARS"]
    matches = body["teams"]["ARS"]["matches"]
    assert [m["competition"] for m in matches] == ["UCL", "EFL"]
    ucl, efl = matches
    assert (ucl["opponent"], ucl["venue"], ucl["week"]) == (OPPONENT, "H", "2026-10-12")
    assert ucl["gameweek"] == 8 and efl["gameweek"] == 8
    # PL 10 Oct 11:30 -> UCL 13 Oct 19:00 = 3.3 d; UCL -> EFL (14 Oct 19:00) = 1.0 d; EFL -> PL 18 Oct 15:30 = 3.9 d.
    assert ucl["rest_days_before"] == 3.3 and ucl["rest_days_after"] == 1.0
    assert efl["venue"] == "A" and efl["rest_days_before"] == 1.0 and efl["rest_days_after"] == 3.9
    assert all("is_pl" not in m for m in matches)


@pytest.mark.parametrize("tier", ["patreon_basic", "patreon_plus", "patreon_premium"])
def test_every_paid_tier_gets_the_detail(capture, tier):
    body = _get(tier, team="ARS").json()
    assert body["tier"] == "premium" and body["teams"]["ARS"]["matches"][0]["opponent"] == OPPONENT


def _rotation(tmp_path, monkeypatch, gap_minutes, extra=(), first_league=2):
    """A club with one earlier match (``first_league``, default UCL), then a PL match ``gap_minutes`` later."""
    from datetime import datetime, timedelta
    t0 = datetime(2026, 10, 13, 19, 0)
    arsenal, opp = (1, "Arsenal"), (90, OPPONENT)
    fixtures = [_fx(1, first_league, arsenal, opp, t0.strftime("%Y-%m-%d %H:%M:%S")),
                _fx(2, 8, arsenal, (3, "Chelsea"), (t0 + timedelta(minutes=gap_minutes)).strftime("%Y-%m-%d %H:%M:%S"))]
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"schema_version": 1, "teams": [{"id": 1, "short_code": "ARS"}],
                                "team_fixtures": [*fixtures, *extra]}), encoding="utf-8")
    monkeypatch.setenv(cc.ENV_ALLOW, "1")
    monkeypatch.setenv(cc.ENV_CAPTURE, str(path))
    cc._cache.clear()
    return _get("patreon_premium", team="ARS").json()["teams"]["ARS"]["rotation_notices"]


@pytest.mark.parametrize("hours,warns", [(72, True), (95.9, True), (96, False), (6 * 24, False), (48, True)])
def test_rotation_notice_edges(tmp_path, monkeypatch, hours, warns):
    notices = _rotation(tmp_path, monkeypatch, int(hours * 60))
    assert bool(notices) is warns
    if warns:
        assert notices[0]["previous_competition"] == "UCL" and notices[0]["rest_whole_days"] <= cc.ROTATION_REST_DAYS


@pytest.mark.parametrize("league,hours,warns", [
    (2, 72, True),      # UCL -> PL, 3 days
    (5, 90, True),      # UEL
    (2286, 48, True),   # UECL
    (24, 72, True),     # FA
    (27, 72, True),     # EFL
    (8, 48, False),     # PL -> PL, 2 days: never warns (Leo, 2026-10-14)
    (8, 72, False),     # PL -> PL, 3 days
    (24, 96, False),    # FA -> PL, 4 days
    (2, 96, False),     # UCL -> PL, 4 days
])
def test_rotation_only_after_europe_or_cup(tmp_path, monkeypatch, league, hours, warns):
    notices = _rotation(tmp_path, monkeypatch, int(hours * 60), first_league=league)
    assert bool(notices) is warns


def test_pl_to_pl_rest_days_are_still_shown(tmp_path, monkeypatch):
    _rotation(tmp_path, monkeypatch, 48 * 60, first_league=8)
    body = _get("patreon_premium", team="ARS").json()["teams"]["ARS"]
    assert body["rotation_notices"] == [] and body["matches"] == []


def test_rotation_needs_a_previous_match(tmp_path, monkeypatch):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"schema_version": 1, "teams": [{"id": 1, "short_code": "ARS"}], "team_fixtures": [
        _fx(2, 8, (1, "Arsenal"), (3, "Chelsea"), "2026-10-18 15:30:00")]}), encoding="utf-8")
    monkeypatch.setenv(cc.ENV_ALLOW, "1")
    monkeypatch.setenv(cc.ENV_CAPTURE, str(path))
    cc._cache.clear()
    assert _get("patreon_premium").json()["teams"]["ARS"]["rotation_notices"] == []


def test_rotation_constant_is_attributed_to_product():
    src = Path(cc.__file__).read_text(encoding="utf-8")
    assert cc.ROTATION_REST_DAYS == 3 and "decided by Leo 2026-10-14: only after a European/cup match" in src and "ROTATION_AFTER" in src and "not M3 thresholds" in src


def test_postponed_fixture_is_not_a_match(capture):
    assert _get("patreon_premium", team="MCI").json()["teams"]["MCI"]["matches"] == []


def test_window_filter(capture):
    ms = _get("patreon_premium", team="ARS", **{"from": "2026-10-14", "to": "2026-10-30"}).json()["teams"]["ARS"]["matches"]
    assert [m["competition"] for m in ms] == ["EFL"]
    assert _get("patreon_premium", **{"from": "bad"}).status_code == 422


# -- free: never a rival, never a competition ---------------------------------

@pytest.mark.parametrize("tier", [None, "free", "patreon_tribuna", "premium", "PATREON_PREMIUM", "nonsense"])
def test_non_detail_tiers_get_counts_only(capture, tier):
    r = _get(tier)
    body = r.json()
    assert body["available"] is True and body["tier"] == "free"
    assert body["teams"]["ARS"] == {"extra_by_gameweek": {"8": 2}}
    assert body["teams"]["MCI"] == {"extra_by_gameweek": {}}
    raw = r.text
    for leaked in ("rotation", OPPONENT, SECRET_OPP2, "UCL", "EFL", "FA", "rest_days", "kickoff", "opponent", "competition", "venue"):
        assert leaked not in raw, leaked


def test_free_payload_has_no_detail_keys_at_any_depth(capture):
    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from walk(v)
        elif isinstance(node, list):
            for v in node:
                yield from walk(v)
    assert set(walk(_get("free").json())) <= {"available", "tier", "teams", "ARS", "MCI", "CHE",
                                              "extra_by_gameweek", "8"}


# -- tier is read in one place, from the server's own helper ------------------

def test_tier_is_read_through_the_single_helper(capture, monkeypatch):
    monkeypatch.setattr(fpl_server, "tier_of", lambda request: "patreon_premium")
    assert _get("free").json()["tier"] == "premium"
    monkeypatch.setattr(fpl_server, "tier_of", lambda request: "free")
    assert _get("patreon_premium").json()["tier"] == "free"


@pytest.mark.xfail(strict=True, reason="i153: the backend trusts X-User-Tier from any caller; the tier must only be "
                                       "accepted with a valid X-Internal-Token. Today a forged header is premium.")
def test_forged_premium_header_without_internal_token_is_free(capture, monkeypatch):
    monkeypatch.setenv("FPL_INTERNAL_TOKEN", "s3cret")
    assert _get("patreon_premium").json()["tier"] == "free"


def test_club_codes_are_fpl_codes(capture, tmp_path, monkeypatch):
    """Sportmonks calls Coventry CVC; the FPL bundle (and so the board) calls it COV."""
    path = tmp_path / "cov.json"
    path.write_text(json.dumps({"schema_version": 1, "teams": [{"id": 7, "short_code": "CVC"}], "team_fixtures": [
        _fx(1, 2, (7, "Coventry City"), (90, OPPONENT), "2026-10-13 19:00:00")]}), encoding="utf-8")
    monkeypatch.setenv(cc.ENV_CAPTURE, str(path))
    cc._cache.clear()
    assert list(_get("free").json()["teams"]) == ["COV"]
