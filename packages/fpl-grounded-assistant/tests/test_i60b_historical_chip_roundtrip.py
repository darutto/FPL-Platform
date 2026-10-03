"""i60 part B -- a historical chip resolves when tapped; it never loops.

Prod, 2026-10-03 (Leo): «puntos de Martínez la temporada pasada» -> chips ->
tap «Martínez (AVL)» -> the chip sends «puntos de Emiliano Martínez Romero
(AVL) en la temporada 2025-2026» -> back comes «¿Cuál de estos jugadores
buscabas?» with ONE chip, the same one, forever.

Cause, in ``_resolve_player_in_season``:
(a) the exact rank compared the query with first, second and web names
    SEPARATELY, never with "first second" -- the chip's own full name fell to
    the substring rank;
(b) there a lone match is accepted only when the club "narrowed"; but a club
    that CONFIRMED the only match (kept == ids) returned False, the same as a
    club that matched nobody -> ambiguous with one candidate.

Fix: (a) "first second" and "first second web" are exact matches; (b) a club
that confirms counts like one that narrows, a club that matches nobody still
leaves it ambiguous (unchanged). Invariant (c'): every ambiguous result is
RESOLVABLE -- each candidate's chip send_text, fed back through the real
handler the way the orchestrator would (club token in the query, or a
structured team_short), returns ok with that candidate's historical id.
A one-candidate ambiguity is still allowed (it is the "did you mean?" for a
lone substring match); it just must not loop.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

import fpl_grounded_assistant.get_player_season_points  # noqa: F401 -- load the module, not the re-export
from fpl_grounded_assistant.suggestions import historical_player_suggestions, suggestions_to_list
from fpl_grounded_assistant.tool_dispatch import run_tool

sp = sys.modules["fpl_grounded_assistant.get_player_season_points"]
SEASON = "2025-2026"

PLAYERS = [
    # pid, web, first, second, team_id, element_type, points
    (501, "Martínez", "Emiliano", "Martínez Romero", 2, 1, 150),   # AVL keeper -- the prod chip
    (502, "Martínez", "Lisandro", "Martínez", 11, 2, 60),          # MUN defender
    (101, "Salah", "Mohamed", "Salah", 14, 3, 300),
    (202, "Salah", "Mohamed", "Salah", 4, 4, 40),                  # same name, other club
    (303, "Haaland", "Erling", "Haaland", 13, 4, 250),
    (601, "Johnson", "Adam", "Johnson", 8, 3, 30),                 # two Johnsons, SAME club
    (602, "Johnson", "Glen", "Johnson", 8, 2, 20),
]
TEAMS = {2: "AVL", 11: "MUN", 14: "LIV", 4: "BOU", 13: "MCI", 8: "CHE", 1: "ARS"}


@pytest.fixture
def store(tmp_path: Path):
    merged = tmp_path / "historical" / "seasons" / SEASON / "parquet_merged"
    merged.mkdir(parents=True)
    pd.DataFrame([{"player_id": p, "web_name": w, "first_name": f, "second_name": s, "team_id": t,
                   "element_type": et, "total_points": pts} for p, w, f, s, t, et, pts in PLAYERS]
                 ).to_parquet(merged / "players.parquet")
    pd.DataFrame([{"team_id": k, "short_name": v} for k, v in TEAMS.items()]).to_parquet(merged / "teams.parquet")
    pd.DataFrame([{"event_id": 1, "player_id": p, "total_points": pts, "minutes": 90, "goals_scored": 0,
                   "assists": 0, "clean_sheets": 0, "bonus": 0} for p, *_, pts in PLAYERS]
                 ).to_parquet(merged / "player_gw_stats.parquet")
    pd.DataFrame([{"event_id": 1, "finished": True}]).to_parquet(merged / "events.parquet")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("FPL_HISTORICAL_ROOT", str(tmp_path / "historical"))
        importlib.reload(sp)
        yield
    importlib.reload(sp)


def _ask(query: str, team_short: str | None = None) -> dict:
    args = {"query": query, "season": SEASON}
    if team_short:
        args["team_short"] = team_short
    return run_tool("get_player_season_points", args, {})


_CHIP = re.compile(r"^puntos de (?P<name>.+) \((?P<club>[A-Z]{3})\) en la temporada (?P<season>\S+)$")


def _assert_every_chip_resolves(result: dict) -> int:
    """(c'): each chip's send_text, both ways the orchestrator can pass it,
    resolves to exactly that candidate. Returns the number of chips checked."""
    assert result["status"] == "ambiguous", result
    chips = suggestions_to_list(historical_player_suggestions(result["candidates"], result["season"]))
    assert chips and len(chips) == len(result["candidates"])
    for chip, cand in zip(chips, result["candidates"]):
        m = _CHIP.match(chip["send_text"])
        assert m, chip["send_text"]
        with_token = _ask(f"{m['name']} ({m['club']})")
        structured = _ask(m["name"], team_short=m["club"])
        for out in (with_token, structured):
            assert out["status"] == "ok", (chip["send_text"], out)
            assert out["player"]["id"] == cand["id"]
    return len(chips)


# ---------------------------------------------------------------------------
# the prod loop, verbatim
# ---------------------------------------------------------------------------

def test_prod_chip_text_resolves_instead_of_looping(store):
    out = _ask("Emiliano Martínez Romero (AVL)")
    assert out["status"] == "ok", out
    assert out["player"]["id"] == 501 and out["player"]["team_short"] == "AVL"


def test_full_name_is_an_exact_match_without_a_club(store):
    assert _ask("Emiliano Martínez Romero")["player"]["id"] == 501        # (a): first + second
    assert _ask("emiliano martinez romero martinez")["player"]["id"] == 501  # (a): first + second + web
    assert _ask("Lisandro Martínez")["player"]["id"] == 502


def test_a_club_that_confirms_the_only_substring_match_resolves(store):
    # "tínez Rom" is a substring (not a prefix) of one player only; AVL confirms him (b).
    out = _ask("tínez Rom", team_short="AVL")
    assert out["status"] == "ok" and out["player"]["id"] == 501


def test_a_club_that_matches_nobody_still_stays_ambiguous(store):
    """(b) does not relax this: the rule #262's review added stays."""
    out = _ask("tínez Rom", team_short="ARS")
    assert out["status"] == "ambiguous"
    assert [c["id"] for c in out["candidates"]] == [501]


# ---------------------------------------------------------------------------
# (c') every ambiguity is resolvable
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query, team_short, n_chips", [
    ("Martínez", None, 2),        # the prod case: AVL keeper + MUN defender
    ("Salah", None, 2),           # same full name, different clubs
    ("Salah", "ARS", 2),          # a club that matches nobody keeps the tie
    ("aland", "ARS", 1),          # lone substring, wrong club: one "did you mean?" chip
    ("aland", None, 1),           # lone substring, no club
    ("Johnson", None, 2),         # two of the SAME club, told apart by first name
])
def test_every_ambiguous_result_is_resolvable(store, query, team_short, n_chips):
    assert _assert_every_chip_resolves(_ask(query, team_short)) == n_chips


def test_same_club_homonyms_resolve_by_full_name_not_by_club(store):
    """Both Johnsons play for CHE: the club alone cannot break that tie, and
    must not pick one; the full name does."""
    assert _ask("Johnson", team_short="CHE")["status"] == "ambiguous"
    assert _ask("Adam Johnson (CHE)")["player"]["id"] == 601
    assert _ask("Glen Johnson", team_short="CHE")["player"]["id"] == 602


def test_a_shortened_name_with_its_club_resolves(store):
    """(b) in the shape the orchestrator produces: the model drops a surname
    ("Emiliano Martínez", a substring of one player only) and passes the club
    from the chip. The club confirms that one player -> ok, not a one-chip
    ambiguity."""
    out = _ask("Emiliano Martínez", team_short="AVL")
    assert out["status"] == "ok" and out["player"]["id"] == 501
    assert _ask("Emiliano Martínez (AVL)")["player"]["id"] == 501
