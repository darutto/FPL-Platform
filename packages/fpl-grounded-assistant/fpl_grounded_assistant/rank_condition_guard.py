"""Brief 0a: the season ranking must never answer a conditioned question.

``rank_players_by_metric`` ranks SEASON totals. When the user's own words ask
for one gameweek, the last N, a range, a venue (home/away) or "per million",
the ranking cannot apply that condition, and returning the season table anyway
is a fluent wrong answer (status ok, real numbers, wrong quantity). This module
decides, from the user's RAW text, whether such a condition is present.

The list below is closed on purpose: it is scoped to this one tool and
temporary, until the query layer can apply the conditions itself. Misses are
expected (typos, rare phrasings) and are listed in the PR.

Two switches, independent (env, read at call time):

* ``FPL_RANK_CONDITION_GUARD`` -- default ON. Off = no condition check.
* ``FPL_RANK_SUPPRESS`` -- default OFF. On = every ranking from the tool is
  replaced by the honest line, checked first and outside any ``try``, so it
  works even if the guard code itself raises.

Fail-closed: if the guard raises, or no user text reached the handler, the
result is the honest line, never the season table. Internal (non-user)
callers say so explicitly with ``OPT_OUT_KEY``; there is no default opt-out.
"""
from __future__ import annotations

import os
import re
import unicodedata
from typing import Any, Iterable

#: Result status of a ranking that was not produced. Not "ok", not an error:
#: a tool observation that carries no rows.
STATUS_CONDITION_NOT_APPLIED = "condition_not_applied"
CODE_SEASON_ONLY = "season_ranking_only"

#: Bootstrap keys (per-turn shallow copy, see orchestrator.QUESTION_CONTEXT_KEY).
QUESTION_KEY = "_question"
RAW_QUESTION_KEY = "_raw_question"
#: Explicit opt-out for internal callers (batteries, scripts). Never a default.
OPT_OUT_KEY = "_rank_guard_internal"
#: A per-turn list the orchestrator puts in its bootstrap copy; every refusal
#: appends its conditions. A side channel on purpose: the loop flow rebuilds
#: ``tool_calls_trace`` from its own rounds and drops the evaluator retry's
#: calls, so the trace alone cannot say that a retry's ranking was refused.
EVENTS_KEY = "_rank_guard_events"

KIND_SINGLE_GW = "single_gw"
KIND_LAST_N = "last_n"
KIND_RANGE = "range"
KIND_VENUE = "venue"
KIND_PER_MILLION = "per_million"
CONDITION_KINDS: tuple[str, ...] = (
    KIND_SINGLE_GW, KIND_LAST_N, KIND_RANGE, KIND_VENUE, KIND_PER_MILLION,
)
#: Non-condition reasons, for the audit enum.
REASON_NO_TEXT = "no_text"
REASON_GUARD_ERROR = "guard_error"
REASON_SUPPRESSED = "suppressed"
AUDIT_KINDS: frozenset[str] = frozenset(CONDITION_KINDS) | {
    REASON_NO_TEXT, REASON_GUARD_ERROR, REASON_SUPPRESSED,
}

#: Tools that only anchor a turn on a gameweek. A call to one of these returning
#: ok is NOT an answer: with the ranking refused beside it the model would have
#: no data and could list players from memory. Pinned equal to
#: ``final_response.GAMEWEEK_CONTEXT_TOOLS`` by a test. ``get_my_squad`` is NOT
#: here on purpose: it hands the model the user's own squad, which it can
#: answer from without any ranking rows.
CONTEXT_ONLY_TOOLS: frozenset[str] = frozenset({"get_current_gameweek", "get_gameweek_context"})

#: Fields that really are about the current gameweek, so "esta jornada" is
#: not a condition for them (transfer momentum).
CURRENT_GW_FIELDS: frozenset[str] = frozenset({"transfers_in_event", "transfers_out_event"})


def _env_on(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "on", "yes"}


def guard_enabled() -> bool:
    return _env_on("FPL_RANK_CONDITION_GUARD", True)


def suppress_enabled() -> bool:
    return _env_on("FPL_RANK_SUPPRESS", False)


# ---------------------------------------------------------------------------
# Text folding
# ---------------------------------------------------------------------------

_NUMBER_WORDS: dict[str, str] = {
    # ES (uno/una and one are left alone: articles)
    "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5", "seis": "6",
    "siete": "7", "ocho": "8", "nueve": "9", "diez": "10", "once": "11",
    "doce": "12", "trece": "13", "catorce": "14", "quince": "15", "veinte": "20",
    # EN
    "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11",
    "twelve": "12", "fifteen": "15", "twenty": "20",
}
_WORD_RE = re.compile(r"\b(" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")\b")


def fold(text: str) -> str:
    """Lowercase, strip accents, numerals for number words, tidy spacing."""
    nfkd = unicodedata.normalize("NFKD", text)
    s = "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"[^\w\s.,£€$%/-]", " ", s)
    s = _WORD_RE.sub(lambda m: _NUMBER_WORDS[m.group(1)], s)
    return " ".join(s.split())


# ---------------------------------------------------------------------------
# Condition patterns (applied to folded text)
# ---------------------------------------------------------------------------

_W_SING = r"(?:jornada|fecha|gameweek|game ?week|gw|matchweek|mw)"
_W_PL = r"(?:jornadas|fechas|gameweeks|game ?weeks|gws|matchweeks|mws)"
_W = r"(?:jornadas?|fechas?|gameweeks?|game ?weeks?|gws?|matchweeks?|mws?)"
_UNITS_PL = rf"(?:{_W_PL}|partidos|encuentros|games|matches|semanas|weeks)"
_ORD_ES = r"(?:primera|primer|segunda|tercera|cuarta|quinta|sexta|septima|octava|novena|decima)"
_ORD_EN = r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)"
_NUM2 = r"(\d{1,2})"
# A second number that is a price ("4.5") is not a gameweek.
_NUM2_NOT_PRICE = r"(\d{1,2})(?!\d|[.,]\d)"

_SINGLE_GW = [
    re.compile(rf"\b{_W}\s*[-#]?\s*{_NUM2}\b"),
    re.compile(rf"\b(?:j|gw|mw)-?{_NUM2}\b"),
    re.compile(rf"\b{_NUM2}\s*(?:st|nd|rd|th|a|o)?\s+{_W_SING}\b"),
    re.compile(rf"\b(?:ultima|pasada|anterior|previa|proxima|siguiente)\s+{_W_SING}\b"),
    re.compile(rf"\b{_W_SING}\s+(?:pasada|anterior|previa|ultima|proxima|siguiente)\b"),
    re.compile(r"\b(?:last|previous|prior|latest|next|upcoming)\s+(?:gameweek|game ?week|gw|matchweek)\b"),
    # a past/next WEEK is a gameweek for this product (Latin American "semana")
    re.compile(r"\b(?:semana|week)\s+(?:pasada|anterior|previa|proxima|siguiente)\b"),
    re.compile(r"\b(?:ultima|pasada|proxima|siguiente)\s+semana\b"),
    re.compile(r"\b(?:last|previous|prior|next|upcoming)\s+week\b"),
    # ordinals: "la primera jornada", "the third gameweek"
    re.compile(rf"\b{_ORD_ES}\s+{_W_SING}\b"),
    re.compile(rf"\b{_ORD_EN}\s+(?:gameweek|game ?week|gw|matchweek)\b"),
]
_CURRENT_GW = re.compile(
    r"\b(?:esta|actual|presente)\s+(?:jornada|fecha|semana)\b"
    r"|\b(?:jornada|fecha|semana)\s+(?:actual|en curso)\b"
    r"|\b(?:this|current)\s+(?:gameweek|game ?week|gw|matchweek|week)\b|\bgw\s+actual\b"
)
_LAST_N = [
    re.compile(rf"\b(?:ultim[oa]s?|recientes?|last|past|previous|prior|latest|recent)\s+(?:(?:the|las|los|la)\s+)?{_NUM2}\b"),
    re.compile(rf"\b(?:ultimas|ultimos|last|past|previous|recent|recientes)\s+(?:(?:the|las|los|la)\s+)?{_UNITS_PL}\b"),
    re.compile(rf"\b{_NUM2}\s+(?:ultimas|ultimos|last|latest|past|previous)\s+{_UNITS_PL}\b"),
    re.compile(rf"\b{_W_PL}\s+(?:recientes|recent|pasadas|anteriores)\b"),
]
_RANGE = [
    re.compile(
        rf"\b{_W}\s*{_NUM2}\s*(?:-|a|al|to|through|thru|hasta|y|and|until)\s*"
        rf"(?:la\s+|the\s+)?(?:{_W_SING}\s*)?{_NUM2_NOT_PRICE}"
    ),
    re.compile(
        rf"\b(?:desde|from|since|a partir de|starting|after|despues de|hasta|until|through|up to)\s+"
        rf"(?:la\s+|the\s+)?{_W}\s*{_NUM2}\b"
    ),
]
#: "first five gameweeks" and "next 5 gameweeks": a season table is just as wrong
#: there, and they are reported as a range.
_RANGE.extend([
    re.compile(rf"\b(?:primeras|primeros)\s+(?:{_NUM2}\s+)?{_UNITS_PL}\b"),
    re.compile(rf"\bfirst\s+(?:{_NUM2}\s+)?{_UNITS_PL}\b"),
    re.compile(rf"\b(?:proximas|proximos|siguientes|next|upcoming|coming)\s+(?:{_NUM2}\s+)?(?:{_UNITS_PL}|fixtures)\b"),
])
_VENUE = re.compile(
    r"\bfuera de casa\b|\bde visitante\b|\bcomo visitante\b|\bde visita\b|\bvisitantes?\b"
    r"|\ben casa\b|\bde local(?:es)?\b|\bcomo local(?:es)?\b|\bat home\b|\bhome\b|\baway\b(?! from)"
    r"|\bon the road\b|\broad games?\b"
)
_PER_MILLION = re.compile(
    r"\b(?:por|per)\s+(?:cada\s+|each\s+)?(?:1\s+)?(?:millon(?:es)?|million|libra|libras|pound|pounds)\b"
    r"|(?:\bper|\bpor)\s+(?:cada\s+)?[£€$]\s*1?\s*m?\b"
    r"|\bppm\b|\bvalue for money\b|\bvalor por dinero\b"
)


def _any(patterns: Iterable[re.Pattern[str]], s: str) -> bool:
    return any(p.search(s) for p in patterns)


def detect_conditions(text: "str | None", *, field: "str | None" = None) -> tuple[str, ...]:
    """The unapplied-condition kinds named in *text* (enum values, ordered).

    ``field`` is the resolved metric: "esta jornada" only counts as a condition
    for metrics that are not about the current gameweek.
    """
    if not isinstance(text, str) or not text.strip():
        return ()
    s = fold(text)
    kinds: list[str] = []
    ranged = _any(_RANGE, s)
    if ranged:
        kinds.append(KIND_RANGE)
    single = _any(_SINGLE_GW, s)
    if _CURRENT_GW.search(s) and field not in CURRENT_GW_FIELDS:
        single = True
    if single and not ranged:
        kinds.append(KIND_SINGLE_GW)
    if _any(_LAST_N, s):
        kinds.append(KIND_LAST_N)
    if _VENUE.search(s):
        kinds.append(KIND_VENUE)
    if _PER_MILLION.search(s):
        kinds.append(KIND_PER_MILLION)
    return tuple(kinds)


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------

def _texts(bootstrap: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in (RAW_QUESTION_KEY, QUESTION_KEY):
        value = bootstrap.get(key)
        if isinstance(value, str) and value.strip() and value not in out:
            out.append(value)
    return out


def user_texts(bootstrap: dict[str, Any]) -> list[str]:
    """The user's raw text and the (possibly rewritten) question, deduplicated."""
    return _texts(bootstrap)


def note_refusal(bootstrap: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    """Record a refusal on the turn's event list (when there is one); returns *output*."""
    try:
        events = bootstrap.get(EVENTS_KEY)
        if isinstance(events, list):
            events.append(list(output.get("conditions") or []))
    except Exception:  # noqa: BLE001 - observability only, never the answer
        pass
    return output


def refusal_output(kinds: Iterable[str], reason: "str | None" = None) -> dict[str, Any]:
    """The tool result for a ranking that was not produced. No rows, ever."""
    kinds = tuple(k for k in kinds if k in AUDIT_KINDS)
    conditions = list(kinds) if kinds else ([reason] if reason in AUDIT_KINDS else [])
    return {
        "status": STATUS_CONDITION_NOT_APPLIED,
        "code": CODE_SEASON_ONLY,
        "conditions": conditions,
        "message": (
            "No ranking was produced: this tool only ranks the whole season and "
            "cannot apply what the user asked for. Say so plainly; do not "
            "estimate or list players from memory."
        ),
    }


def evaluate(bootstrap: dict[str, Any], field: "str | None") -> "dict[str, Any] | None":
    """The refusal for this ranking, or ``None`` when it may be served.

    Never raises: any failure inside the check is itself a refusal.
    """
    try:
        if not guard_enabled():
            return None
        if bootstrap.get(OPT_OUT_KEY) is True:
            return None
        texts = _texts(bootstrap)
        if not texts:
            return refusal_output((), REASON_NO_TEXT)
        kinds: list[str] = []
        for text in texts:
            for kind in detect_conditions(text, field=field):
                if kind not in kinds:
                    kinds.append(kind)
        if kinds:
            return refusal_output(kinds)
        return None
    except Exception:  # noqa: BLE001 - fail closed, by design
        return refusal_output((), REASON_GUARD_ERROR)


def rewrite_only_conditions(bootstrap: dict[str, Any], field: "str | None") -> bool:
    """True when only the rewritten question (not the raw text) names a condition."""
    try:
        raw = bootstrap.get(RAW_QUESTION_KEY)
        rewritten = bootstrap.get(QUESTION_KEY)
        return bool(
            isinstance(raw, str) and isinstance(rewritten, str) and raw != rewritten
            and not detect_conditions(raw, field=field)
            and detect_conditions(rewritten, field=field)
        )
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Wording (code-written, ES / EN)
# ---------------------------------------------------------------------------

def guard_line(output: dict[str, Any], locale: str = "es") -> str:
    """The honest line for a ``condition_not_applied`` result."""
    from .catalogue import t  # noqa: PLC0415  (leaf import, avoids a cycle at load)

    loc = "en" if locale == "en" else "es"
    conditions = [c for c in (output.get("conditions") or []) if c in CONDITION_KINDS]
    if not conditions:
        return t("rank_guard.line_generic", loc)  # type: ignore[arg-type]
    names = ", ".join(t(f"rank_guard.kind.{c}", loc) for c in conditions)  # type: ignore[arg-type]
    return t("rank_guard.line", loc, conditions=names)  # type: ignore[arg-type]
