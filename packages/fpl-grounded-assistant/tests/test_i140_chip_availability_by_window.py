"""i140 -- a chip is available when it was not played in the window that holds the GW.

FPL 2026-27 gives each chip one use per window (GW1/2-19, GW20-38). The UI's
``chips_remaining`` counted uses per SEASON (wildcard 2, the rest 1), so it
offered team 68643 a wildcard already spent in GW5 and would block every
chip from GW20. Availability is now decided once, in the response layer,
from FPL's windows (``bootstrap["chips"]``) and ``squad_context.chips_used``;
with either missing it falls back to ``chips_remaining`` and logs why.

The gameweek is the chip advice's evaluated ``gw`` (what the user asked
about), else FPL's next / current event. No network.
"""
from __future__ import annotations

import logging

import pytest

from fpl_grounded_assistant import final_response as fr
from fpl_grounded_assistant.final_response import ChipAdviceMeta, _apply_squad_overrides

CHIP_WINDOWS = [
    {"name": "wildcard", "start_event": 2, "stop_event": 19},
    {"name": "wildcard", "start_event": 20, "stop_event": 38},
    {"name": "freehit", "start_event": 2, "stop_event": 19},
    {"name": "bboost", "start_event": 1, "stop_event": 19},
    {"name": "3xc", "start_event": 1, "stop_event": 19},
    {"name": "freehit", "start_event": 20, "stop_event": 38},
    {"name": "bboost", "start_event": 20, "stop_event": 38},
    {"name": "3xc", "start_event": 20, "stop_event": 38},
]
BOOTSTRAP = {"chips": CHIP_WINDOWS}
BODY = "Lectura de la jornada."
#: What the UI sends today for 68643 (per-season count): wildcard still "remaining".
STALE_REMAINING = ["wildcard", "free_hit"]


def _chip(name: str, gw: int | None) -> ChipAdviceMeta:
    return ChipAdviceMeta(chip=name, recommendation="conditions_marginal", gw=gw,
                          signal_value=None, signal_label=None, top_player=None, evaluated_player=None)


def _apply(name, gw, used, remaining=STALE_REMAINING, bootstrap=BOOTSTRAP):
    squad = {"chips_remaining": remaining}
    if used is not None:
        squad["chips_used"] = used
    return _apply_squad_overrides(transfer=None, chip=_chip(name, gw), final_text=BODY,
                                  squad_context=squad, bootstrap=bootstrap)


# ---------------------------------------------------------------------------
# the gate's four cases
# ---------------------------------------------------------------------------

def test_wildcard_used_gw5_current_gw6_is_not_available():
    _, chip, text = _apply("wildcard", 6, [{"chip": "wildcard", "event": 5}])
    assert chip.chip_unavailable is True                       # the UI said "remaining"
    assert text.startswith("Ya usaste el Wildcard en la GW5. Vuelves a tenerlo desde la GW20.")


def test_tc_used_gw3_current_gw21_is_available():
    _, chip, text = _apply("triple_captain", 21, [{"chip": "triple_captain", "event": 3}],
                           remaining=["wildcard"])           # the UI would block it from GW20
    assert chip.chip_unavailable is False and text == BODY


def test_bb_used_gw2_and_gw22_current_gw25_is_not_available():
    used = [{"chip": "bench_boost", "event": 2}, {"chip": "bench_boost", "event": 22}]
    _, chip, text = _apply("bench_boost", 25, used, remaining=[])
    assert chip.chip_unavailable is True
    # second window: names the use in THIS window, and there is no later one to return in
    assert text.split("\n\n")[0] == "Ya usaste el Bench Boost en la GW22."


@pytest.mark.parametrize("remaining,blocked", [(["wildcard"], False), ([], True)])
def test_without_windows_it_is_todays_rule(remaining, blocked, caplog):
    with caplog.at_level(logging.INFO, logger=fr.__name__):
        _, chip, _ = _apply("wildcard", 6, [{"chip": "wildcard", "event": 5}],
                            remaining=remaining, bootstrap=None)
    assert chip.chip_unavailable is blocked
    assert "chip_availability_fallback chip=wildcard reason=no_windows" in caplog.text


# ---------------------------------------------------------------------------
# one test per guard
# ---------------------------------------------------------------------------

def test_without_chips_used_it_is_todays_rule(caplog):
    with caplog.at_level(logging.INFO, logger=fr.__name__):
        _, chip, _ = _apply("wildcard", 6, None, remaining=["wildcard"])
    assert chip.chip_unavailable is False
    assert "reason=no_chips_used" in caplog.text


def test_a_use_in_the_other_window_does_not_count():
    _, chip, _ = _apply("wildcard", 6, [{"chip": "wildcard", "event": 20}], remaining=[])
    assert chip.chip_unavailable is False


def test_another_chips_use_does_not_count():
    _, chip, _ = _apply("triple_captain", 6, [{"chip": "bench_boost", "event": 2}], remaining=[])
    assert chip.chip_unavailable is False


def test_window_edges_are_inclusive():
    _, chip, _ = _apply("wildcard", 19, [{"chip": "wildcard", "event": 2}], remaining=["wildcard"])
    assert chip.chip_unavailable is True
    _, chip, _ = _apply("wildcard", 20, [{"chip": "wildcard", "event": 19}], remaining=[])
    assert chip.chip_unavailable is False


@pytest.mark.parametrize("bad", [{"chip": "wildcard", "event": "x"}, {"chip": "wildcard"},
                                 {"chip": "wildcard", "event": 0}])
def test_an_unreadable_use_of_this_chip_falls_back(bad, caplog):
    with caplog.at_level(logging.INFO, logger=fr.__name__):
        _, chip, _ = _apply("wildcard", 6, [bad], remaining=["wildcard"])
    assert chip.chip_unavailable is False                      # today's rule, not "never used"
    assert "reason=malformed_chips_used" in caplog.text


def test_a_gw_outside_every_window_falls_back(caplog):
    with caplog.at_level(logging.INFO, logger=fr.__name__):
        _, chip, _ = _apply("wildcard", 1, [], remaining=[])     # wildcard windows start at GW2
    assert chip.chip_unavailable is True
    assert "reason=target_outside_windows" in caplog.text


def test_without_the_advice_gw_the_next_event_is_used():
    boot = {**BOOTSTRAP, "events": [{"id": 5, "is_current": True}, {"id": 6, "is_next": True}]}
    _, chip, _ = _apply("wildcard", None, [{"chip": "wildcard", "event": 5}], remaining=["wildcard"],
                        bootstrap=boot)
    assert chip.chip_unavailable is True
    boot = {**BOOTSTRAP, "events": [{"id": 20, "is_next": True}]}
    _, chip, _ = _apply("wildcard", None, [{"chip": "wildcard", "event": 5}], remaining=[], bootstrap=boot)
    assert chip.chip_unavailable is False


def test_the_use_named_is_the_one_in_the_target_window():
    used = [{"chip": "wildcard", "event": 5}, {"chip": "wildcard", "event": 21}]
    _, _, text = _apply("wildcard", 6, used, remaining=[])
    assert text.split("\n\n")[0] == "Ya usaste el Wildcard en la GW5. Vuelves a tenerlo desde la GW20."


def test_the_next_event_wins_over_the_current_one_across_a_window_edge():
    boot = {**BOOTSTRAP, "events": [{"id": 19, "is_current": True}, {"id": 20, "is_next": True}]}
    _, chip, _ = _apply("wildcard", None, [{"chip": "wildcard", "event": 5}], remaining=[], bootstrap=boot)
    assert chip.chip_unavailable is False                      # planning for GW20: a fresh window


def test_no_gw_anywhere_falls_back(caplog):
    with caplog.at_level(logging.INFO, logger=fr.__name__):
        _, chip, _ = _apply("wildcard", None, [], remaining=[])
    assert chip.chip_unavailable is True
    assert "reason=no_target_gw" in caplog.text


def test_without_any_chip_data_nothing_changes():
    _, chip, text = _apply_squad_overrides(transfer=None, chip=_chip("wildcard", 6), final_text=BODY,
                                           squad_context={"itb": 5}, bootstrap=BOOTSTRAP)
    assert chip.chip_unavailable is False and text == BODY


# ---------------------------------------------------------------------------
# what /ask serves
# ---------------------------------------------------------------------------

def _served(name: str, gw: int, used: list, remaining: list):
    from fpl_grounded_assistant.harness_adapter import to_ask_response
    from fpl_server import AskRequest
    d = {"answer_text": BODY, "chip": _chip(name, gw), "transfer": None, "selected_tool": "get_chip_advice",
         "outcome": "ok", "routing_trace": {"branch": "orchestrator", "grounded": True},
         "raw_output": {"status": "ok", "chip": name}}
    req = AskRequest(question="¿Uso el chip?", squad_context={"chips_remaining": remaining, "chips_used": used})
    return to_ask_response(d, req, BOOTSTRAP)


@pytest.mark.parametrize("name,gw,used,remaining,blocked", [
    ("wildcard", 6, [{"chip": "wildcard", "event": 5}], ["wildcard"], True),
    ("triple_captain", 21, [{"chip": "triple_captain", "event": 3}], ["wildcard"], False),
    ("bench_boost", 25, [{"chip": "bench_boost", "event": 2}, {"chip": "bench_boost", "event": 22}], [], True),
])
def test_served_chip_unavailable(name, gw, used, remaining, blocked):
    resp = _served(name, gw, used, remaining)
    assert resp.chip.get("chip_unavailable") is blocked
    assert resp.final_text.startswith("Ya usaste") is blocked
