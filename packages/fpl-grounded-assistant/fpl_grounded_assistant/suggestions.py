"""
suggestions.py
==============
Additive, deterministic tappable-suggestion supplier (Guided Comparison flow).

When a user sends a bare ``/comparar`` (no players), the backend answers
``needs_clarification``.  This module supplies a small, deterministic list of
**tappable player-name suggestions** — sourced from the current gameweek's most
transferred-in players — so the UI can offer a two-step "chip wizard" instead of
forcing the user to type two names.

Grounding invariant (non-negotiable)
------------------------------------
Suggestions are composed **only** from already-fetched deterministic bootstrap
data (``bootstrap["elements"]``, the same ``transfers_in_event`` field read by
``find_players`` and ``get_player_snapshot``).  No value ever comes from an LLM.
Same bootstrap always yields the same ranking (ties broken by element id) — the
function is pure and never raises on malformed input.

Extensibility
-------------
``build_suggestions`` consults a small ``intent -> supplier`` map.  Only
``compare_players`` is wired today; adding a supplier for another intent is a
one-line map entry.

Schema (as implemented — the UI builds against this)
----------------------------------------------------
``Suggestion``  {label: str, send_text: str, player_id?: int, kind?: str}
    label      : short web_name, chip-friendly (e.g. "Saka")
    send_text  : text the UI sends when the chip is tapped (also web_name)
    player_id  : stable FPL element id, player-disambiguation chips only
    kind       : tap-behavior discriminator; absent for ordinary name chips,
                 "prompt_rewrite" for a complete command to send verbatim
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Suggestion contract type
# ---------------------------------------------------------------------------

#: ``Suggestion.kind`` for a chip whose ``send_text`` is a complete, ready-to-
#: send command rather than a fragment.  The UI must send it verbatim as plain
#: text and must NOT attach ``selected_player_id`` — the rewritten command
#: already names the chosen player, and the stable-id handoff would discard the
#: rest of it (harness.ask_v2 treats a structured id as authoritative and
#: ignores the question text entirely).
KIND_PROMPT_REWRITE: str = "prompt_rewrite"

#: ``Suggestion.kind`` for a HISTORICAL player chip (i60). Its ``send_text`` is
#: a complete canonical question -- "puntos de <nombre completo> (<club>) en la
#: temporada <YYYY-YYYY>" -- and it carries NO ``player_id``: the candidate's id
#: belongs to that past season's store, and the stable-id handoff resolves
#: against the CURRENT bootstrap, so sending it could pick the wrong player.
#: The UI sends ``send_text`` verbatim, exactly like ``KIND_PROMPT_REWRITE``.
KIND_HISTORICAL_PLAYER_REWRITE: str = "historical_player_rewrite"


@dataclass(frozen=True)
class Suggestion:
    """A single tappable suggestion chip.

    ``label`` is what the chip shows; ``send_text`` is what the UI sends when it
    is tapped.  For transfer-name suggestions both are the player's ``web_name``.

    ``kind`` discriminates chips that behave differently on tap.  ``None`` (the
    default) is the historical behavior — a name fragment the UI feeds into a
    wizard slot.  ``KIND_PROMPT_REWRITE`` marks a self-contained command to send
    as-is; see that constant for why the two cannot be conflated.
    """
    label: str
    send_text: str
    player_id: int | None = None
    kind: str | None = None


def _safe_int(value: Any, default: int = 0) -> int:
    """Best-effort int cast that never raises (mirrors find_players._safe_int)."""
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Best-effort float cast that never raises (selected_by_percent is a string)."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Deterministic ranker: top transferred players this gameweek
# ---------------------------------------------------------------------------

def top_transfer_names(
    bootstrap: "dict[str, Any] | None",
    *,
    limit: int = 6,
    direction: str = "in",
) -> "list[dict[str, str]]":
    """Rank players by weekly transfer volume and return chip-friendly names.

    Parameters
    ----------
    bootstrap:
        Live FPL bootstrap dict.  ``None`` / missing ``elements`` yields ``[]``.
    limit:
        Maximum number of suggestions to return (default 6).  Non-positive
        limits yield ``[]``.
    direction:
        ``"in"`` ranks by ``transfers_in_event`` (descending — most bought);
        ``"out"`` ranks by ``transfers_out_event``.  Any other value falls back
        to ``"in"``.

    Returns
    -------
    list[dict[str, str]]
        A list of ``{"label": web_name, "send_text": web_name}`` dicts,
        highest transfer volume first.  Deterministic: ties are broken by
        element id (ascending) so the output is stable for a given bootstrap.
        Never raises.

    Off-season fallback
    --------------------
    Between seasons (or between gameweeks, briefly) every element's
    ``transfers_in_event`` / ``transfers_out_event`` is genuinely ``0`` — there
    is no live gameweek to transfer within. Ranking by an all-zero field
    degenerates to the tie-break (element id), which produces an arbitrary,
    non-meaningful list (e.g. a run of backup goalkeepers). When the top
    candidate's volume is ``0``, fall back to ``selected_by_percent``
    (ownership — the same signal used by the ``@populares`` resource) so
    suggestions stay sensible year-round instead of reading as broken.
    """
    if not isinstance(bootstrap, dict) or limit <= 0:
        return []

    field_name = "transfers_out_event" if direction == "out" else "transfers_in_event"
    elements = bootstrap.get("elements") or []
    if not isinstance(elements, list):
        return []

    def _rank(field: str, is_float: bool = False) -> list[tuple[float, int, str]]:
        rows: list[tuple[float, int, str]] = []
        for el in elements:
            if not isinstance(el, dict):
                continue
            web_name = el.get("web_name")
            if not isinstance(web_name, str) or not web_name.strip():
                continue
            raw = el.get(field)
            volume = _safe_float(raw, 0.0) if is_float else float(_safe_int(raw, 0))
            el_id = _safe_int(el.get("id"), 0)
            # Sort key: volume DESC, then id ASC (negate id to keep single reverse sort).
            rows.append((volume, -el_id, web_name))
        rows.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return rows

    ranked = _rank(field_name)
    if ranked and ranked[0][0] == 0:
        # Degenerate (off-season) case — fall back to ownership.
        ranked = _rank("selected_by_percent", is_float=True)

    out: list[dict[str, str]] = []
    for _, _, web_name in ranked[:limit]:
        out.append({"label": web_name, "send_text": web_name})
    return out


# ---------------------------------------------------------------------------
# intent -> supplier map + public entrypoints
# ---------------------------------------------------------------------------

# Local copy of the constant to keep this a leaf module (no import cycle with
# dispatcher/final_response).  Must stay equal to dispatcher.INTENT_COMPARE_PLAYERS.
_INTENT_COMPARE_PLAYERS = "compare_players"

# Suppliers take the bootstrap and return a list of Suggestion. This map is
# for generic clarification turns; player ambiguity uses the candidate-aware
# helper below because its options come from a specific resolver result.
_SUGGESTION_SUPPLIERS: "dict[str, Callable[[dict[str, Any]], list[Suggestion]]]" = {
    _INTENT_COMPARE_PLAYERS: lambda bs: [
        Suggestion(label=d["label"], send_text=d["send_text"])
        for d in top_transfer_names(bs, limit=6, direction="in")
    ],
}


def build_suggestions(
    intent: "str | None",
    outcome: "str | None",
    bootstrap: "dict[str, Any] | None",
) -> "tuple[Suggestion, ...] | None":
    """Return tappable suggestions for a clarification turn, or ``None``.

    Populated only when ``outcome == "needs_clarification"`` AND ``intent`` has a
    registered supplier (today: ``compare_players``).  Returns ``None`` on OK
    outcomes, other intents, or when no suggestions can be produced.  Pure — no
    LLM, never raises.
    """
    if outcome != "needs_clarification" or intent is None:
        return None
    supplier = _SUGGESTION_SUPPLIERS.get(intent)
    if supplier is None:
        return None
    if not isinstance(bootstrap, dict):
        return None
    items = supplier(bootstrap)
    if not items:
        return None
    return tuple(items)


def player_disambiguation_suggestions(
    candidates: "list[dict[str, Any]] | tuple[dict[str, Any], ...]",
) -> "tuple[Suggestion, ...] | None":
    """Build deterministic player-pick chips from snapshot candidates."""
    items = tuple(
        Suggestion(
            label=f"{candidate.get('web_name', '')} ({candidate.get('team_short', '')})",
            send_text=f"{candidate.get('web_name', '')} {candidate.get('team_short', '')}".strip(),
            player_id=_safe_int(candidate.get("id"), 0) or None,
        )
        for candidate in candidates
        if candidate.get("web_name") and _safe_int(candidate.get("id"), 0) > 0
    )
    return items or None


def _fold_with_offsets(text: str) -> "tuple[str, list[int]]":
    """Accent- and case-folded ``text`` plus, per folded char, its index in ``text``."""
    import unicodedata  # noqa: PLC0415

    folded: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(text):
        for piece in unicodedata.normalize("NFKD", char):
            if unicodedata.combining(piece):
                continue
            folded.append(piece.lower())
            origin.append(index)
    return "".join(folded), origin


def replace_mention(question: str, mention: str, replacement: str) -> "str | None":
    """``question`` with the first whole-word ``mention`` swapped for ``replacement``.

    Accent- and case-insensitive ("Joao Pedro" finds "João Pedro"); ``None`` when the
    mention is not in the question, so the caller can decline to build a chip.
    """
    needle, _ = _fold_with_offsets(mention.strip())
    haystack, origin = _fold_with_offsets(question)
    if not needle:
        return None
    start = haystack.find(needle)
    while start >= 0:
        end = start + len(needle)
        before_ok = start == 0 or not haystack[start - 1].isalnum()
        after_ok = end == len(haystack) or not haystack[end].isalnum()
        if before_ok and after_ok:
            first, last = origin[start], origin[end - 1] + 1
            return question[:first] + replacement + question[last:]
        start = haystack.find(needle, start + 1)
    return None


def question_is_only_the_name(question: str, mention: str) -> bool:
    """True when nothing but the player's name (and punctuation) is left of ``question``."""
    rest = replace_mention(question, mention, "") if mention.strip() else None
    if rest is None:
        return False
    return not any(char.isalnum() for char in rest)


def question_resume_suggestions(
    candidates: "list[dict[str, Any]] | tuple[dict[str, Any], ...]",
    mention: str,
    question: str,
    bootstrap: "dict[str, Any] | None" = None,
) -> "tuple[Suggestion, ...] | None":
    """Pick-one chips that re-ask the user's OWN question with the player named in full.

    For tools whose answer is not the player card (position changes, involvement):
    the stable-id handoff would answer with the generic snapshot and drop the question.
    Each chip's ``send_text`` is the original question with ``mention`` replaced by the
    candidate's full name (which the resolver matches whole), sent verbatim with no id.
    ``None`` when the mention cannot be found in the question or no candidate has a name,
    and (loop guard) when two chips would send the same text or, given ``bootstrap``, a
    full name does not resolve back to its own candidate: the caller then keeps today's chips.
    """
    items = []
    for candidate in candidates:
        full_name = str(candidate.get("name") or "").strip()
        if not full_name and bootstrap is not None:
            # get_player_snapshot / get_player_form candidates carry no first/second name.
            element = next(
                (e for e in bootstrap.get("elements", []) or [] if e.get("id") == candidate.get("id")), {}
            )
            full_name = f"{element.get('first_name', '')} {element.get('second_name', '')}".strip()
        label = f"{candidate.get('web_name', '')} ({candidate.get('team_short', '')})"
        rewritten = replace_mention(question, mention, full_name) if full_name else None
        if rewritten is None or not candidate.get("web_name"):
            return None
        if bootstrap is not None:
            from fpl_tool_contract import tool_resolve_player  # noqa: PLC0415

            resolved = tool_resolve_player(full_name, bootstrap)
            if resolved.get("status") != "ok" or resolved.get("player_id") != candidate.get("id"):
                return None
        items.append(Suggestion(label=label, send_text=rewritten, player_id=None, kind=KIND_PROMPT_REWRITE))
    if len({item.send_text for item in items}) != len(items):
        return None
    return tuple(items) or None


def historical_player_suggestions(
    candidates: "list[dict[str, Any]] | tuple[dict[str, Any], ...]",
    season: str,
) -> "tuple[Suggestion, ...] | None":
    """Chips for an ambiguous PAST-season player (get_player_season_points).

    Sibling of ``player_disambiguation_suggestions``, deliberately separate:
    that builder drops ``id <= 0`` on purpose and hands the id to the UI as
    authoritative -- neither is right for ids from another season's store.
    Here the chip carries the full canonical question instead, built from
    the ``name`` (first + second) and ``team_short`` the candidate already
    exposes, so the resolver can break the tie by club on the way back.
    """
    items = tuple(
        Suggestion(
            label=f"{c.get('web_name', '')} ({c.get('team_short', '')})",
            send_text=(
                f"puntos de {c.get('name') or c.get('web_name', '')} "
                f"({c.get('team_short', '')}) en la temporada {season}"
            ),
            player_id=None,
            kind=KIND_HISTORICAL_PLAYER_REWRITE,
        )
        for c in candidates
        if c.get("web_name") and c.get("team_short")
    )
    return items or None


def suggestions_to_list(
    suggestions: "tuple[Suggestion, ...] | None",
) -> "list[dict[str, Any]] | None":
    """Serialise a tuple of ``Suggestion`` to a JSON-safe list of dicts (or ``None``).

    Single-source serializer so the wire shape is identical across the /ask
    (adapter) and /session/{id}/ask paths.
    """
    if not suggestions:
        return None
    return [
        {
            "label": s.label,
            "send_text": s.send_text,
            **({"player_id": s.player_id} if s.player_id is not None else {}),
            **({"kind": s.kind} if s.kind is not None else {}),
        }
        for s in suggestions
    ]


def build_suggestion_dicts(
    intent: "str | None",
    outcome: "str | None",
    bootstrap: "dict[str, Any] | None",
) -> "list[dict[str, Any]] | None":
    """Convenience: ``build_suggestions`` followed by ``suggestions_to_list``.

    Used by the /ask path (``ask_v2``), whose result dict carries JSON-safe
    primitives rather than dataclass instances.
    """
    return suggestions_to_list(build_suggestions(intent, outcome, bootstrap))
