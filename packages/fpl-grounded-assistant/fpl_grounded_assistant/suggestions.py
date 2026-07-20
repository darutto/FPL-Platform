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
``Suggestion``  {label: str, send_text: str}
    label      : short web_name, chip-friendly (e.g. "Saka")
    send_text  : text the UI sends when the chip is tapped (also web_name)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Suggestion contract type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Suggestion:
    """A single tappable suggestion chip.

    ``label`` is what the chip shows; ``send_text`` is what the UI sends when it
    is tapped.  For transfer-name suggestions both are the player's ``web_name``.
    """
    label: str
    send_text: str


def _safe_int(value: Any, default: int = 0) -> int:
    """Best-effort int cast that never raises (mirrors find_players._safe_int)."""
    try:
        if value is None:
            return default
        return int(value)
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
    """
    if not isinstance(bootstrap, dict) or limit <= 0:
        return []

    field_name = "transfers_out_event" if direction == "out" else "transfers_in_event"
    elements = bootstrap.get("elements") or []
    if not isinstance(elements, list):
        return []

    ranked: list[tuple[int, int, str]] = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        web_name = el.get("web_name")
        if not isinstance(web_name, str) or not web_name.strip():
            continue
        volume = _safe_int(el.get(field_name), 0)
        el_id = _safe_int(el.get("id"), 0)
        # Sort key: volume DESC, then id ASC (negate id to keep single reverse sort).
        ranked.append((volume, -el_id, web_name))

    ranked.sort(key=lambda t: (t[0], t[1]), reverse=True)

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

# Suppliers take the bootstrap and return a list of Suggestion.  Extend by
# adding a new intent key here; only compare is wired today.
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


def suggestions_to_list(
    suggestions: "tuple[Suggestion, ...] | None",
) -> "list[dict[str, str]] | None":
    """Serialise a tuple of ``Suggestion`` to a JSON-safe list of dicts (or ``None``).

    Single-source serializer so the wire shape is identical across the /ask
    (adapter) and /session/{id}/ask paths.
    """
    if not suggestions:
        return None
    return [{"label": s.label, "send_text": s.send_text} for s in suggestions]


def build_suggestion_dicts(
    intent: "str | None",
    outcome: "str | None",
    bootstrap: "dict[str, Any] | None",
) -> "list[dict[str, str]] | None":
    """Convenience: ``build_suggestions`` followed by ``suggestions_to_list``.

    Used by the /ask path (``ask_v2``), whose result dict carries JSON-safe
    primitives rather than dataclass instances.
    """
    return suggestions_to_list(build_suggestions(intent, outcome, bootstrap))
