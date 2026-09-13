"""
fpl_grounded_assistant.atomic_tool_cards
========================================
Structured cards for open-ended (orchestrator-answered) questions.

The LLM orchestrator answers open-ended questions ("jugadores con más puntos",
"mejores por xGI") by calling an *atomic* tool and returning its output as an
ASCII-art text table. This module composes a real ``GenericCardMeta`` from that
same deterministic tool output so the UI renders a styled card instead of the
monospace table — reusing the existing ``generic_card`` renderer with no schema
change.

Grounding invariant (non-negotiable)
------------------------------------
Every cell is composed only from the deterministic tool output (itself sourced
from the FPL bootstrap), pre-formatted to a string. No value ever comes from
LLM text. ``llm_review`` is not involved. This mirrors ``generic_card.py``'s own
invariant — the difference is only the *input*: raw tool output here vs. the
frozen ``*Meta`` dataclasses there.

Scope (Phase 1)
---------------
``rank_players_by_metric`` only — the dominant "top / rank / best / most X"
query class, whose 5-column ASCII table maps to a card with zero information
loss. Other atomic tools are deferred (they show strictly more than a naive
card would; carding them lossily would *drop* information the UI suppresses the
prose to make room for). The overlay is applied by the harness for turns that
ran a **single distinct tool** (see ``is_single_distinct_tool_turn``) -- a
turn that called the same tool twice still cards; a turn that ran two
different tools does not.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

from .formatting import format_metric_value
from .generic_card import Column, GenericCardMeta, HeroStat
from .rank_players_by_metric import natural_order

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Metric canonical-name -> Spanish column header.
# Keyed on the CANONICAL field names (rank_players_by_metric resolves aliases
# to these before returning them in output["metric"]). Covers every value in
# rank_players_by_metric._METRIC_ALIASES; unmapped names fall back to a
# title-cased form so a newly-added metric still renders sensibly.
# ---------------------------------------------------------------------------
_METRIC_HEADER_ES: dict[str, str] = {
    "form":                        "Forma",
    "total_points":                "Puntos",
    "points_per_game":             "Pts/Partido",
    "expected_goals":              "xG",
    "expected_assists":            "xA",
    "expected_goal_involvements":  "xGI",
    "ict_index":                   "ICT",
    "selected_by_percent":         "Propiedad %",
    "minutes":                     "Minutos",
    "goals_scored":                "Goles",
    "assists":                     "Asist.",
    "clean_sheets":                "Porterías 0",
    "bonus":                       "Bonus",
    "bps":                         "BPS",
    # Per-90 rate stats
    "expected_goals_per_90":              "xG/90",
    "expected_assists_per_90":            "xA/90",
    "expected_goal_involvements_per_90":  "xGI/90",
    "saves_per_90":                       "Paradas/90",
    "clean_sheets_per_90":                "Porterías 0/90",
    "defensive_contribution_per_90":      "DC/90",
    # Price, momentum, set pieces, discipline, and detailed performance
    "now_cost":                           "Precio (£m)",
    "transfers_in_event":                 "Fichajes GW",
    "transfers_out_event":                "Ventas GW",
    "penalties_order":                    "Orden penales",
    "direct_freekicks_order":             "Orden tiros libres",
    "corners_and_indirect_freekicks_order": "Orden córners/TLI",
    "yellow_cards":                       "Amarillas",
    "red_cards":                          "Rojas",
    "expected_goals_conceded":            "xGC",
    "goals_conceded":                     "Goles en contra",
    "influence":                          "Influencia",
    "creativity":                         "Creatividad",
    "threat":                             "Amenaza",
    "saves":                              "Paradas",
}


def _metric_header(metric: str) -> str:
    """Spanish header for a canonical metric name, with a safe fallback."""
    return _METRIC_HEADER_ES.get(metric, metric.replace("_", " ").title())


def _card_title(metric: str, order: "str | None", count: int, header_es: str) -> str:
    """Title matching the ranking's real direction.

    A caller-inverted ranking (``order="asc"`` on price, say) is the cheapest
    players, not the top ones — titling it "TOP" is how that list got read back
    as the most expensive. ``order`` is absent on pre-``order`` payloads and
    equals the natural direction for an ordinary ranking; both stay "TOP".
    """
    if order is not None and order != natural_order(metric):
        extreme = "MENOR" if order == "asc" else "MAYOR"
        return f"{count} CON {extreme} · {header_es}"
    return f"TOP {count} · {header_es}"


def _rank_subtitle(raw_output: dict[str, Any]) -> "str | None":
    """Build the filter subtitle, mirroring renderer._render_rank_players_by_metric."""
    parts: list[str] = []
    pos_flt = raw_output.get("position_filter")
    if pos_flt:
        parts.append(f"posición: {pos_flt}")
    min_mins = raw_output.get("min_minutes_filter", 0) or 0
    if min_mins > 0:
        parts.append(f"min. minutos: {min_mins}")
    return ", ".join(parts) if parts else None


def compose_rank_players_card(raw_output: dict[str, Any]) -> "GenericCardMeta | None":
    """Compose a ranked-players card from ``rank_players_by_metric`` output.

    Columns mirror the text renderer exactly (``# | Jugador | Equipo | Pos |
    <metric>``) so card and prose can never diverge. Returns ``None`` on a
    non-ok status, an empty ranking, or malformed input (never raises) — the
    caller then keeps the plain-text fallback.
    """
    if raw_output.get("status") != "ok":
        return None
    ranked = raw_output.get("ranked") or []
    if not ranked:
        return None

    try:
        metric = str(raw_output.get("metric", ""))
        header_es = _metric_header(metric)

        columns = (
            Column(header="#", align="right", kind="mono"),
            Column(header="Jugador", align="left", kind="text"),
            Column(header="Equipo", align="left", kind="text"),
            Column(header="Pos", align="left", kind="text"),
            Column(header=header_es, align="right", kind="mono"),
        )
        rows: list[tuple[str, ...]] = []
        for entry in ranked:
            rows.append((
                str(entry.get("rank", "?")),
                str(entry.get("web_name", "?")),
                str(entry.get("team_short", "?")),
                str(entry.get("position", "?")),
                format_metric_value(entry.get("metric_value", 0.0)),
            ))

        hero = HeroStat(
            value=format_metric_value(ranked[0].get("metric_value", 0.0)),
            label=header_es,
            tone=None,
        )

        return GenericCardMeta(
            accent="turquoise",
            title=_card_title(
                metric, raw_output.get("order"), len(ranked), header_es,
            ),
            subtitle=_rank_subtitle(raw_output),
            hero=hero,
            pills=(),
            columns=columns,
            rows=tuple(rows),
            footer=None,
        )
    except Exception as exc:  # noqa: BLE001
        # Observable, not silent: a composition failure would otherwise
        # regress this turn back to the ASCII table with no signal.
        _LOG.warning(
            "atomic_tool_cards: failed to compose rank_players_by_metric card "
            "(%s); falling back to prose",
            type(exc).__name__,
        )
        return None


# ---------------------------------------------------------------------------
# Dispatch — tool name -> composer. Phase 2 tools are one-line additions.
# ---------------------------------------------------------------------------
_ATOMIC_TOOL_COMPOSERS: dict[str, Any] = {
    "rank_players_by_metric": compose_rank_players_card,
}


def is_single_distinct_tool_turn(
    tool_chosen: "str | None",
    tool_call_count: int,
    tool_sequence: Iterable["str | None"],
) -> bool:
    """i58: did this orchestrator turn run exactly ONE distinct tool?

    This is the count half of the harness card gate. The other half is
    ``maybe_atomic_tool_card`` (is the retained output cardable?). The gate
    used to ask ``tool_call_count == 1`` -- "one call" -- which stopped carding
    the turns the i46 extra round rescues: the model calls the same cardable
    tool again with different arguments, ``tool_call_count`` reads 2, and the
    turn that ended in *good prose over cardable data* lost its card (see
    field-notes/2026-08-31-i46-extra-round-fix.md, "Knock-on worth knowing").

    Inputs are primitives so the same predicate runs in the harness, in the
    measurement script and in the tests without any of them re-deriving it:

    ``tool_chosen``
        The tool whose output was retained on the result (``None`` -> False).
    ``tool_call_count``
        Executed calls underlying the RETAINED payload (``OrchestratorResult``
        semantics). ``1`` is sufficient on its own: exactly one executed call
        produced the payload, so there is exactly one distinct tool behind it.
        This keeps every previously-carded turn carded, including an
        evaluator-retry delivery, whose calls ``tool_calls_trace`` does not
        carry (``_attaches_tool_calls_trace``: the trace describes the PRIMARY
        calls, the retry's count describes the retry's).
    ``tool_sequence``
        The executed tool names in order -- ``[e["name"] for e in
        OrchestratorResult.tool_calls_trace]``, the same field the routing
        JSONL projects as ``tool_sequence``. For a multi-call turn it decides:
        every name equal to ``tool_chosen`` -> one distinct tool -> True;
        any other name -> a genuine multi-tool turn -> False. An EMPTY sequence
        on a multi-call turn cannot prove a single tool, so it is False
        (conservative: never card what cannot be shown to be single-tool).
    """
    if not tool_chosen:
        return False
    if tool_call_count == 1:
        return True
    names = [n for n in tool_sequence if n]
    return bool(names) and set(names) == {tool_chosen}


def maybe_atomic_tool_card(
    tool_name: "str | None",
    raw_output: dict[str, Any],
    existing_generic_card: "GenericCardMeta | None",
) -> "GenericCardMeta | None":
    """Return a card to overlay for an atomic tool, or ``None``.

    Pure and count-agnostic (the single-distinct-tool guard is
    ``is_single_distinct_tool_turn``, applied at the harness call site). Never
    overrides an already-composed card, and only builds for a tool that has a
    registered composer.
    """
    if existing_generic_card is not None:
        return None
    composer = _ATOMIC_TOOL_COMPOSERS.get(tool_name or "")
    if composer is None:
        return None
    return composer(raw_output)
