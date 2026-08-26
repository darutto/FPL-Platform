"""
prompt_disambiguation.py
========================
Turn an ambiguous player name inside a slash-prompt into tappable pick-one chips.

Why this exists
---------------
``/comparar Palmer vs Saka`` resolves two players.  When one side is ambiguous
the comparison cannot run, and the turn used to dead-end on an English sentence
("Multiple players share the name 'Palmer'…") with nothing to tap — the user had
to retype the whole command with a fuller name.  The player-*snapshot* path has
offered a pick-one wizard for this since the disambiguation chips landed; this
module extends the same affordance to prompt turns.

Approach: rewrite, don't hand off
---------------------------------
A snapshot chip sends a stable ``player_id`` and lets ``harness.ask_v2`` treat it
as authoritative.  That is exactly wrong here: the id identifies one player, but
the turn is a *comparison* — dropping to a single-player lookup would silently
discard the other side.  So instead each chip carries a rewritten copy of the
user's own command with only the ambiguous slot replaced::

    /comparar Palmer vs Saka   +   "Cole Palmer"   ->   /comparar Cole Palmer vs Saka

Tapping one re-enters the ordinary prompt path with an unambiguous argument.
Nothing about the routing, the intent, or the other argument changes, and the
rewritten text is what the user sees in their own chat bubble — readable, and
re-editable if they want to tweak it.

The user's own connector and phrasing are preserved (``vs`` stays ``vs``, ``por``
stays ``por``) by splitting on the connector and rebuilding around it, rather
than re-rendering from parsed arguments.

Scope
-----
Positional argument forms only.  The named-flag form (``/comparar a=Palmer
b=Saka``) returns ``None`` — no chips — rather than risking a malformed rewrite;
the turn then behaves exactly as it did before this module existed.

Pure: no LLM, no network, no bootstrap access.  Every value comes from the
resolver's own candidate list.  Never raises.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from .suggestions import KIND_PROMPT_REWRITE, Suggestion

#: Connector split, mirroring ``prompt_registry._CONNECTOR_RE`` but *capturing*
#: the separator so a rewrite can put back exactly what the user typed.  Must
#: stay in sync with that pattern: a connector this misses is one the rewrite
#: would mangle.
_CONNECTOR_CAPTURE_RE = re.compile(
    r"(\s+(?:por|for|vs\.?|versus|y|and)\s+|\s*,\s*)",
    flags=re.IGNORECASE,
)

#: A ``key=value`` token anywhere in the argument text means the named-flag form
#: is in play and positional rewriting is unsafe.
_FLAG_RE = re.compile(r"\S+\s*=")

#: Cap on chips offered, matching the resolver's own candidate cap.
_MAX_CHIPS: int = 5


def _fold(value: Any) -> str:
    """Case/accent-insensitive comparison key.  Never raises."""
    text = unicodedata.normalize("NFD", str(value or ""))
    stripped = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(stripped.casefold().split())


def _strip_command(question: str, prompt_name: str) -> str | None:
    """Return the argument text following ``/{prompt_name}``, or ``None``.

    ``None`` means the question is not the slash form this prompt was reached
    by (e.g. it arrived as an alias, or through a path that rewrote it), so
    there is no original text to rewrite faithfully.
    """
    text = (question or "").strip()
    if not text.startswith("/"):
        return None
    head, _, rest = text.partition(" ")
    if _fold(head.lstrip("/")) != _fold(prompt_name):
        return None
    return rest.strip()


def rebuild_with_choice(
    question: str,
    prompt_name: str,
    ambiguous_query: str,
    chosen_name: str,
) -> str | None:
    """Rewrite *question*, replacing the ``ambiguous_query`` slot with *chosen_name*.

    Returns the full rewritten command (e.g. ``"/comparar Cole Palmer vs Saka"``)
    or ``None`` when the rewrite cannot be done safely — a named-flag form, a
    question that is not this prompt's slash form, or an ambiguous query that
    does not match any argument slot.  Callers must treat ``None`` as "offer no
    chips": a wrong rewrite would silently run a different comparison than the
    user asked for.
    """
    args_text = _strip_command(question, prompt_name)
    if not args_text or not str(ambiguous_query).strip() or not str(chosen_name).strip():
        return None
    if _FLAG_RE.search(args_text):
        return None

    target = _fold(ambiguous_query)
    replacement = str(chosen_name).strip()

    # Single-argument prompts (/capitan, /calendarios): the whole payload is
    # the slot, so it is replaced outright.
    parts = _CONNECTOR_CAPTURE_RE.split(args_text, maxsplit=1)
    if len(parts) == 1:
        return f"/{prompt_name} {replacement}" if _fold(args_text) == target else None

    left, separator, right = parts[0], parts[1], parts[2]
    if _fold(left) == target:
        return f"/{prompt_name} {replacement}{separator}{right}"
    if _fold(right) == target:
        return f"/{prompt_name} {left}{separator}{replacement}"
    return None


def _chip_label(candidate: dict[str, Any]) -> str:
    """Human-readable chip face: full name plus team code when both are known.

    Falls back to ``web_name`` because the full name is what disambiguates but
    the team code is what the user recognises — showing "Cole Palmer (CHE)"
    answers "which Palmer?" without them having to think about it.
    """
    name = str(candidate.get("name") or candidate.get("web_name") or "").strip()
    team = str(candidate.get("team_short") or "").strip()
    return f"{name} ({team})" if name and team else name


def _full_name(candidate: dict[str, Any]) -> str:
    """The name a rewrite substitutes in.  Empty string when unknown."""
    return str(candidate.get("name") or candidate.get("web_name") or "").strip()


def _counts(values: "list[str]") -> dict[str, int]:
    """Occurrence count per folded value, for collision detection."""
    counts: dict[str, int] = {}
    for value in values:
        key = _fold(value)
        counts[key] = counts.get(key, 0) + 1
    return counts


def prompt_disambiguation_suggestions(
    question: str,
    prompt_name: str | None,
    raw_output: dict[str, Any] | None,
) -> tuple[Suggestion, ...] | None:
    """Build pick-one chips for an ambiguous player inside a prompt turn.

    Reads the ambiguous query from the tool's own output — ``error_player`` for
    two-sided tools like ``compare_players``, ``query`` for single-player ones —
    so the chips always rewrite the slot that actually failed, not a guess.

    Returns ``None`` (no chips, message-only turn as before) when the status is
    not ambiguous, when the resolver produced no candidates, or when no
    candidate yields a safe rewrite.  Never raises.
    """
    if not prompt_name or not isinstance(raw_output, dict):
        return None
    if raw_output.get("status") != "ambiguous":
        return None

    candidates = raw_output.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None

    ambiguous_query = raw_output.get("error_player") or raw_output.get("query")
    if not ambiguous_query:
        return None

    usable = [c for c in candidates[:_MAX_CHIPS] if isinstance(c, dict) and _full_name(c)]
    if not usable:
        return None

    # Two players can share a full name (and even a team). Substituting a name
    # that still matches both would re-ambiguate on the re-send — the chip would
    # loop the user straight back to this same message. Detect those collisions
    # up front and substitute the numeric id instead, which the resolver always
    # takes as a unique key. Labels get the same treatment so two chips are
    # never visually identical.
    name_counts  = _counts([_full_name(c) for c in usable])
    label_counts = _counts([_chip_label(c) for c in usable])

    chips: list[Suggestion] = []
    for candidate in usable:
        raw_id = candidate.get("id")
        player_id = int(raw_id) if isinstance(raw_id, int) and raw_id > 0 else None

        name = _full_name(candidate)
        # Unique name -> substitute it (readable). Otherwise fall back to the id,
        # and drop the chip entirely if there is no id to fall back to.
        if name_counts.get(_fold(name), 0) > 1:
            if player_id is None:
                continue
            chosen = str(player_id)
        else:
            chosen = name

        label = _chip_label(candidate)
        if label_counts.get(_fold(label), 0) > 1 and player_id is not None:
            label = f"{label} #{player_id}"

        send_text = rebuild_with_choice(question, prompt_name, ambiguous_query, chosen)
        if send_text is None:
            continue
        chips.append(
            Suggestion(
                label=label,
                send_text=send_text,
                # Carried for telemetry/debugging and so a future surface can
                # identify the player without re-parsing send_text.  The UI must
                # NOT send it as selected_player_id — see KIND_PROMPT_REWRITE.
                player_id=player_id,
                kind=KIND_PROMPT_REWRITE,
            )
        )
    return tuple(chips) or None
