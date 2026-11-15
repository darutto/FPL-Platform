"""Synthetic text only: the real list never enters the repo."""
import pytest

from football_intelligence.manual_calendar import ManualCalendarError, parse_manual_europe

TEXT = """Titulo cualquiera

CHAMPIONS LEAGUE

Arsenal
- 04/11/2026 vs Equipo Uno (Visitante)
- 24/11/2026 vs Chelsea (Local)

EUROPA LEAGUE

Nott'm Forest
- 05/11/2026 vs Equipo Dos (Local)
"""


def test_converts_to_the_layer_with_no_time_and_partial_coverage():
    layer = parse_manual_europe(TEXT, list_date="2026-10-27")
    assert layer["provenance"] == "manual_curated" and layer["coverage"] == "partial" and layer["frozen"] is True
    assert layer["competitions"] == ["UCL", "UEL"] and layer["list_date"] == "2026-10-27"
    first = layer["matches"][0]
    assert first == {"competition": "UCL", "club": "ARS", "opponent": "Equipo Uno", "opponent_code": "",
                     "date": "2026-11-04", "venue": "A", "kickoff_known": False}
    assert all(m["kickoff_known"] is False and "kickoff_utc" not in m for m in layer["matches"])
    by = {(m["club"], m["date"]): m for m in layer["matches"]}
    assert by[("NFO", "2026-11-05")]["competition"] == "UEL"
    assert by[("ARS", "2026-11-24")]["opponent_code"] == "CHE"  # a PL club keeps the registry code


TIMED = """CHAMPIONS LEAGUE

Arsenal
- 04/11/2026 vs Equipo Uno (Visitante) - 15:00 EST / 21:00 CET
- 24/11/2026 vs Equipo Dos (Local) - 15:00 EST / 21:00 GMT
- 09/12/2026 vs Equipo Tres (Local) - 12:45 EST / 17:45 GMT
"""


def test_times_become_utc_and_a_disagreement_or_listed_doubt_is_unverified():
    layer = parse_manual_europe(TIMED, list_date="2026-10-28", unverified=frozenset({("ARS", "2026-12-09")}))
    by = {m["date"]: m for m in layer["matches"]}
    assert by["2026-11-04"]["kickoff_utc"] == "2026-11-04T20:00:00Z" and by["2026-11-04"]["kickoff_known"] is True
    assert by["2026-11-24"]["kickoff_known"] is False and "kickoff_utc" not in by["2026-11-24"]  # EST vs GMT disagree
    assert by["2026-12-09"]["kickoff_known"] is False
    assert [(w["line"], w["reason"]) for w in layer["warnings"]] == [(5, "est_local_mismatch"), (6, "listed_unverified")]


@pytest.mark.parametrize("bad", [
    "CHAMPIONS LEAGUE\n\nEquipo Raro\n- 04/11/2026 vs X (Local)\n",  # not a PL club
    "CHAMPIONS LEAGUE\n\nArsenal\n- 31/02/2026 vs X (Local)\n",      # impossible date
    "CHAMPIONS LEAGUE\n\nArsenal\n- 04/11/2026 vs X (Neutral)\n",    # unknown venue
    "CHAMPIONS LEAGUE\n\nArsenal\n- 04/11/2026 vs X (Local)\n- 04/11/2026 vs Y (Local)\n",  # duplicate
    "- 04/11/2026 vs X (Local)\n",                                    # outside any block
    "",
])
def test_malformed_lists_fail_loudly(bad):
    with pytest.raises(ManualCalendarError):
        parse_manual_europe(bad, list_date="2026-10-27")


def test_a_bad_list_date_fails():
    with pytest.raises(ValueError):
        parse_manual_europe(TEXT, list_date="27/10/2026")
