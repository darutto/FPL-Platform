"""Jev tool router: one question in, one :class:`JevDecision` out (i115).

NOT WIRED. No serving path imports this package in i115; the shadow (i116)
and the canary (i118) are separate cards. ``tests/test_i115_jev_router.py``
fails if any module of the served path references it.

What ``route()`` does
---------------------
One POST to TypeSafe's System One API with two Choice questions asked in
parallel over the SAME state:

* ``route`` -- which tool (or composed plan) answers the question, over
  :func:`build_menu` (the measured criteria minus ``MENU_EXCLUDED``, plus the
  plans, plus ``none_of_these``);
* ``chip``  -- which chip the question names, if any.

and then applies :func:`decide`, the rule measured in the Jev pilot (eval
4/4b, 14 chip questions x 3 reps, graded by ``grade_i108_chip_two_parts``):

* take the CHIP path when the route is the chip plan, or when the route is
  ``get_my_squad`` AND the question contains a chip word from a CLOSED
  vocabulary (that code rule took the measured 11/13 to 13/13);
* the gameweek is a literal read by regex, never by a model;
* ``chip == "none"`` ESCALATES: the chip tool's enum needs a chip, and Jev is
  confident (0.90-0.94 measured) that none is named -- the blocker is the
  value, not uncertainty, so there is no confidence threshold;
* a question about several gameweeks, a range, the next N, a window, or
  WHEN to play the chip ESCALATES (i121): the chip path evaluates one GW;
* anything else ESCALATES to the full orchestrator, which is what production
  does for every question today.

Failure is a decision, never an exception: a missing key, a timeout, an HTTP
error or a malformed body all return ``path="escalate"`` with the reason.

Privacy rule (i114): the request carries the question text and nothing else
-- never a team id, user id, squad, or session history. ``route()`` takes no
context argument on purpose; a test pins its signature and the outgoing body.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

from .criteria import CRITERIA, NONE_OPTION, PLANS

#: TypeSafe native API (the pilot measured this endpoint, not the Vercel
#: gateway). Model id as the API names it.
JEV_URL: str = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL: str = "jev-latest"

#: Server-side only; never sent anywhere but the Authorization header.
API_KEY_ENV: str = "TYPESAFE_API_KEY"

#: Read at CALL time (not import time) so the value can change without a
#: redeploy. Invalid or non-positive values fall back to the default.
TIMEOUT_ENV: str = "FPL_JEV_TIMEOUT_S"
DEFAULT_TIMEOUT_S: float = 1.0

CHIP_PLAN: str = "plan_chip_general_then_my_squad"
SQUAD_TOOL: str = "get_my_squad"

#: Kept in CRITERIA (ported verbatim) but NOT offered: with the chip tool AND
#: the chip plan in one menu the chip family split three ways and confidence
#: fell to p50 0.70; without it the plan took the family at 0.94-0.98
#: (pilot eval 3 + its 1-rep variant, "E4").
MENU_EXCLUDED: frozenset[str] = frozenset({"get_chip_advice"})

#: Registered tools deliberately WITHOUT a routing criterion, with the reason.
#: A question for one of them makes Jev pick another option or none_of_these;
#: either way the chip rule does not fire and the turn escalates, i.e. is
#: served exactly as today. The catalog-sync test requires every OTHER
#: registered tool to have a criterion, and every name here to be registered.
CATALOG_EXCEPTIONS: dict[str, str] = {
    "get_zonal_weakness": "zonal family: excluded from the routing corpus (ZONAL_TOOLS), never measured",
    "get_zonal_opportunity": "zonal family: excluded from the routing corpus (ZONAL_TOOLS), never measured",
    "get_player_zonal_outlook": "zonal family: excluded from the routing corpus (ZONAL_TOOLS), never measured",
    "get_expected_minutes": "FI-7b: offered only behind the football-intelligence flag, never measured",
    "get_fixture_context": "FI-7b: offered only behind the football-intelligence flag, never measured",
    "get_player_intelligence": "FI-7b: offered only behind the football-intelligence flag, never measured",
    "get_tactical_role": "FI-7b: offered only behind the football-intelligence flag, never measured",
}

#: Closed vocabulary that promotes a get_my_squad route to the chip path.
CHIP_WORDS: re.Pattern[str] = re.compile(
    r"bench\s*boost|triple\s*captain|wildcard|free\s*hit|\bchips?\b", re.IGNORECASE
)

#: "fecha 2", "jornada 3", "GW4", "gw 5" -> the number. "esta ronda" / "la
#: próxima fecha" name no number: the chip tool resolves the current GW.
GAMEWEEK_RE: re.Pattern[str] = re.compile(
    r"\b(?:fecha|jornada|gameweek|gw)\s*(\d{1,2})\b", re.IGNORECASE
)

#: i121: the chip path evaluates ONE gameweek (the named one, or the current
#: one). A chip question that asks about several gameweeks, a range, the next
#: N, a window, or WHEN to play the chip cannot be answered by one evaluation:
#: measured in prod 2026-10-02, "free hit en la jornada 6, 7 u 8, ¿cuándo?"
#: took GW6 only and "las próximas 3 jornadas … en qué momento" took the
#: current GW only, while the orchestrator covered the range -- and the i108
#: E3 grader passed both (it checks shape, not coverage). Such a question
#: escalates, i.e. is served exactly as today. Matched on accent-folded,
#: lower-cased text. Each entry is (signal name, pattern); the name is logged.
_GW_WORD = r"(?:fechas?|jornadas?|gameweeks?|gws?|semanas?|rondas?)"
_NUM = r"\d{1,2}"
RANGE_SIGNALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # "jornada 6, 7 u 8", "fechas 6 y 7", "gw 6/7", "jornadas 6 o 7"
    ("gameweek_list", re.compile(
        rf"\b{_GW_WORD}\s*{_NUM}\s*(?:,\s*{_NUM}\s*)*(?:,|\by\b|\bu\b|\bo\b|/)\s*(?:{_GW_WORD}\s*)?{_NUM}\b")),
    # "6 a 8", "6-8", "6 al 8", "de la 6 a la 8", "gw6-gw8", "6 hasta 8" -- the
    # first number must follow a gameweek word or "la/el/de la", so prices and
    # counts ("a 5.0", "15 jugadores") do not match.
    ("gameweek_range", re.compile(
        rf"(?:\b{_GW_WORD}\s*|\b(?:de\s+)?(?:la|el)\s+){_NUM}\s*(?:-|–|\ba\b|\bal\b|\bhasta\b)\s*"
        rf"(?:la\s+|el\s+)?(?:{_GW_WORD}\s*)?{_NUM}\b")),
    # "entre la 6 y la 8", "entre las jornadas 6 y 8"
    ("gameweek_between", re.compile(
        rf"\bentre\s+(?:las?\s+|los?\s+)?(?:{_GW_WORD}\s*)?{_NUM}\s+y\s+(?:la\s+|el\s+)?(?:{_GW_WORD}\s*)?{_NUM}\b")),
    # "próximas 3 jornadas", "siguientes 4 fechas", "next 3 gameweeks"
    ("next_n", re.compile(
        rf"\b(?:proxim[oa]s|siguientes|next)\s+(?:{_NUM}|dos|tres|cuatro|cinco|seis|two|three|four|five)\s+{_GW_WORD}")),
    # "esta jornada y la próxima", "esta fecha o la siguiente"
    ("this_and_next", re.compile(r"\best[ae]\s+\w+\s+(?:y|o|u)\s+(?:la|el)\s+(?:proxim[oa]|siguiente)\b")),
    ("window", re.compile(r"\bventana\b|\bwindow\b")),
    # WHEN to play it: "¿cuándo?", "mejor momento", "en qué jornada/momento".
    # NOT "es buen momento" (= now; ad-07 in the corpus stays on the chip path).
    ("when", re.compile(rf"\bcuando\b|\bmejor\s+momento\b|\ben\s+que\s+(?:momento|{_GW_WORD})\b|\bwhen\b")),
)


def _fold(text: str) -> str:
    import unicodedata  # noqa: PLC0415

    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def range_signal(question: str) -> str | None:
    """Name of the first RANGE_SIGNALS entry the question matches, or None."""
    folded = _fold(question)
    for name, pattern in RANGE_SIGNALS:
        if pattern.search(folded):
            return name
    return None


ROUTE_INSTRUCTIONS: str = "Which tool should answer this Fantasy Premier League question first?"

CHIP_QUESTION: dict[str, Any] = {
    "type": "choice",
    "instructions": "Which FPL chip, if any, does the question ask about?",
    "criteria": {
        "bench_boost": "Bench boost.",
        "triple_captain": "Triple captain.",
        "wildcard": "Wildcard.",
        "free_hit": "Free hit.",
        "none": "No specific chip named (including a generic 'the chip' with no name, or a question not about chips).",
    },
}

PATH_CHIP: str = "chip"
PATH_ESCALATE: str = "escalate"


@dataclass(frozen=True)
class JevDecision:
    """What the router decided, and why. ``path`` is ``"chip"`` or ``"escalate"``."""

    path: str
    reason: str
    route: str | None = None
    route_confidence: float | None = None
    chip: str | None = None
    chip_confidence: float | None = None
    gameweek: int | None = None
    #: i121: which RANGE_SIGNALS entry the question matched (None: one GW).
    range_signal: str | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None


def build_menu() -> dict[str, Any]:
    """The route options sent to Jev: measured criteria minus the excluded
    tools, plus the plans, with ``none_of_these`` last."""
    menu = {k: v for k, v in CRITERIA.items() if k not in MENU_EXCLUDED and k != NONE_OPTION}
    menu.update(PLANS)
    menu[NONE_OPTION] = CRITERIA[NONE_OPTION]
    return menu


def build_request(question: str) -> dict[str, Any]:
    """The whole request body. ``state`` is the question text and nothing else."""
    return {
        "model": JEV_MODEL,
        "state": question,
        "questions": {
            "route": {"type": "choice", "instructions": ROUTE_INSTRUCTIONS, "criteria": build_menu()},
            "chip": CHIP_QUESTION,
        },
    }


def read_timeout_s() -> float:
    """``FPL_JEV_TIMEOUT_S`` at call time; the default when unset or invalid."""
    raw = os.environ.get(TIMEOUT_ENV)
    try:
        value = float(raw) if raw is not None else DEFAULT_TIMEOUT_S
    except ValueError:
        return DEFAULT_TIMEOUT_S
    return value if value > 0 else DEFAULT_TIMEOUT_S


def read_gameweek(question: str) -> int | None:
    m = GAMEWEEK_RE.search(question or "")
    return int(m.group(1)) if m else None


def decide(answers: dict[str, Any], question: str) -> JevDecision:
    """The measured rule, applied to Jev's answers. Pure: no I/O."""
    route_ans = answers.get("route") or {}
    chip_ans = answers.get("chip") or {}
    route = route_ans.get("choice")
    chip = chip_ans.get("choice")
    common = {
        "route": route,
        "route_confidence": route_ans.get("confidence"),
        "chip": chip,
        "chip_confidence": chip_ans.get("confidence"),
        "gameweek": read_gameweek(question),
        "range_signal": range_signal(question),
    }
    if not isinstance(route, str) or not isinstance(chip, str):
        return JevDecision(PATH_ESCALATE, "malformed_answer", **common)
    if route == CHIP_PLAN:
        why = "plan"
    elif route == SQUAD_TOOL and CHIP_WORDS.search(question or ""):
        why = "squad+chip_word"
    else:
        return JevDecision(PATH_ESCALATE, "not_chip_route", **common)
    if chip == "none":
        return JevDecision(PATH_ESCALATE, "chip_none", **common)
    if common["range_signal"] is not None:
        return JevDecision(PATH_ESCALATE, "gameweek_range", **common)
    return JevDecision(PATH_CHIP, why, **common)


PostFn = Callable[..., Any]


def route(question: str, *, post: PostFn | None = None) -> JevDecision:
    """Ask Jev once and decide. Never raises (``Exception``); never retries.

    ``post`` is the transport (``requests.post`` signature), injectable for
    tests. The only data that leaves the process is :func:`build_request`.
    """
    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        return JevDecision(PATH_ESCALATE, "no_api_key")
    send = post if post is not None else requests.post
    t0 = time.perf_counter()
    try:
        resp = send(
            JEV_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=build_request(question),
            timeout=read_timeout_s(),
        )
    except requests.Timeout:
        return JevDecision(PATH_ESCALATE, "timeout", latency_ms=_ms(t0))
    except Exception:  # noqa: BLE001 -- any transport failure is an escalation
        return JevDecision(PATH_ESCALATE, "transport_error", latency_ms=_ms(t0))
    latency = _ms(t0)
    status = getattr(resp, "status_code", None)
    if status != 200:
        return JevDecision(PATH_ESCALATE, f"http_{status}", latency_ms=latency)
    try:
        body = resp.json()
        answers = body["answers"]
        tokens = (body.get("usage") or {}).get("input_tokens")
    except Exception:  # noqa: BLE001 -- a body we cannot read is an escalation
        return JevDecision(PATH_ESCALATE, "malformed_response", latency_ms=latency)
    decision = decide(answers, question)
    return JevDecision(**{**decision.__dict__, "latency_ms": latency, "input_tokens": tokens})


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)
