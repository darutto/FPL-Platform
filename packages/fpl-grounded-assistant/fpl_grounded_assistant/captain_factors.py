"""Plain-language captaincy factors, phrased once for every surface.

Why this module exists
----------------------
A ranking answers "who scores highest". It does not answer "why is the player
I asked about below him", and that is the question people actually arrive with.
Someone asking about Haaland reads "your pick 71.1, best available 82.2" and
learns nothing about him playing every minute, taking the penalties, and being
in the same fixture as the name above him.

So the factors are shown *beside* the score, never folded into it. Nothing here
changes a captain score; these functions only describe inputs that already
exist.

Two rules are load-bearing:

* **Name the factor, never its coefficient.** "Form moves the score more than
  anything else" informs; "form is 40% of the calculation" publishes the model.
  No function here returns a weight, a threshold or a cutoff, and the prompt
  layer must not be handed one either.
* **Opportunity, not alarm.** A partial minutes share is context for a
  decision, not a warning, and it is never rendered as a danger.

The card and the prose both call these, so the same player cannot be described
with two different figures.
"""
from __future__ import annotations

from typing import Any, Mapping

Locale = str


def minutes_phrase(
    minutes_context: Mapping[str, Any] | None,
    locale: Locale = "es",
) -> str | None:
    """Say how much of the available football a player has actually played.

    Returns ``None`` when participation could not be derived, so a caller shows
    nothing rather than a confident-sounding blank.
    """
    if not isinstance(minutes_context, Mapping):
        return None
    played = minutes_context.get("minutes_played")
    available = minutes_context.get("minutes_available")
    starts = minutes_context.get("starts")
    if minutes_context.get("degraded") or played is None or not available:
        return None

    if locale == "es":
        phrase = f"jugó {played} de {available} minutos posibles"
        if isinstance(starts, int) and starts >= 0:
            phrase += f", {starts} " + ("titularidad" if starts == 1 else "titularidades")
        return phrase
    phrase = f"played {played} of {available} available minutes"
    if isinstance(starts, int) and starts >= 0:
        phrase += f", {starts} start" + ("" if starts == 1 else "s")
    return phrase


def penalties_phrase(
    penalties_order: int | None,
    locale: Locale = "es",
) -> str | None:
    """Say whether the player takes the penalties. Absence is not a negative."""
    if penalties_order is None:
        return None
    try:
        order = int(penalties_order)
    except (TypeError, ValueError):
        return None
    if order <= 0:
        return None
    if locale == "es":
        return "lanza los penaltis" if order == 1 else f"penaltis, {order}º en la lista"
    return "takes the penalties" if order == 1 else f"penalties, {order} in line"


def factor_phrases(
    entry: Mapping[str, Any],
    locale: Locale = "es",
) -> list[str]:
    """Every visible factor for one ranked entry, in reading order."""
    role_signals = entry.get("role_signals") or {}
    penalties_order = entry.get("penalties_order", role_signals.get("penalties_order"))
    phrases = [
        minutes_phrase(entry.get("minutes_context"), locale),
        penalties_phrase(penalties_order, locale),
    ]
    return [phrase for phrase in phrases if phrase]


def full_participation(minutes_context: Mapping[str, Any] | None) -> bool:
    """True only when participation was derived and is complete."""
    if not isinstance(minutes_context, Mapping):
        return False
    if minutes_context.get("degraded"):
        return False
    return minutes_context.get("participation_percent") == 100.0


def contradiction_note(
    entry: Mapping[str, Any],
    better_ranked: list[Mapping[str, Any]],
    locale: Locale = "es",
) -> str | None:
    """Say so when the order and the visible factors disagree.

    The failure this exists to prevent has happened twice already in this
    product: two parts of the system assert opposite things and the reader
    believes whichever is louder. Here the score is louder. So when a player
    sits below others despite playing every available minute and taking the
    penalties while they do neither, the row says it outright instead of
    leaving the number to speak alone.

    Only genuine conflicts are annotated. A row without a note means there is
    no surprise in it — which is only true if notes stay rare.
    """
    if not full_participation(entry.get("minutes_context")):
        return None
    role_signals = entry.get("role_signals") or {}
    takes_penalties = (
        entry.get("penalties_order", role_signals.get("penalties_order")) == 1
    )
    if not takes_penalties:
        return None

    outranked_with_less = [
        other
        for other in better_ranked
        if not full_participation(other.get("minutes_context"))
    ]
    if not outranked_with_less:
        return None

    if locale == "es":
        return (
            "Juega todos los minutos y lanza los penaltis, y aun así puntúa por "
            "debajo: lo que más mueve la puntuación es la forma reciente, no el "
            "minutaje."
        )
    return (
        "Plays every available minute and takes the penalties, yet scores lower: "
        "what moves the score most is recent form, not minutes."
    )


#: Said wherever the triple captain is offered. The chip doubles the captain's
#: return, and people read that as doubling the upside only.
TRIPLE_CAPTAIN_RISK_NOTE = {
    "es": (
        "El triple capitán multiplica lo que pase, en los dos sentidos: si el "
        "jugador no suma, la jornada se resiente el triple."
    ),
    "en": (
        "The triple captain multiplies whatever happens, both ways: if the "
        "player blanks, the gameweek takes three times the hit."
    ),
}
