"""euro_preload: plan and gates are offline, the run goes through the client only, nothing leaves trial-output/."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import euro_preload  # noqa: E402
from _trial_common import DEFAULT_OUT, EXIT_OK, EXIT_REFUSED, MODE_MOCK, make_client  # noqa: E402
from conftest import FakeTransport, response  # noqa: E402

SOURCE = (Path(__file__).resolve().parent.parent / "scripts" / "euro_preload.py").read_text(encoding="utf-8")


def _season(sid, start):
    return {"id": sid, "name": f"{start[:4]}/{int(start[:4]) + 1}", "starting_at": start}


def _seasons_body():
    return response({"data": [_season(1, "2024-06-11"), _season(2, "2025-06-10"), _season(3, "2026-06-09")]})


def _starter(n, grid=True):
    return {"type_id": euro_preload.STARTER_TYPE, "formation_field": "1:1" if grid else None, "player_id": n}


def _fixture(fid, state, starters=22, grid=True, formations=True):
    return {"id": fid, "league_id": 2, "starting_at": "2026-09-16 19:00:00", "state": {"developer_name": state},
            "lineups": [_starter(i, grid) for i in range(starters)], "formations": [{"x": 1}] if formations else []}


def _client(*bodies):
    transport = FakeTransport(list(bodies))
    return make_client(MODE_MOCK, transport=transport), transport


# -- gates: no request, no token -------------------------------------------------

def test_dry_run_prints_the_plan_without_a_client_or_a_token(monkeypatch, capsys, tmp_path):
    def boom(*a, **k):
        raise AssertionError("dry run must not build a client or read the token")

    monkeypatch.setattr(euro_preload, "make_client", boom)
    monkeypatch.setattr(euro_preload.SportmonksConfig, "from_env", boom)
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "secret-token-value")
    capture = tmp_path / "capture.json"
    capture.write_text(json.dumps({"scope": {"team_ids": [10, 11, 12]}}), encoding="utf-8")
    code = euro_preload.main(["--dry-run", "--years", "2026,2025", "--capture", str(capture)])
    text = capsys.readouterr().out
    assert code == EXIT_OK
    # 4 season lookups + 2 years x 4 leagues + 3 clubs
    assert "planned requests: minimum 15, maximum 101" in text  # max: 4*3 + 8*10 + 3*3
    assert "hard cap 180" in text
    assert "secret-token-value" not in text


def test_dry_run_without_a_capture_says_the_club_calendars_are_skipped(capsys, tmp_path):
    assert euro_preload.main(["--dry-run", "--years", "2026", "--capture", str(tmp_path / "missing.json")]) == EXIT_OK
    assert "club calendars: skipped" in capsys.readouterr().out


def test_live_needs_the_acknowledgement(capsys):
    assert euro_preload.main([]) == EXIT_REFUSED
    assert euro_preload.main(["--live"]) == EXIT_REFUSED
    assert "REFUSED" in capsys.readouterr().out


def test_output_outside_trial_output_is_refused(tmp_path, capsys):
    assert euro_preload.main(["--dry-run", "--out", str(tmp_path)]) == EXIT_REFUSED
    assert "trial-output" in capsys.readouterr().out
    assert euro_preload.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path)]) == EXIT_REFUSED


def test_the_default_output_is_inside_the_gitignored_directory():
    assert euro_preload._inside_trial_output(DEFAULT_OUT / euro_preload.OUT_SUBDIR)
    assert not euro_preload._inside_trial_output(DEFAULT_OUT.parent)


def test_a_bad_years_list_is_refused(capsys):
    assert euro_preload.main(["--dry-run", "--years", "twenty"]) == EXIT_REFUSED


def test_the_script_has_no_raw_http_and_never_prints_the_token():
    for forbidden in ("import requests", "from requests", "import urllib", "import httpx", "import http.client", "urlopen("):
        assert forbidden not in SOURCE
    assert "SPORTMONKS_API_TOKEN" not in SOURCE


# -- pure helpers ----------------------------------------------------------------

def test_default_years_follow_the_season_that_starts_in_the_summer():
    assert euro_preload.default_years(date(2026, 10, 22)) == (2026, 2025, 2024)
    assert euro_preload.default_years(date(2027, 3, 1)) == (2026, 2025, 2024)
    assert euro_preload.default_years(date(2027, 6, 1)) == (2027, 2026, 2025)


def test_a_season_is_picked_by_its_summer_start():
    client, _ = _client(_seasons_body())
    seasons = tuple(client.iter_entities("seasons", params={"filters": "seasonLeagues:2"}, max_pages=1))
    assert euro_preload.pick_season(seasons, 2025)["id"] == 2
    assert euro_preload.pick_season(seasons, 2026)["id"] == 3
    assert euro_preload.pick_season(seasons, 2030) is None


def test_fixture_stats_count_only_what_is_finished_and_complete():
    rows = [_fixture(1, "FT"), _fixture(2, "FT", grid=False), _fixture(3, "FT", starters=11), _fixture(4, "NS"),
            _fixture(5, "AET", formations=False)]
    assert euro_preload.fixture_stats(rows) == {
        "fixtures": 5, "finished": 4, "finished_with_full_xi": 3, "finished_with_grid_on_all_starters": 2,
        "finished_with_formation": 3}


def test_team_ids_come_from_a_capture_or_are_not_guessed(tmp_path):
    path = tmp_path / "capture.json"
    assert euro_preload.load_team_ids(path) is None
    path.write_text(json.dumps({"scope": {"team_ids": [3, 6]}}), encoding="utf-8")
    assert euro_preload.load_team_ids(path) == [3, 6]
    path.write_text(json.dumps({"scope": {}}), encoding="utf-8")
    assert euro_preload.load_team_ids(path) is None


# -- a run through the client ----------------------------------------------------

def test_a_run_writes_files_and_aggregates_through_the_client_only(tmp_path):
    bodies = [_seasons_body() for _ in range(4)]  # one season list per league
    bodies += [response({"data": [_fixture(1, "FT"), _fixture(2, "NS")]}) for _ in range(4)]  # one year x four leagues
    bodies += [response({"data": [{"id": 77, "league_id": 8, "league": {"name": "Premier League"}}]}),
               response({"data": [{"id": 78, "league_id": 2, "league": {"name": "Champions League"}}]})]
    client, transport = _client(*bodies)
    summary = euro_preload.run(client, tmp_path / "out", years=(2026,), team_ids=[10, 11])
    assert summary["requests"] == len(transport.calls) == 10
    assert all(call[0] == "GET" and call[1].startswith(client.config.base_url) for call in transport.calls)
    fixtures = [u for u in summary["units"] if u["kind"] == "fixtures"]
    assert len(fixtures) == 4 and all(u["fixtures"] == 2 and u["finished_with_full_xi"] == 1 for u in fixtures)
    assert summary["units"][-1]["fixtures_by_competition"] == {"Premier League": 1, "Champions League": 1}
    written = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert written == ["fixtures-2026-UCL.json", "fixtures-2026-UECL.json", "fixtures-2026-UEFA-SC.json",
                       "fixtures-2026-UEL.json", "seasons.json", "summary.json", "team_fixtures-2026.json"]
    assert "token" not in (tmp_path / "out" / "summary.json").read_text(encoding="utf-8").lower()


def test_the_request_cap_stops_the_run_and_keeps_what_was_read(tmp_path):
    client, transport = _client(*[_seasons_body() for _ in range(4)],
                                *[response({"data": [_fixture(1, "FT")]}) for _ in range(4)])
    summary = euro_preload.run(client, tmp_path / "out", years=(2026,), team_ids=None, cap=5)
    assert summary["requests"] <= 5 and len(transport.calls) <= 5
    assert any(note.startswith("BUDGET") for note in summary["notes"])
    assert (tmp_path / "out" / "summary.json").is_file()


def test_a_missing_season_is_noted_and_costs_no_fixture_request(tmp_path):
    client, transport = _client(*[response({"data": [_season(1, "2020-06-01")]}) for _ in range(4)])
    summary = euro_preload.run(client, tmp_path / "out", years=(2026,), team_ids=None)
    assert len(transport.calls) == 4 and summary["units"] == []
    assert sum("no season found" in n for n in summary["notes"]) == 4 and any("skipped" in n for n in summary["notes"])
