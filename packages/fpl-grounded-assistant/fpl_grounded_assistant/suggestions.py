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
