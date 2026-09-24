"""
fpl_grounded_assistant.chip_two_part
======================================
i108 E3: a chip answer in two parts -- GENERAL, then PARTICULAR.

1. General: this gameweek's verdict for the chip, and the favoured group
   (``signals.favoured_teams`` / ``signals.favoured_players``) named.
2. Particular: the user's squad against that group, read from the tool's
   ``squad_fit`` / ``squad_source`` / ``linked_squad_error`` -- never from the
   model's own reading of a squad.

Who writes what (decided after two measured rounds, i108 E3)
-------------------------------------------------------------
Both parts are computed facts, so neither depends on the model copying them:
``compose_chip_answer`` PREPENDS the general header (verdict label + favoured
group, read from the tool output) and APPENDS the particular sentence
(``particular_phrase``). The model writes only the body in between
(``chip_composition_rule``). Always general -> particular, even when the user
asks about their squad first -- the product owner's decision.

One source of truth
-------------------
The phrases below are the ONLY copy of the wording. The composer, the prompt
rule and the gate's grader (``scripts/grade_i108_chip_two_parts.py``) all
import them, so what is written and what the grader looks for cannot drift.

Framing (product rule, not local to chips): opportunity, never transaction
words -- no comprar / vender / fichar, not even to deny them. The
``needs_transfers`` verdict is expressed as what is missing to get the most
out of the chip.

Pure module: no imports from the live stack.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

#: Chips that carry a squad_fit (i108 E2). Triple captain has no particular
#: part yet -- whether it should is an open question for the product owner.
SQUAD_FIT_CHIPS: tuple[str, ...] = ("bench_boost", "wildcard", "free_hit")

#: Part 1 -- the verdict label the general part opens with, per recommendation.
GENERAL_VERDICT_LABEL: dict[str, str] = {
    "conditions_favorable":   "jornada favorable",
    "conditions_marginal":    "jornada a medias",
    "conditions_unfavorable": "jornada poco favorable",
}

#: Part 2 -- one phrase per outcome. ``{n}`` is squad_fit.missing_count.
PARTICULAR_PHRASE: dict[str, str] = {
    "set":             "ya tienes el grupo favorecido",
    # Round 2 copy (after round 1 of the gate): "jugadores" added -- the form
    # the model wrote on its own; the grader still demands this exact phrase.
    "needs_transfers": "te faltan {n} jugadores del grupo favorecido para sacarle todo al chip",
    "not_applicable":  "esta jornada no es buena para este chip, ni para ti ni para nadie",
    "invite":          "enlaza tu equipo y te digo si ya tienes el grupo favorecido",
    "fetch_failed":    "no pude cargar tu plantilla",
}

#: Openings the no-team arm must never start with (the pre-E3 failure).
FORBIDDEN_OPENINGS: tuple[str, ...] = (
    "no puedo evaluar tu equipo",
    "no puedo evaluar tu plantilla",
)


def particular_outcome(chip_output: dict[str, Any]) -> str | None:
    """Which PARTICULAR_PHRASE key the tool output calls for, or ``None``.

    ``None`` means no particular part is expected: a chip outside
    ``SQUAD_FIT_CHIPS``, a non-ok output, or members known but no fit
    computable (``missing_context`` / undeterminable bench).
    """
    if not isinstance(chip_output, dict) or chip_output.get("status") != "ok":
        return None
    if chip_output.get("chip") not in SQUAD_FIT_CHIPS:
        return None
    if chip_output.get("linked_squad_error") == "fetch_failed":
        return "fetch_failed"
    fit = chip_output.get("squad_fit")
    if isinstance(fit, dict) and fit.get("verdict") in PARTICULAR_PHRASE:
        return fit["verdict"]
    if chip_output.get("squad_source") is None:
        return "invite"
    return None


def particular_phrase(chip_output: dict[str, Any]) -> str | None:
    """The exact phrase the answer must contain for *chip_output*, or ``None``."""
    outcome = particular_outcome(chip_output)
    if outcome is None:
        return None
    phrase = PARTICULAR_PHRASE[outcome]
    if outcome == "needs_transfers":
        phrase = phrase.format(n=int(chip_output["squad_fit"]["missing_count"]))
    return phrase


#: How each squad-fit chip is named in the header.
CHIP_DISPLAY: dict[str, str] = {
    "bench_boost": "Bench Boost",
    "wildcard":    "Wildcard",
    "free_hit":    "Free Hit",
}

#: At most this many favoured players are named in the header.
_HEADER_MAX_PLAYERS: int = 5


def chip_composition_rule() -> str:
    """The CHIP_COMPOSITION constraint line for the orchestrator system prompt."""
    return (
        "  - CHIP_COMPOSITION: when get_chip_advice ran for bench_boost, wildcard or "
        "free_hit, the system itself adds the opening verdict line with the favoured "
        "group, and a closing sentence about the user's squad (from squad_fit / "
        "squad_source / linked_squad_error). Write ONLY the body in between: why, from "
        "the tool's signals (fixtures, FDR, the favoured teams and players, the chip "
        "window). Do NOT write a verdict or title line, and do NOT write anything about "
        "whether the user's squad holds the group or about linking a team -- both are "
        "added for you (the squad fields are not in the tool output you see). With a "
        "linked team the tool has ALREADY evaluated the user's squad: do not call "
        "get_my_squad for a chip question, and never open with 'no "
        "puedo evaluar tu equipo'. Frame it as the opportunity; no comprar/vender/"
        "fichar or transfer words, not even to deny them.\n"
    )


def last_chip_output(trace: Any) -> dict[str, Any] | None:
    """The last ok ``get_chip_advice`` output in a tool-call trace, or ``None``."""
    last: dict[str, Any] | None = None
    for entry in trace or ():
        if isinstance(entry, dict) and entry.get("name") == "get_chip_advice":
            output = entry.get("output")
            if isinstance(output, dict) and output.get("status") == "ok":
                last = output
    return last


def _join_es(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " y " + items[-1]


def general_header(chip_output: dict[str, Any], team_names: dict[int, str]) -> str | None:
    """``**Bench Boost — jornada favorable.** Grupo favorecido: …``, or ``None``.

    ``None`` when there is nothing general to say deterministically: a chip
    outside ``SQUAD_FIT_CHIPS``, a non-ok output, or a recommendation without
    a label (``missing_context``). Teams are named by the id the tool
    returned (full name from the bootstrap, short code as fallback).
    """
    if not isinstance(chip_output, dict) or chip_output.get("status") != "ok":
        return None
    chip = chip_output.get("chip")
    label = GENERAL_VERDICT_LABEL.get(chip_output.get("recommendation") or "")
    if chip not in SQUAD_FIT_CHIPS or label is None:
        return None
    header = f"**{CHIP_DISPLAY[chip]} \u2014 {label}.**"
    signals = chip_output.get("signals") if isinstance(chip_output.get("signals"), dict) else {}
    teams = [
        team_names.get(t.get("team")) or t.get("team_short")
        for t in signals.get("favoured_teams") or []
        if isinstance(t, dict) and (team_names.get(t.get("team")) or t.get("team_short"))
    ]
    players = [
        p.get("web_name") for p in signals.get("favoured_players") or []
        if isinstance(p, dict) and p.get("web_name")
    ][:_HEADER_MAX_PLAYERS]
    if teams:
        header += f" Grupo favorecido: {_join_es(teams)}"
        header += f" ({', '.join(players)})." if players else "."
    return header


def compose_chip_answer(
    body: str,
    chip_output: dict[str, Any] | None,
    team_names: dict[int, str],
) -> str:
    """Header, the model's body, then the particular sentence -- in that order.

    Returns *body* unchanged when the output calls for neither part. The
    particular sentence is not appended twice if the body already has it.
    """
    if not isinstance(chip_output, dict):
        return body
    header = general_header(chip_output, team_names)
    phrase = particular_phrase(chip_output)
    if header is None and phrase is None:
        return body
    parts = [header] if header else []
    if (body or "").strip():
        parts.append(body.strip())
    if phrase and fold(phrase) not in fold(body or ""):
        parts.append(phrase[0].upper() + phrase[1:] + ".")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Grader helpers (used by scripts/grade_i108_chip_two_parts.py and its tests)
# ---------------------------------------------------------------------------

def fold(text: str) -> str:
    """Lower-case, accent-free, single-spaced, quote-free text for matching."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    stripped = re.sub("[«»\"'“”*_]", " ", stripped.lower())
    return re.sub(r"\s+", " ", stripped).strip()


def first_paragraph(text: str) -> str:
    """The opening block: up to the first blank line, else the first 300 chars.

    The STRICT definition, kept for reporting. See ``opening``.
    """
    body = (text or "").strip()
    if "\n\n" in body:
        return body.split("\n\n", 1)[0]
    return body[:300]


def opening(text: str) -> str:
    """Leading markdown heading line(s) plus the first paragraph after them.

    A heading ("## Wildcard — GW1") is a title, not the opening paragraph:
    an answer whose heading is followed by "**Jornada a medias.**" does open
    with its verdict. Found on the first measured rows of the i108 E3 gate,
    before the gate result was known; the strict ``first_paragraph`` count is
    reported alongside.
    """
    lines = (text or "").strip().splitlines()
    head: list[str] = []
    i = 0
    while i < len(lines) and (lines[i].lstrip().startswith("#") or not lines[i].strip()):
        if lines[i].strip():
            head.append(lines[i])
        i += 1
    return "\n".join(head + [first_paragraph("\n".join(lines[i:]))])
