"""i121 -- a chip question about a RANGE of gameweeks escalates; and a coverage
check the i108 E3 grader cannot make.

No network: every Jev answer here is recorded (the prod shadow of 2026-10-02
and the pilot's eval 4b), and an autouse guard fails the test on any real
TypeSafe call.

What this file pins
-------------------
A. The two prod turns that exposed the gap now ESCALATE with reason
   ``gameweek_range`` from the very Jev answers recorded in prod; the other
   four prod turns decide exactly as they did (no collateral change).
B. The 14 i108 chip questions (i115's recording) still decide as before: none
   of them carries a range signal.
C. ``range_signal`` on written positives and negatives, including the traps
   (prices, counts, "es buen momento" = now).
D. ``chip=none`` keeps precedence: a range question naming no chip is still
   ``chip_none``, not ``gameweek_range``.
E. The shadow row logs ``range_signal``.
F. ``scripts/check_jev_range_coverage.py``: on the recorded prod rows it flags
   exactly the two range turns; on the same turns re-decided by the fixed
   rule it flags nothing, because they no longer take the chip path. It reads
   what was asked from the question with its OWN parser and what was answered
   from the executed ``chip_args`` -- never from the router's logged signal.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
import requests

import fpl_grounded_assistant  # noqa: F401
from fpl_grounded_assistant.jev_router import router as jr
from fpl_grounded_assistant.jev_router import shadow

PKG = Path(__file__).resolve().parents[1]
PROD = json.loads((PKG / "tests/fixtures/jev_router_i121_prod_shadow_answers.json").read_text(encoding="utf-8"))["rows"]
PILOT = json.loads((PKG / "tests/fixtures/jev_router_i115_recorded_answers.json").read_text(encoding="utf-8"))["rows"]

#: Written from the question text: the two turns that asked a span.
RANGE_TURNS = {"aef9ef7e2ebe48809b5954b1a9760e84", "f922830239d14d25ad7cd3e917d4ede8"}


@pytest.fixture(autouse=True)
def _no_real_typesafe(monkeypatch: pytest.MonkeyPatch) -> None:
    real = requests.Session.request

    def guarded(self: Any, method: str, url: str, *a: Any, **kw: Any) -> Any:
        if "typesafe.ai" in str(url):
            pytest.fail(f"real TypeSafe call from a test: {method} {url}")
        return real(self, method, url, *a, **kw)

    monkeypatch.setattr(requests.Session, "request", guarded)


def _checker() -> Any:
    spec = importlib.util.spec_from_file_location("_cov", PKG / "scripts" / "check_jev_range_coverage.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ A. prod turns

def test_prod_fixture_holds_the_six_shadowed_turns() -> None:
    assert len(PROD) == 6 and RANGE_TURNS <= {r["turn_id"] for r in PROD}


@pytest.mark.parametrize("row", PROD, ids=lambda r: r["turn_id"][:8])
def test_prod_turns_decide_as_intended(row: dict[str, Any]) -> None:
    d = jr.decide(row["answers"], row["question"])
    if row["turn_id"] in RANGE_TURNS:
        assert (d.path, d.reason) == ("escalate", "gameweek_range")
        assert d.range_signal is not None
    else:
        # unchanged from what prod recorded before i121
        assert (d.path, d.reason) == (row["recorded_layer1"]["path"], row["recorded_layer1"]["reason"])
        assert d.range_signal is None


# ------------------------------------------------------------------ B. the 14 chip ids

@pytest.mark.parametrize("row", PILOT, ids=lambda r: f"{r['question_id']}-rep{r['rep']}")
def test_i108_chip_questions_carry_no_range_signal(row: dict[str, Any]) -> None:
    assert jr.range_signal(row["question"]) is None
    assert jr.decide(row["answers"], row["question"]).reason != "gameweek_range"


# ------------------------------------------------------------------ C. the signal itself

RANGE_QUESTIONS = [
    ("¿Usar free hit en la jornada 6, 7 u 8? ¿Cuándo es el mejor momento?", "gameweek_list"),
    ("bench boost en las fechas 6 y 7", "gameweek_list"),
    ("¿bench boost en la jornada 6 o 7?", "gameweek_list"),
    ("bench boost jornada 10/11", "gameweek_list"),
    ("triple captain GW6-GW8", "gameweek_range"),
    ("wildcard gw 8 a 10", "gameweek_range"),
    ("free hit de la 10 a la 12", "gameweek_range"),
    ("wildcard entre la 6 y la 8", "gameweek_between"),
    ("free hit en las próximas 3 jornadas", "next_n"),
    ("next 3 gameweeks bench boost?", "next_n"),
    ("¿bench boost esta jornada o la próxima?", "this_and_next"),
    ("¿Uso el free hit en la ventana de dobles?", "window"),
    ("¿cuál es el mejor momento para el wildcard?", "when"),
    ("¿en qué jornada uso el triple captain?", "when"),
    ("¿Cuándo tiro el bench boost?", "when"),
]

SINGLE_QUESTIONS = [
    "¿Es buen momento para usar el free hit?",            # = now (ad-07)
    "¿Debería activar el bench boost esta jornada?",
    "¿Qué tan recomendable es usar la wildcard en la siguiente fecha?",
    "¿Debería usar el chip de bench boost en la próxima fecha?",
    "Fecha 2: ¿bench boost sí o no?",
    "¿Tiro el bench boost en la GW 12 con 15 jugadores?",  # a count, not a span
    "bench boost con 4 suplentes a 5.0",                  # a price after "a"
    "¿Uso el triple captain con Haaland a 14.5 en la fecha 7?",
    "¿Conviene el bench boost en la fecha 2 si tengo 3 jugadores del Arsenal?",
    "¿Triple captain a Saka en la fecha 7 si el Arsenal ganó 3 a 1 la anterior?",  # a scoreline
    "¿Bench boost esta fecha con defensas de 4 a 5 millones en el banco?",         # a price span
]


@pytest.mark.parametrize("question,signal", RANGE_QUESTIONS)
def test_range_questions_are_detected(question: str, signal: str) -> None:
    assert jr.range_signal(question) == signal


@pytest.mark.parametrize("question", SINGLE_QUESTIONS)
def test_single_gameweek_questions_are_not(question: str) -> None:
    assert jr.range_signal(question) is None


def test_range_on_the_chip_path_escalates() -> None:
    d = jr.decide({"route": {"choice": jr.CHIP_PLAN}, "chip": {"choice": "free_hit"}},
                  "¿free hit en la jornada 6, 7 u 8?")
    assert (d.path, d.reason, d.range_signal) == ("escalate", "gameweek_range", "gameweek_list")


# ------------------------------------------------------------------ D. precedence

def test_chip_none_keeps_precedence_over_range() -> None:
    d = jr.decide({"route": {"choice": jr.CHIP_PLAN}, "chip": {"choice": "none"}},
                  "¿uso el chip en las próximas 3 jornadas?")
    assert d.reason == "chip_none"


def test_non_chip_route_with_a_range_is_still_not_chip_route() -> None:
    d = jr.decide({"route": {"choice": "get_fixture_outlook"}, "chip": {"choice": "none"}},
                  "¿cómo viene el Arsenal en las próximas 3 jornadas?")
    assert d.reason == "not_chip_route"


# ------------------------------------------------------------------ E. logged

def test_shadow_row_logs_the_range_signal() -> None:
    d = jr.decide({"route": {"choice": jr.CHIP_PLAN}, "chip": {"choice": "wildcard"}},
                  "wildcard entre la 6 y la 8")
    assert shadow._decision_dict(d)["range_signal"] == "gameweek_between"


# ------------------------------------------------------------------ F. coverage check

def _as_audit_and_shadow(rows: list[dict[str, Any]], redecide: bool) -> tuple[list[dict], list[dict]]:
    audit, shadow_rows = [], []
    for r in rows:
        audit.append({"turn_id": r["turn_id"], "question": r["question"]})
        if redecide:
            d = jr.decide(r["answers"], r["question"])
            layer1 = {"path": d.path, "reason": d.reason}
            chip_args = ({"chip": d.chip, **({"gameweek": d.gameweek} if d.gameweek is not None else {})}
                         if d.path == "chip" else None)
        else:
            layer1, chip_args = r["recorded_layer1"], r["recorded_chip_args"]
        shadow_rows.append({"turn_id": r["turn_id"], "layer1": layer1,
                            "layer2": {"chip_args": chip_args} if chip_args else None})
    return audit, shadow_rows


def test_coverage_check_flags_exactly_the_prod_range_turns() -> None:
    found = _checker().violations(*_as_audit_and_shadow(PROD, redecide=False))
    assert {v["turn_id"] for v in found} == RANGE_TURNS
    by_id = {v["turn_id"]: v for v in found}
    assert by_id["f922830239d14d25ad7cd3e917d4ede8"]["asked"] == [6, 7, 8]
    assert by_id["f922830239d14d25ad7cd3e917d4ede8"]["evaluated_gameweek"] == 6


def test_coverage_check_is_clean_once_the_rule_escalates_them() -> None:
    assert _checker().violations(*_as_audit_and_shadow(PROD, redecide=True)) == []


def test_coverage_check_flags_a_wrong_single_gameweek() -> None:
    audit = [{"turn_id": "t1", "question": "¿bench boost en la fecha 7?"}]
    shadow_rows = [{"turn_id": "t1", "layer1": {"path": "chip"}, "layer2": {"chip_args": {"chip": "bench_boost", "gameweek": 6}}}]
    assert [v["flag"] for v in _checker().violations(audit, shadow_rows)] == ["wrong_gameweek"]


def test_coverage_check_does_not_trust_the_router_signal() -> None:
    """A chip-path row whose router logged no range must still be flagged when
    the question asked one -- the checker parses the question itself."""
    audit = [{"turn_id": "t1", "question": "free hit en la jornada 6, 7 u 8"}]
    shadow_rows = [{"turn_id": "t1", "layer1": {"path": "chip", "range_signal": None},
                    "layer2": {"chip_args": {"chip": "free_hit", "gameweek": 6}}}]
    assert [v["flag"] for v in _checker().violations(audit, shadow_rows)] == ["asked_several"]
