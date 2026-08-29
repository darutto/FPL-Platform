"""i25 — the corpus expires and nothing says so; this is the check that says so.

Found by reading one case: `pv-11` asks about Gordon, who left in this window.
A stale case does not merely lose data, it **manufactures findings** — the first
reference run scored `pv-11` as a 3/3 reproduction of i46 when there was nothing
to synthesise at all.

Offline: every test here drives a synthetic bootstrap, so this runs in CI while
the battery that spends money does not.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parent.parent
_SCRIPTS = _PKG / "scripts"
for _p in (str(_PKG), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import golden_axes as gx  # noqa: E402
import golden_preflight as pf  # noqa: E402


def _player(pid: int, web_name: str, first: str = "A", second: str = "B") -> dict:
    return {
        "id": pid, "web_name": web_name, "first_name": first, "second_name": second,
        "team": 1, "element_type": 3, "status": "a", "minutes": 900,
        "now_cost": 50, "total_points": 10,
    }


@pytest.fixture()
def bootstrap() -> dict:
    return {
        "teams": [
            {"id": 1, "name": "Man City", "short_name": "MCI"},
            {"id": 2, "name": "Coventry City", "short_name": "COV"},
            {"id": 3, "name": "Hull City", "short_name": "HUL"},
            {"id": 4, "name": "Bournemouth", "short_name": "BOU"},
        ],
        "element_types": [{"id": 3, "singular_name_short": "MID"}],
        "elements": [
            _player(1, "Haaland", "Erling", "Haaland"),
            _player(2, "Anderson", "Elliot", "Anderson"),
            _player(3, "Emersonn", "Emerson", "Souza"),
        ],
    }


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def test_a_present_player_resolves(bootstrap):
    assert pf._resolve_player("Haaland", bootstrap) == pf.OK


def test_an_exact_match_is_not_discarded_by_a_falsy_zero_rank(bootstrap):
    """Regression on a bug written while building this: filtering matches with
    `(m.get("match_rank") or 99) <= 1` discards every EXACT hit, because
    match_rank 0 is falsy. It reported Haaland — and every live player — as
    departed, and was caught only because the output was obviously absurd.

    Exactly the instrument failure this whole card exists to remove, committed
    inside the tool meant to prevent it. Pinned so it cannot come back."""
    assert pf._resolve_player("Haaland", bootstrap) == pf.OK

    from fpl_grounded_assistant.find_players import find_players
    ranks = [m.get("match_rank") for m in find_players("Haaland", bootstrap=bootstrap)["matches"]]
    assert 0 in ranks, "the fixture must actually exercise an exact (rank 0) match"


def test_a_departed_player_is_not_rescued_by_substring_matches(bootstrap):
    """"Son" fuzzy-matches Emersonn and Anderson. Accepting those would report a
    departed player as present — the precise failure being guarded against."""
    assert pf._resolve_player("Son", bootstrap) == pf.NOT_FOUND


def test_a_name_matching_two_players_is_ambiguous(bootstrap):
    bootstrap["elements"].append(_player(4, "Haaland", "Other", "Haaland"))

    assert pf._resolve_player("Haaland", bootstrap) == pf.AMBIGUOUS


def test_a_missing_player_is_not_found(bootstrap):
    assert pf._resolve_player("Gordon", bootstrap) == pf.NOT_FOUND


def test_team_alias_resolves_the_bootstrap_spelling(bootstrap):
    """The bootstrap abbreviates: a literal comparison reports a live team gone."""
    assert pf._resolve_team("Manchester City", bootstrap) == pf.OK
    assert pf._resolve_team("El Bournemouth", bootstrap) == pf.OK


def test_a_relegated_team_is_not_found(bootstrap):
    assert pf._resolve_team("Wolves", bootstrap) == pf.NOT_FOUND


def test_an_ambiguous_team_substring_does_not_resolve(bootstrap):
    """"City" alone matches Coventry, Hull and Man City."""
    assert pf._resolve_team("City", bootstrap) == pf.NOT_FOUND


# ---------------------------------------------------------------------------
# Case-level check
# ---------------------------------------------------------------------------

def test_check_names_the_case_and_the_reason(bootstrap):
    stale = pf.check({"pv-11": "Dame el detalle de Gordon en lo que va de temporada."},
                     bootstrap)

    assert [s.case_id for s in stale] == ["pv-11"]
    assert "Gordon" in stale[0].reason and pf.NOT_FOUND in stale[0].reason
    assert "pv-11" in pf.format_report(stale)


def test_a_clean_case_produces_no_stale_entry(bootstrap):
    assert pf.check({"pv-03": "Me conviene Haaland esta fecha?"}, bootstrap) == []


# ---------------------------------------------------------------------------
# The declaration cannot go stale the way the corpus did
# ---------------------------------------------------------------------------

def test_every_capitalised_candidate_in_every_case_is_reviewed():
    """A question added later whose capitalised tokens are in neither ENTITIES
    nor NON_ENTITIES must force review rather than contribute an unchecked pin.
    This is the property that keeps the pin list from repeating the corpus's
    failure."""
    for axis in gx.build_axes("full"):
        for case in axis.cases:
            for candidate in pf.scan_candidates(case.question):
                assert candidate in pf.ENTITIES or candidate in pf.NON_ENTITIES, (
                    f"{case.id}: {candidate!r} is neither a declared entity nor a "
                    f"declared non-entity"
                )


def test_an_undeclared_candidate_raises():
    with pytest.raises(SystemExit) as excinfo:
        pf.entities_in("¿Cómo viene Zarzuelinho esta fecha?")

    assert "Zarzuelinho" in str(excinfo.value)


def test_declared_sets_do_not_overlap():
    assert not (set(pf.ENTITIES) & pf.NON_ENTITIES)


def test_every_declared_entity_has_a_known_kind():
    assert set(pf.ENTITIES.values()) <= {pf.PLAYER, pf.TEAM}
