"""FPL's out-news on a match where the player was not in the XI: attributed only when dated before that match.

Policy (decided with the reviewer): FPL gives only the CURRENT news, so it is never walked back to a match that
predates its own news_added; it is 'observed' from FPL and never a cause; no date, no attribution.
"""
from __future__ import annotations

import copy

import pytest

from fpl_grounded_assistant.atomic_tool_cards import compose_position_changes_card
from fpl_grounded_assistant.position_changes_tool import attach_fpl_out, fpl_out_notice, run_position_changes
from fpl_grounded_assistant.renderer import render
from fpl_grounded_assistant.tool_schema_registry import GET_POSITION_CHANGES_SCHEMA

from test_b4_position_changes_tool import BOOTSTRAP, FPL_FIXTURES, PEDRO, FakeHandle, _tables

# João Pedro is in the Chelsea squad list but not in the XI of fixture 4 (GW4, kicks off 2026-11-23T15:00Z).


def _run(status="i", news="Knee injury - Unknown return date", added="2026-11-20T10:00:00.123456Z", **extra):
    bootstrap = copy.deepcopy(BOOTSTRAP)
    for e in bootstrap["elements"]:
        if e["id"] == PEDRO:
            e.update(status=status, news=news, news_added=added, **extra)
    return run_position_changes({"player": "João Pedro Junqueira de Jesus"}, bootstrap, handle=FakeHandle(_tables()),
                                fetch_fixtures=lambda: FPL_FIXTURES)


def _out(result):
    return {m["gameweek"]: m.get("fpl_out") for m in result["matches"]}


def test_a_dated_notice_before_the_match_is_attached_as_observed_from_fpl():
    result = _run()
    gw4 = next(m for m in result["matches"] if m["gameweek"] == 4)
    assert gw4["player_status"] == "not_listed"
    assert gw4["fpl_out"] == {"reason": "knee", "since": "2026-11-20", "claim_status": "observed", "source": "fpl"}
    # He started in GW1, 2, 3 and 5 (never marked, whatever the news says); GW4 is the only match he was not in.
    assert {m["gameweek"]: m["player_status"] for m in result["matches"]} == {1: "started", 2: "started", 3: "started",
                                                                              4: "not_listed", 5: "started"}
    assert [gw for gw, o in _out(result).items() if o] == [4]


@pytest.mark.parametrize("kwargs", [
    {"added": "2026-11-25T10:00:00Z"},   # news is LATER than the match: not walked back
    {"added": None},                      # no date: nothing is attributed
    {"added": ""},
    {"added": "garbage"},
    {"status": "d"},                      # doubtful is not out
    {"status": "a"},
])
def test_without_a_date_before_the_match_the_row_stays_as_it_is(kwargs):
    gw4 = next(m for m in _run(**kwargs)["matches"] if m["gameweek"] == 4)
    assert "fpl_out" not in gw4


def test_the_dates_are_compared_in_utc():
    # 23:30 on the 22nd in UTC-5 is 04:30 UTC on the 23rd: still before the 15:00Z kickoff
    assert "fpl_out" in next(m for m in _run(added="2026-11-22T23:30:00-05:00")["matches"] if m["gameweek"] == 4)
    # 15:00Z exactly is not before the kickoff
    assert "fpl_out" not in next(m for m in _run(added="2026-11-23T15:00:00Z")["matches"] if m["gameweek"] == 4)


@pytest.mark.parametrize("status,news,reason", [
    ("i", "Hamstring injury - Expected back 23 Nov", "hamstring"),
    ("i", "Expected back 3 Dec", "injury"),           # 'back' in the tail is not a back injury
    ("i", "Some unknown knock - 25% chance of playing", "injury"),
    ("s", "Suspended until 9 Dec", "suspension"),
    ("u", "Has left the club", "unavailable"),
])
def test_reason_words_come_from_the_head_of_the_news_and_unknown_is_generic(status, news, reason):
    notice = fpl_out_notice({"elements": [{"id": 1, "status": status, "news": news, "news_added": "2026-10-17T10:00:00Z"}]}, 1)
    assert notice["reason"] == reason


def test_the_text_in_both_languages_with_the_dates_the_reviewer_asked_for():
    result = _run()
    es, en = render("get_position_changes", result, locale="es"), render("get_position_changes", result, locale="en")
    assert "baja: lesión de rodilla (FPL, 20/11)" in es and "Consta como baja en FPL desde el 20/11" in es
    assert "out: knee injury (FPL, 20 Nov)" in en and "Listed as out in FPL since 20 Nov" in en
    for text in (es, en):
        assert "no jugó porque" not in text.lower() and "did not play because" not in text.lower()


def test_a_row_without_notice_renders_exactly_as_before():
    result = _run(added=None)
    for locale in ("es", "en"):
        text = render("get_position_changes", result, locale=locale)
        assert "FPL" not in text.replace("Source", "")  # no FPL attribution anywhere
        assert "baja:" not in text and "out:" not in text


def test_the_card_note_carries_the_same_text():
    card = compose_position_changes_card(_run(), "en")
    notes = [row[-1] for row in card.rows] if hasattr(card, "rows") else []
    assert any("out: knee injury (FPL, 20 Nov)" in str(n) for n in notes)


def test_the_tool_description_allows_one_phrase_and_forbids_a_cause():
    d = GET_POSITION_CHANGES_SCHEMA.description
    assert "consta como baja en FPL desde el 17/10" in d and "listed as out in FPL since 17 Oct" in d
    assert "no jugo porque" in d


def test_attach_is_a_no_op_without_a_notice():
    matches = [{"player_status": "not_listed", "kickoff": "2026-11-23T15:00:00Z"}]
    assert attach_fpl_out(matches, None) == 0 and "fpl_out" not in matches[0]
