"""pressure_harvest: plan and gates are offline, the run goes through the client only, nothing leaves trial-output/."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pressure_harvest  # noqa: E402
from _trial_common import DEFAULT_OUT, EXIT_OK, EXIT_REFUSED, MODE_MOCK, make_client  # noqa: E402
from conftest import FakeTransport, response  # noqa: E402

SOURCE = (Path(__file__).resolve().parent.parent / "scripts" / "pressure_harvest.py").read_text(encoding="utf-8")


def _season(sid, start):
    return {"id": sid, "name": f"{start[:4]}/{int(start[:4]) + 1}", "starting_at": start}


def _seasons_body():
    return response({"data": [_season(1, "2024-08-16"), _season(2, "2025-08-15"), _season(3, "2026-08-21")]})


def _fixture(fid, state="FT", pressure=True, xg=True):
    rows = [{"minute": m, "pressure": 10, "participant_id": p} for m in (1, 2) for p in (7, 8)] if pressure else []
    return {"id": fid, "state": {"developer_name": state}, "pressure": rows,
            "xgfixture": [{"type_id": pressure_harvest.EXPECTED_GOALS_TYPE, "data": {"value": 1.2}}] if xg else []}


def _client(*bodies):
    transport = FakeTransport(list(bodies))
    return make_client(MODE_MOCK, transport=transport), transport


def test_dry_run_prints_the_plan_without_a_client_or_a_token(monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("dry run must not build a client or read the token")

    monkeypatch.setattr(pressure_harvest, "make_client", boom)
    monkeypatch.setattr(pressure_harvest.SportmonksConfig, "from_env", boom)
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "secret-token-value")
    assert pressure_harvest.main(["--dry-run", "--years", "2026,2025"]) == EXIT_OK
    text = capsys.readouterr().out
    assert "planned requests: minimum 3, maximum 23, hard cap 60" in text  # max: 3 + 2 x 10
    assert "secret-token-value" not in text


def test_live_needs_the_acknowledgement(capsys):
    assert pressure_harvest.main([]) == EXIT_REFUSED
    assert pressure_harvest.main(["--live"]) == EXIT_REFUSED
    assert "REFUSED" in capsys.readouterr().out


def test_output_outside_trial_output_is_refused(tmp_path, capsys):
    assert pressure_harvest.main(["--dry-run", "--out", str(tmp_path)]) == EXIT_REFUSED
    assert pressure_harvest.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path)]) == EXIT_REFUSED
    assert "trial-output" in capsys.readouterr().out


def test_a_bad_years_list_is_refused():
    assert pressure_harvest.main(["--dry-run", "--years", "twenty"]) == EXIT_REFUSED


def test_the_default_output_is_inside_the_gitignored_directory():
    assert pressure_harvest._inside_trial_output(DEFAULT_OUT / pressure_harvest.OUT_SUBDIR)


def test_the_script_has_no_raw_http_and_never_prints_the_token():
    for forbidden in ("import requests", "from requests", "import urllib", "import httpx", "import http.client", "urlopen("):
        assert forbidden not in SOURCE
    assert "SPORTMONKS_API_TOKEN" not in SOURCE


def test_fixture_stats_count_only_what_is_finished_and_complete():
    rows = [_fixture(1), _fixture(2, pressure=False), _fixture(3, xg=False), _fixture(4, state="NS")]
    assert pressure_harvest.fixture_stats(rows) == {
        "fixtures": 4, "finished": 3, "finished_with_pressure": 2, "finished_with_team_xg": 2,
        "pressure_two_rows_per_minute": 2, "pressure_rows": 8}


def test_a_run_writes_files_and_aggregates_through_the_client_only(tmp_path):
    client, transport = _client(_seasons_body(), response({"data": [_fixture(1), _fixture(2, "NS")]}))
    summary = pressure_harvest.run(client, tmp_path / "out", years=(2026,))
    assert summary["requests"] == len(transport.calls) == 2
    assert all(call[0] == "GET" and call[1].startswith(client.config.base_url) for call in transport.calls)
    assert summary["units"][0]["finished_with_pressure"] == 1
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["fixtures-2026.json", "summary.json"]
    assert "token" not in (tmp_path / "out" / "summary.json").read_text(encoding="utf-8").lower()


def test_the_request_cap_stops_the_run_and_keeps_what_was_read(tmp_path):
    client, transport = _client(_seasons_body(), response({"data": [_fixture(1)]}))
    summary = pressure_harvest.run(client, tmp_path / "out", years=(2026, 2025), cap=2)
    assert summary["requests"] <= 2 and len(transport.calls) <= 2
    assert any(note.startswith("BUDGET") for note in summary["notes"])
    assert (tmp_path / "out" / "summary.json").is_file()


def test_a_missing_season_is_noted_and_costs_no_fixture_request(tmp_path):
    client, transport = _client(response({"data": [_season(1, "2020-08-01")]}))
    summary = pressure_harvest.run(client, tmp_path / "out", years=(2026,))
    assert len(transport.calls) == 1 and summary["units"] == []
    assert any("no season found" in n for n in summary["notes"])


# -- the per-player xG pass --------------------------------------------------------

def _lineup_fixture(fid, state="FT", with_xg=2, rows=4):
    xg = [{"type_id": pressure_harvest.EXPECTED_GOALS_TYPE, "data": {"value": 0.3}}]
    return {"id": fid, "state": {"developer_name": state},
            "lineups": [{"player_id": i, "xglineup": xg if i < with_xg else []} for i in range(rows)]}


def test_player_xg_stats_count_fixtures_and_lineup_rows():
    rows = [_lineup_fixture(1), _lineup_fixture(2, with_xg=0), _lineup_fixture(3, state="NS")]
    assert pressure_harvest.player_xg_stats(rows) == {
        "fixtures": 3, "finished": 2, "finished_with_lineups": 2, "finished_with_player_xg": 1,
        "lineup_rows": 8, "lineup_rows_with_xg": 2}


def test_player_xg_dry_run_names_the_lineup_include(capsys):
    assert pressure_harvest.main(["--player-xg", "--dry-run", "--years", "2026"]) == EXIT_OK
    assert "lineups.xGLineup" in capsys.readouterr().out


def test_player_xg_run_writes_its_own_files_and_leaves_the_first_pass_alone(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "summary.json").write_text("first pass", encoding="utf-8")
    client, transport = _client(_seasons_body(), response({"data": [_lineup_fixture(1)]}))
    summary = pressure_harvest.run(client, out, years=(2026,), player_xg=True)
    assert summary["requests"] == len(transport.calls) == 2
    assert transport.calls[1][2]["include"] == pressure_harvest.PLAYER_XG_INCLUDES
    assert (out / "summary.json").read_text(encoding="utf-8") == "first pass"
    assert sorted(p.name for p in out.iterdir()) == ["lineups-xg-2026.json", "summary-player-xg.json", "summary.json"]
