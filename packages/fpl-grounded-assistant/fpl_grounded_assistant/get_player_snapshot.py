"""
fpl_grounded_assistant.get_player_snapshot
===========================================
P2.2: Atomic get_player_snapshot tool — single-player full grounding payload.

Where ``find_players`` returns a candidate LIST, ``get_player_snapshot``
returns ONE player's full grounding payload, OR an ``ambiguous`` status with
up to 5 candidates when the name resolves to more than one player.

This is the MPC_learning pattern: ambiguity is a first-class status, not
silently resolved.

Resolution algorithm
--------------------
1. Normalize the query (NFKD + lowercase + accent strip) — same helper as
   ``find_players``.
2. Rank 0 — exact match (query == web_name, first_name, OR second_name):
   - Exactly 1 → status="ok" with single player.
   - More than 1 → status="ambiguous" with all exact matches (e.g. two
     "Diallo" players in the squad).
3. Rank 1 — prefix match (any name field starts with the query):
   - Exactly 1 → status="ok" (auto-resolve single prefix).
   - More than 1 → status="ambiguous" with up to 5 prefix matches.
4. Rank 2 — substring match (query anywhere in composite name):
   - Any matches → status="ambiguous" (too loose to auto-resolve).
5. No matches at any rank → status="not_found".

Grounding payload
-----------------
Single-answer ("ok") response omits ``match_rank`` (it is meaningless for a
single result).  Ambiguous candidates INCLUDE ``match_rank`` so the LLM can
tiebreak or explain the options to the user.

Reuse
-----
Matching uses the canonical ``fpl_player_registry`` resolver. The grounding
payload builder remains shared with ``find_players``:
    _normalize          — compatibility wrapper around canonical normalization
    _build_match_dict   — 31-field grounding payload builder

Registration
------------
This module registers ``get_player_snapshot`` in ``TOOL_REGISTRY`` as a
side-effect of import.  The package's ``__init__.py`` imports this module so
``run_tool("get_player_snapshot", ...)`` works automatically after any
full-package import.
"""
from __future__ import annotations

from typing import Any

from fpl_player_registry import RANK_AUTO_RESOLVE_MAX, resolve_player_candidates
from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

# Reuse the fixture-run tool so the snapshot card can show an upcoming
# schedule strip without duplicating fixture-lookup logic.
from fpl_grounded_assistant.player_fixture_run import get_player_fixture_run

# Re-use helpers from find_players — single source of truth.
from fpl_grounded_assistant.find_players import (
    _normalize,
    _build_match_dict,
    _team_short,
)

_MAX_AMBIGUOUS_CANDIDATES: int = 5

#: Fixtures shown on the snapshot card — matches get_player_fixture_run's
#: own DEFAULT_HORIZON, kept explicit here so a change to that default
#: doesn't silently change what this card shows.
_SNAPSHOT_FIXTURE_HORIZON: int = 5


def _attach_fixture_run(player_dict: dict[str, Any], bootstrap: dict[str, Any]) -> None:
    """Mutate *player_dict* in place, adding "fixtures"/"team_fdr_context".

    Resolves by the player's own numeric id (not by re-running name
    matching) so this can never disagree with the player already resolved
    above -- get_player_fixture_run's query resolver accepts a numeric FPL
    element id directly. Degrades to an empty list / None on any
    non-"ok" outcome (e.g. missing_context) rather than raising or
    propagating an error status onto an otherwise-successful snapshot.
    """
    fx = get_player_fixture_run(
        str(player_dict["id"]), bootstrap, horizon=_SNAPSHOT_FIXTURE_HORIZON
    )
    if fx.get("status") == "ok":
        player_dict["fixtures"] = fx.get("fixtures", [])
        player_dict["team_fdr_context"] = fx.get("team_fdr_context")
    else:
        player_dict["fixtures"] = []
        player_dict["team_fdr_context"] = None


def _split_team_hint(
    normalized_query: str, bootstrap: dict[str, Any]
) -> tuple[str, str | None]:
    """Detect a trailing team short_name token on *normalized_query*.

    Lets a disambiguation chip send natural text like "Joao Pedro CHE" that
    the LLM already reliably routes to this tool, and have the team
    qualifier resolved *here* rather than requiring a new deterministic
    route or asking the LLM to interpret a bare id (get_player_snapshot is
    orchestrator-only -- there is no deterministic path for it, unlike
    /comparar's MODE_DISPATCH prompt).

    Matches on team short_name ONLY (3-letter codes like "CHE") -- not full
    team names, which carry real collision risk with player surnames. Short
    codes are also exactly what the disambiguation chips below send, so
    nothing else needs to be supported.

    Returns ``(name_only_query, team_hint)``. ``team_hint`` is ``None`` (and
    *normalized_query* returned unchanged) when the last token isn't a
    known team code, or when stripping it would leave nothing to match on --
    a query that just happens to end in a real team code but describes no
    real name should fall through to ordinary matching, not silently lose
    its last word.
    """
    tokens = normalized_query.split()
    if len(tokens) < 2:
        return normalized_query, None

    team_shorts = {
        _normalize(str(t.get("short_name", ""))): str(t.get("short_name", ""))
        for t in bootstrap.get("teams", [])
    }
    last = tokens[-1]
    if last not in team_shorts:
        return normalized_query, None

    name_only = " ".join(tokens[:-1]).strip()
    if not name_only:
        return normalized_query, None

    return name_only, last


# ---------------------------------------------------------------------------
# Core public function
# ---------------------------------------------------------------------------

def get_player_snapshot(
    player_name: str | int,
    bootstrap: "dict[str, Any] | None" = None,
) -> dict[str, Any]:
    """Single player full grounding payload by name or FPL element id.

    Resolution: exact match (case + accent insensitive) wins immediately.
    If multiple exact matches OR multiple prefix matches without a tiebreaker,
    return status='ambiguous' with up to 5 candidates (LLM decides what to do).

    Args:
        player_name: player name (case-insensitive, unicode-normalized) or
            numeric FPL element id.
        bootstrap: live FPL bootstrap; if None, returns not_found.

    Returns one of:
        # Single unambiguous match:
        {
            "status": "ok",
            "player": {
                # Full grounding payload (match_rank omitted)
                # id, web_name, team_short, position, minutes_played_season,
                # status, news, news_added, chance_of_playing_this_round,
                # form, total_points, points_per_game, expected_goals,
                # expected_assists, expected_goal_involvements, ict_index,
                # their per-90 rates, defensive_contribution and DC/90,
                # now_cost, selected_by_percent, transfers_in_event,
                # transfers_out_event
                # plus: fixtures (next 5, via get_player_fixture_run),
                # team_fdr_context (None if fixtures is empty)
            }
        }
        # OR ambiguous resolution:
        {
            "status": "ambiguous",
            "query": <normalized name>,
            "candidates": [<up to 5 grounding-payload dicts with match_rank>],
            "message": "Multiple players match '<query>'. Please specify."
        }
        # OR not found:
        {
            "status": "not_found",
            "query": <normalized name>,
            "message": "No player matching '<query>'."
        }
    """
    # ------------------------------------------------------------------
    # 0. Validate and normalize inputs
    # ------------------------------------------------------------------
    if isinstance(player_name, bool) or not isinstance(player_name, (str, int)):
        return {
            "status":  "error",
            "code":    "invalid_argument",
            "message": "player_name must be a non-empty string or integer element id.",
        }
    if isinstance(player_name, str) and not player_name.strip():
        return {
            "status":  "error",
            "code":    "invalid_argument",
            "message": "player_name must be a non-empty string or integer element id.",
        }

    normalized_query = _normalize(str(player_name).strip())

    # ------------------------------------------------------------------
    # 1. Guard: bootstrap required
    # ------------------------------------------------------------------
    if bootstrap is None:
        return {
            "status":  "not_found",
            "query":   normalized_query,
            "message": f"No player matching '{normalized_query}'.",
        }

    elements: list[dict[str, Any]] = bootstrap.get("elements", []) or []
    teams: list[dict[str, Any]] = bootstrap.get("teams", []) or []
    element_types: list[dict[str, Any]] = bootstrap.get("element_types", []) or []

    # A trailing team-code token (e.g. "joao pedro che") can never match any
    # player's name text, so it must be stripped BEFORE matching -- left in,
    # the whole query fails every rank and falls straight to not_found
    # (this was the actual bug: appending "Chelsea" made the search worse,
    # not better). team_hint is used below to disambiguate a multi-match.
    match_query, team_hint = _split_team_hint(normalized_query, bootstrap)
    resolution = resolve_player_candidates(
        match_query,
        elements,
        teams,
        allow_prefix=True,
        allow_substring=True,
    )
    best_matches = list(resolution.best_matches)
    elements_by_id = {el.get("id"): el for el in elements}

    def _ok(match: Any) -> dict[str, Any]:
        player_dict = _build_match_dict(
            elements_by_id[match.record.id], teams, element_types, match.rank
        )
        player_dict.pop("match_rank", None)
        _attach_fixture_run(player_dict, bootstrap)
        return {"status": "ok", "player": player_dict}

    # Preserve the snapshot's existing conservative rule: a substring match
    # remains a wizard candidate even when only one player happens to match.
    if len(best_matches) == 1 and best_matches[0].rank <= RANK_AUTO_RESOLVE_MAX:
        return _ok(best_matches[0])

    if best_matches:
        if team_hint is not None and best_matches[0].rank <= RANK_AUTO_RESOLVE_MAX:
            narrowed = [
                match
                for match in best_matches
                if _normalize(_team_short(elements_by_id[match.record.id], teams))
                == team_hint
            ]
            if len(narrowed) == 1:
                return _ok(narrowed[0])
        candidates = [
            _build_match_dict(
                elements_by_id[match.record.id], teams, element_types, match.rank
            )
            for match in best_matches[:_MAX_AMBIGUOUS_CANDIDATES]
        ]
        return {
            "status":     "ambiguous",
            "query":      normalized_query,
            "candidates": candidates,
            "message":    f"Multiple players match '{normalized_query}'. Please specify.",
        }

    # Rule 5: nothing found
    return {
        "status":  "not_found",
        "query":   normalized_query,
        "message": f"No player matching '{normalized_query}'.",
    }


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

GET_PLAYER_SNAPSHOT_SPEC = ToolSpec(
    name="get_player_snapshot",
    description=(
        "Single player full grounding payload by name or numeric FPL element id. Returns status=ok+player "
        "(1 match), ambiguous+candidates (multi-match), or not_found. "
        "For candidate lists use find_players instead."
    ),
    parameters={
        "type": "object",
        "properties": {
            "player_name": {
                "type":        ["string", "integer"],
                "description": "Player name (case/accent-insensitive) or numeric FPL element id",
            },
        },
        "required":             ["player_name"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["ok", "ambiguous", "not_found", "error"],
            },
            "player": {
                "type":        "object",
                "description": "Full 30-field grounding payload plus fixtures/team_fdr_context (only when status=ok)",
            },
            "query": {
                "type":        "string",
                "description": "Normalized query (present on ambiguous/not_found)",
            },
            "candidates": {
                "type":        "array",
                "description": "Up to 5 candidate grounding payloads (only when status=ambiguous)",
            },
            "message": {
                "type":        "string",
                "description": "Human-readable explanation (ambiguous/not_found)",
            },
        },
    },
)


def _get_player_snapshot_handler(
    args: dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to ``get_player_snapshot()``."""
    try:
        return get_player_snapshot(
            player_name=args["player_name"],
            bootstrap=bootstrap,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status":  "error",
            "code":    "tool_exception",
            "message": f"get_player_snapshot raised an unexpected error: {exc}",
        }


# Register with the shared tool registry so run_tool("get_player_snapshot", ...) works.
TOOL_REGISTRY.register(GET_PLAYER_SNAPSHOT_SPEC, _get_player_snapshot_handler)
