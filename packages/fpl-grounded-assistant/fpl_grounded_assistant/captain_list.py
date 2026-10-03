"""
fpl_grounded_assistant.captain_list
=====================================
i125(a): a captain answer's top N IS the tool's top N.

Measured before this module (prod, 2026-10-02, R=5 per arm, top 3 against
the card): 2/5 with a linked team, 0/5 without. The model dropped James
Tarkowski (DEF, ranked 2nd by ``rank_captain_candidates``) on its own,
intermittently -- a defender "can't be" a captain -- so the prose
contradicted the ranking card painted right under it.

Product decision (Leo, 2026-10-02): respect the ranking, defenders included.
Same pattern as i108 E3 (``chip_two_part``): the numbered list is composed
here from the tool output and PREPENDED to the answer; the model writes only
the commentary (``captain_list_rule``) and never reorders or omits.

Which list -- the card's, by construction. ``RankingTable`` paints the ids
the tool names in ``presentation``: ``owned_top`` ("A) Candidatos de tu
plantilla") when a squad is connected, ``global_top`` otherwise. The text
lists the first N of that same id list, resolved against
``ranked_candidates``, so the prose and the card cannot disagree. No
presentation ids -> no list (no third fallback rule invented here).

N is what the user asked for ("top 3", "dame 5 opciones", "tres
candidatos"), else ``DEFAULT_TOP``, cut to the list's length.

Pure module: no imports from the live stack.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

TOOL: str = "rank_captain_candidates"

#: N when the question names no count.
DEFAULT_TOP: int = 3

_NUMBER_WORDS: dict[str, int] = {
    "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
}
_COUNT_NOUNS = r"(?:capitan(?:es)?|opciones|candidatos|nombres|jugadores|captains|options|candidates|picks)"
_TOP_RE = re.compile(r"\btop\s*-?\s*(\d{1,2}|" + "|".join(_NUMBER_WORDS) + r")\b")
_COUNT_RE = re.compile(r"\b(\d{1,2}|" + "|".join(_NUMBER_WORDS) + r")\s+(?:mejores\s+|best\s+)?" + _COUNT_NOUNS + r"\b")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def requested_top(question: str) -> int | None:
    """The count the question asks for, or ``None`` when it names none."""
    folded = _fold(question)
    match = _TOP_RE.search(folded) or _COUNT_RE.search(folded)
    if match is None:
        return None
    token = match.group(1)
    value = int(token) if token.isdigit() else _NUMBER_WORDS[token]
    return value if value >= 1 else None


def last_captain_output(trace: Any) -> dict[str, Any] | None:
    """The last ok ``rank_captain_candidates`` output in a trace, or ``None``."""
    last: dict[str, Any] | None = None
    for entry in trace or ():
        if isinstance(entry, dict) and entry.get("name") == TOOL:
            output = entry.get("output")
            if isinstance(output, dict) and output.get("status") == "ok":
                last = output
    return last


def presented_entries(output: dict[str, Any]) -> list[dict[str, Any]]:
    """The candidates the card's primary section shows, in the card's order.

    ``presentation.owned_top`` when the squad is connected, else
    ``presentation.global_top``; ids resolved against ``ranked_candidates``.
    Empty when the tool named no ids for that section.
    """
    presentation = output.get("presentation") or {}
    key = "owned_top" if output.get("squad_source") == "connected" else "global_top"
    by_id = {
        c.get("player_id"): c for c in output.get("ranked_candidates") or []
        if isinstance(c, dict) and c.get("player_id") is not None and c.get("status", "ok") == "ok"
    }
    return [by_id[i] for i in presentation.get(key) or [] if i in by_id]


def _score(value: Any) -> str:
    try:
        return f"{float(value):.1f}".replace(".", ",")
    except (TypeError, ValueError):
        return "?"


def captain_list(output: dict[str, Any] | None, question: str) -> str | None:
    """The numbered top N, or ``None`` when there is nothing to list."""
    if not isinstance(output, dict) or output.get("status") != "ok":
        return None
    entries = presented_entries(output)
    if not entries:
        return None
    n = min(requested_top(question) or DEFAULT_TOP, len(entries))
    gw = (output.get("time_context") or {}).get("evaluated_gameweek")
    gw_part = f" — GW{gw}" if gw else ""
    if output.get("squad_source") == "connected":
        title = f"**Tus mejores opciones de capitán{gw_part}** (de tu plantilla, según el ranking):"
    else:
        title = f"**Mejores opciones de capitán{gw_part}** (según el ranking):"
    lines = [title]
    for i, c in enumerate(entries[:n], 1):
        team = c.get("team_short") or ""
        pos = c.get("position") or ""
        meta = ", ".join(x for x in (team, pos) if x)
        meta_part = f" ({meta})" if meta else ""
        lines.append(f"{i}. **{c.get('web_name', '?')}**{meta_part} — {_score(c.get('captain_score'))}")
    return "\n".join(lines)


def compose_captain_answer(body: str, output: dict[str, Any] | None, question: str) -> str:
    """The deterministic list, then the model's commentary. *body* unchanged
    when there is nothing to list."""
    header = captain_list(output, question)
    if header is None:
        return body
    parts = [header]
    if (body or "").strip():
        parts.append(body.strip())
    return "\n\n".join(parts)


def captain_list_rule() -> str:
    """The CAPTAIN_LIST constraint line for the orchestrator system prompt."""
    return (
        "  - CAPTAIN_LIST: when rank_captain_candidates ran, the system itself adds, ABOVE "
        "your text, the numbered list of the top candidates (position, name, team, score) "
        "exactly as the tool ranked them -- from the user's squad (owned players) when one is "
        "connected, otherwise the global ranking. Write ONLY the commentary under it, as short "
        "prose paragraphs: why the leading options, what to weigh between them (form, fixture, "
        "minutes, set pieces), naming players by name. Do NOT write your own numbered or "
        "ranked list (no '1.', '2.', '3.' items, no per-player blocks with a score heading, no "
        "title line), do NOT reorder, skip or re-rank anyone: a defender or goalkeeper the tool "
        "ranks is a legitimate captain option, discuss them like any other. With a squad "
        "connected, the recommendation is among the listed (owned) players; a non-owned name "
        "may appear only as context, never as the pick.\n"
    )
