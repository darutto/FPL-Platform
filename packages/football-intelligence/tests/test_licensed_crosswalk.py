"""B3 step 1b: the licensed crosswalk (Sportmonks player -> FPL element). Synthetic data only: invented names."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from football_intelligence.ingestion.licensed.crosswalk import (
    MANUAL_METHOD, SECOND_PASS_METHOD, AliasFileError, build_crosswalk, load_aliases,
)

CLUB_SM, CLUB_FPL = 900001, 1
OTHER_SM, OTHER_FPL = 900002, 2


def _el(eid, first, second, born, team=CLUB_FPL, minutes=90, web=None):
    return {"id": eid, "first_name": first, "second_name": second, "web_name": web or second,
            "birth_date": born, "team": team, "minutes": minutes}


def _pl(pid, name, born, club=CLUB_SM, display=None):
    return {"id": pid, "name": name, "display_name": display, "date_of_birth": born, "squad_team_id": club}


#: Three first-pass pairs at one club, so the club crosswalk maps it (CLUB_GUARD_MIN_PAIRS = 3).
BASE_ELEMENTS = [_el(1, "Arlo", "Quint", "1998-01-01"), _el(2, "Bram", "Vesk", "1997-02-02"),
                 _el(3, "Cato", "Wynd", "1996-03-03")]
BASE_PLAYERS = [_pl(701, "Arlo Quint", "1998-01-01"), _pl(702, "Bram Vesk", "1997-02-02"),
                _pl(703, "Cato Wynd", "1996-03-03")]


def test_first_pass_resolves_by_full_name_and_birth_date():
    out = build_crosswalk(BASE_PLAYERS, BASE_ELEMENTS)
    assert out.pairs == {701: 1, 702: 2, 703: 3}
    assert out.report.by_method == {"full_name_birth_date": 3}
    assert out.report.rate_with_minutes_percent == 100.0


def test_second_pass_uses_the_display_name_only_with_birth_date_and_an_agreeing_club():
    elements = BASE_ELEMENTS + [_el(4, "Dario", "Xelto", "1995-04-04"), _el(5, "Emil", "Yorn", "1994-05-05")]
    players = BASE_PLAYERS + [
        _pl(704, "Dario Alberto Xelto Junior", "1995-04-04", display="Dario Xelto"),        # resolves
        _pl(705, "Emil Benedikt Yornsson", "1994-05-05", club=OTHER_SM, display="Emil Yorn"),   # club unmapped: no
    ]
    out = build_crosswalk(players, elements)
    assert out.pairs[704] == 4 and 705 not in out.pairs
    assert out.report.by_method[SECOND_PASS_METHOD] == 1


def test_indistinguishable_identities_are_dropped_not_guessed():
    twins = [_el(10, "Finn", "Zale", "2000-01-01", team=CLUB_FPL), _el(11, "Finn", "Zale", "2000-01-01", team=OTHER_FPL)]
    out = build_crosswalk([_pl(710, "Finn Zale", "2000-01-01")], twins)
    assert out.pairs == {}


# ------------------------------------------------------------- manual aliases

def test_an_alias_resolves_only_a_unique_birth_date_at_the_elements_club():
    elements = BASE_ELEMENTS + [_el(6, "Gus", "Abbot", "1993-06-06"), _el(7, "Hal", "Brin", "1992-07-07"),
                                _el(8, "Ivo", "Cole", "1991-08-08")]
    players = BASE_PLAYERS + [_pl(706, "Gustavo Something Else", "1993-06-06"),
                              _pl(707, "Totally Different", "1992-07-07"), _pl(708, "Another One", "1992-07-07")]
    aliases = [{"fpl_id": 6}, {"fpl_id": 7}, {"fpl_id": 8}, {"fpl_id": 1}, {"fpl_id": 999}]
    out = build_crosswalk(players, elements, aliases)
    assert out.pairs[706] == 6 and 707 not in out.pairs and 708 not in out.pairs
    assert out.report.by_method[MANUAL_METHOD] == 1 and out.report.aliases_accepted == 1
    assert out.report.aliases_rejected == {"already_resolved_or_ambiguous": 1, "ambiguous": 1,
                                           "no_candidate": 1, "unknown_fpl_element": 1}


def test_a_missing_alias_file_is_no_aliases(tmp_path):
    assert load_aliases(tmp_path / "absent.json") == []


def test_the_alias_file_holds_fpl_ids_and_provenance_only(tmp_path):
    path = tmp_path / "aliases.json"
    good = {"fpl_id": 6, "confirmed_by": "Leo", "confirmed_on": "2026-10-26", "evidence": "club page"}
    path.write_text(json.dumps({"schema_version": 1, "aliases": [good]}))
    assert load_aliases(path) == [good]
    for bad in ({**good, "sportmonks_id": 706}, {**good, "name": "x"}, {**good, "confirmed_on": "soon"},
                {k: v for k, v in good.items() if k != "evidence"}):
        path.write_text(json.dumps({"schema_version": 1, "aliases": [bad]}))
        with pytest.raises(AliasFileError):
            load_aliases(path)
    path.write_text(json.dumps({"schema_version": 1, "aliases": [good, good]}))
    with pytest.raises(AliasFileError, match="twice"):
        load_aliases(path)


def test_the_report_is_counts_only():
    text = json.dumps(asdict(build_crosswalk(BASE_PLAYERS, BASE_ELEMENTS).report))
    assert not any(name in text for name in ("Arlo", "Quint", "Bram", "701", "1998-01-01"))


# ------------------------------------------- same pairs as the trial's reference

TRIAL_SCRIPTS = Path(__file__).resolve().parents[2] / "sportmonks-client" / "scripts"


@pytest.mark.skipif(not (TRIAL_SCRIPTS / "trial_mapping.py").exists(), reason="trial script removed")
def test_the_pairs_equal_the_trial_reference_implementation():
    sys.path.insert(0, str(TRIAL_SCRIPTS))
    try:
        import trial_mapping
        from sportmonks_client.models import Player, parse_entity
    finally:
        sys.path.remove(str(TRIAL_SCRIPTS))
    elements = BASE_ELEMENTS + [_el(4, "Dario", "Xelto", "1995-04-04"), _el(5, "Emil", "Yorn", "1994-05-05"),
                                _el(10, "Finn", "Zale", "2000-01-01"), _el(11, "Finn", "Zale", "2000-01-01", team=OTHER_FPL),
                                _el(12, "Jon", "Dree", "1990-12-12", minutes=0)]
    players = BASE_PLAYERS + [
        _pl(704, "Dario Alberto Xelto Junior", "1995-04-04", display="Dario Xelto"),
        _pl(705, "Emil Benedikt Yornsson", "1994-05-05", club=OTHER_SM, display="Emil Yorn"),
        _pl(710, "Finn Zale", "2000-01-01"), _pl(712, "Jon Dree", "1990-12-12"),
        _pl(713, "Nobody Known", "1989-01-01")]
    entities = [parse_entity(Player, p, "squads/teams/{team_id}") for p in players]
    trial = trial_mapping.fpl_side(entities, trial_mapping.fpl_people({"elements": elements}))
    assert build_crosswalk(players, elements).pairs == {int(pid): eid for pid, eid, _ in trial.pairs}
