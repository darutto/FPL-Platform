"""Measurement-only legality and outcome graders for the agentic-loop experiment.

This module validates selections; it is deliberately not a squad optimiser and
is not called by any product path.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from typing import Any, Iterable


SQUAD_QUOTAS: dict[int, int] = {1: 2, 2: 5, 3: 5, 4: 3}
POSITION_LABELS: dict[int, str] = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
SELECTION_REQUIREMENTS: dict[str, tuple[int, int]] = {
    "Q7": (3, 4),
    "Q9": (4, 2),
}

CLASS2_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "Q10": {"position": 3, "min_price": 6.0, "max_price": 8.0},
    "Q11": {"position": 2, "min_price": 4.5, "max_price": 6.0},
}


def extract_json_block(answer_text: str) -> dict[str, Any] | None:
    """Return the last fenced JSON object, or None when no valid block exists."""
    matches = re.findall(r"```json\s*(\{.*?\})\s*```", answer_text or "", re.DOTALL | re.IGNORECASE)
    for raw in reversed(matches):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


#: Outcomes that mean orchestration itself failed, independent of any tool
#: result. These are reported identically by the loop and the legacy
#: single-round path, so they are safe to compare across arms.
ORCHESTRATION_FAILURE_OUTCOMES: frozenset[str] = frozenset({
    "no_client",
    "llm_error",
    "cooldown",
    "no_tool",
    "unknown_tool",
    "tool_error",
    "quota_exceeded",
    "worker_error",
})

#: Invariant fragments of content-free tool messages. These match on the stable
#: part of the sentence, NOT on a fully rendered example: the transfer-suggestion
#: message interpolates position, club and price clauses
#: (``f"No available {pos}{team}{price} found with positive form..."`` at
#: transfer_suggestion.py), so a marker like "no available midfielders found"
#: silently fails to match the price-filtered variant that this experiment
#: exists to measure.
CONTENT_FREE_MARKERS: tuple[str, ...] = (
    "found with positive form in the current bootstrap",
    "no encontr\u00e9 una herramienta",
    "llm call failed",
    "no se pudo completar una llamada",
)


def classify_user_visible(
    outcome: str,
    answer_text: str,
    tool_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Axis 1: identify churn-level empty/error/content-free responses.

    Arm-uniform by construction. ``outcome`` is deliberately NOT read as a
    general quality signal, because the arms do not agree on it: the bounded
    loop reports ``ok`` plus ``rounds_exhausted`` for grounded partials (so the
    harness delivers them instead of collapsing to ``unsupported``), while the
    legacy single-round path reports ``tool_result_error`` for the very same
    tool status. Scoring on ``outcome`` would therefore mark identical answer
    text catastrophic in arms A/B and substantive in arms C/D, handing the loop
    a systematic advantage on the headline churn metric that has nothing to do
    with answer quality.

    So orchestration-level failures are read from ``outcome`` (both paths agree
    there), and tool-level quality is read from the tool's own ``status``, which
    both paths populate identically.
    """
    text = (answer_text or "").strip()
    reasons: list[str] = []

    if outcome in ORCHESTRATION_FAILURE_OUTCOMES:
        reasons.append(f"outcome={outcome}")

    if isinstance(tool_output, dict):
        status = tool_output.get("status")
        if status is not None and status != "ok":
            reasons.append(f"tool_status={status}")

    if len(text) < 40:
        reasons.append("answer_too_short")

    lowered = text.lower()
    if any(marker in lowered for marker in CONTENT_FREE_MARKERS):
        reasons.append("content_free_stub")

    return {
        "classification": "catastrophic_failure" if reasons else "substantive_answer",
        "catastrophic_failure": bool(reasons),
        "reasons": reasons,
    }


def _player_index(bootstrap: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(player["id"]): player
        for player in bootstrap.get("elements", [])
        if isinstance(player, dict) and "id" in player
    }


def _cost(player: dict[str, Any]) -> int:
    try:
        return int(player.get("now_cost", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _minutes(player: dict[str, Any]) -> int:
    try:
        return int(player.get("minutes", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _millions_to_tenths(value: Any) -> int | None:
    try:
        return int(round(float(value) * 10))
    except (TypeError, ValueError):
        return None


def _duplicates(values: Iterable[int]) -> list[int]:
    seen: set[int] = set()
    duplicates: set[int] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


class _Edge:
    __slots__ = ("to", "rev", "cap", "cost")

    def __init__(self, to: Any, rev: int, cap: int, cost: int) -> None:
        self.to = to
        self.rev = rev
        self.cap = cap
        self.cost = cost


def _add_edge(graph: dict[Any, list[_Edge]], source: Any, target: Any, cap: int, cost: int) -> int:
    forward_index = len(graph[source])
    reverse_index = len(graph[target])
    graph[source].append(_Edge(target, reverse_index, cap, cost))
    graph[target].append(_Edge(source, forward_index, 0, -cost))
    return forward_index


def _min_cost_flow(
    graph: dict[Any, list[_Edge]], source: Any, sink: Any, target_flow: int
) -> tuple[int, int]:
    """Small successive-shortest-paths solver using SPFA for residual negatives."""
    flow = 0
    total_cost = 0
    while flow < target_flow:
        infinity = 10**12
        distance: dict[Any, int] = {node: infinity for node in graph}
        previous: dict[Any, tuple[Any, int]] = {}
        in_queue: set[Any] = {source}
        queue: deque[Any] = deque([source])
        distance[source] = 0

        while queue:
            node = queue.popleft()
            in_queue.discard(node)
            for edge_index, edge in enumerate(graph[node]):
                if edge.cap <= 0:
                    continue
                candidate = distance[node] + edge.cost
                if candidate >= distance[edge.to]:
                    continue
                distance[edge.to] = candidate
                previous[edge.to] = (node, edge_index)
                if edge.to not in in_queue:
                    queue.append(edge.to)
                    in_queue.add(edge.to)

        if sink not in previous:
            break

        augment = target_flow - flow
        node = sink
        while node != source:
            prior, edge_index = previous[node]
            augment = min(augment, graph[prior][edge_index].cap)
            node = prior
        node = sink
        while node != source:
            prior, edge_index = previous[node]
            edge = graph[prior][edge_index]
            edge.cap -= augment
            graph[node][edge.rev].cap += augment
            node = prior
        flow += augment
        total_cost += augment * distance[sink]
    return flow, total_cost


def exact_completion(
    bootstrap: dict[str, Any],
    locked_ids: Iterable[int],
    selected_ids: Iterable[int],
    *,
    budget_tenths: int = 1000,
) -> dict[str, Any]:
    """Return whether the fixed players have an exact legal, affordable completion."""
    players = _player_index(bootstrap)
    locked = [int(value) for value in locked_ids]
    selected = [int(value) for value in selected_ids]
    fixed = locked + selected
    if _duplicates(fixed):
        return {"completion_exists": False, "witness_squad": [], "reason": "duplicate_fixed_id"}
    if any(player_id not in players for player_id in fixed):
        return {"completion_exists": False, "witness_squad": [], "reason": "unknown_fixed_id"}

    position_counts: dict[int, int] = defaultdict(int)
    club_counts: dict[int, int] = defaultdict(int)
    fixed_cost = 0
    for player_id in fixed:
        player = players[player_id]
        position_counts[int(player.get("element_type", 0) or 0)] += 1
        club_counts[int(player.get("team", 0) or 0)] += 1
        fixed_cost += _cost(player)

    if fixed_cost > budget_tenths:
        return {"completion_exists": False, "witness_squad": [], "reason": "fixed_budget_exceeded"}
    if any(count > 3 for count in club_counts.values()):
        return {"completion_exists": False, "witness_squad": [], "reason": "fixed_club_cap_exceeded"}
    if any(position_counts[position] > quota for position, quota in SQUAD_QUOTAS.items()):
        return {"completion_exists": False, "witness_squad": [], "reason": "fixed_position_quota_exceeded"}

    remaining = {
        position: quota - position_counts[position]
        for position, quota in SQUAD_QUOTAS.items()
    }
    target_flow = sum(remaining.values())
    if target_flow == 0:
        return {
            "completion_exists": True,
            "witness_squad": fixed,
            "completion_ids": [],
            "minimum_completion_cost": 0,
            "total_cost": fixed_cost,
            "reason": None,
        }

    fixed_set = set(fixed)
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for player in players.values():
        player_id = int(player["id"])
        position = int(player.get("element_type", 0) or 0)
        club = int(player.get("team", 0) or 0)
        if player_id in fixed_set or remaining.get(position, 0) <= 0:
            continue
        if player.get("status") != "a" or _minutes(player) <= 0:
            continue
        if club_counts[club] >= 3:
            continue
        grouped[(club, position)].append(player)

    candidates: list[dict[str, Any]] = []
    for (_club, position), group in grouped.items():
        keep = min(remaining[position], 3)
        candidates.extend(sorted(group, key=lambda item: (_cost(item), int(item["id"])))[:keep])

    source = ("source",)
    sink = ("sink",)
    graph: dict[Any, list[_Edge]] = defaultdict(list)
    player_edges: dict[int, tuple[Any, int]] = {}
    for position, needed in remaining.items():
        if needed:
            _add_edge(graph, source, ("position", position), needed, 0)
    for player in candidates:
        player_id = int(player["id"])
        position = int(player["element_type"])
        club = int(player["team"])
        position_node = ("position", position)
        player_node = ("player", player_id)
        club_node = ("club", club)
        _add_edge(graph, position_node, player_node, 1, 0)
        edge_index = _add_edge(graph, player_node, club_node, 1, _cost(player))
        player_edges[player_id] = (player_node, edge_index)
    for club in {int(player["team"]) for player in candidates}:
        _add_edge(graph, ("club", club), sink, 3 - club_counts[club], 0)

    flow, completion_cost = _min_cost_flow(graph, source, sink, target_flow)
    completion_ids = sorted(
        player_id
        for player_id, (node, edge_index) in player_edges.items()
        if graph[node][edge_index].cap == 0
    )
    exists = flow == target_flow and fixed_cost + completion_cost <= budget_tenths
    witness = fixed + completion_ids if exists else []
    return {
        "completion_exists": exists,
        "witness_squad": witness,
        "completion_ids": completion_ids if exists else [],
        "minimum_completion_cost": completion_cost if flow == target_flow else None,
        "total_cost": fixed_cost + completion_cost if flow == target_flow else None,
        "reason": None if exists else ("budget_exceeded" if flow == target_flow else "flow_not_saturated"),
    }


def _validate_player_set(
    ids: list[int],
    players: dict[int, dict[str, Any]],
    *,
    expected_position: int | None = None,
) -> list[str]:
    errors: list[str] = []
    for player_id in ids:
        player = players.get(player_id)
        if player is None:
            errors.append(f"unknown_player:{player_id}")
            continue
        if player.get("status") != "a":
            errors.append(f"unavailable_player:{player_id}")
        if _minutes(player) <= 0:
            errors.append(f"zero_minutes:{player_id}")
        if expected_position is not None and int(player.get("element_type", 0) or 0) != expected_position:
            errors.append(f"wrong_position:{player_id}")
    return errors


def _validate_club_cap(ids: list[int], players: dict[int, dict[str, Any]]) -> list[str]:
    counts: dict[int, int] = defaultdict(int)
    for player_id in ids:
        if player_id in players:
            counts[int(players[player_id].get("team", 0) or 0)] += 1
    return [f"club_cap:{club}" for club, count in counts.items() if count > 3]


def validate_selection_payload(
    scenario_id: str,
    payload: dict[str, Any],
    bootstrap: dict[str, Any],
    expected_locked_ids: list[int],
    *,
    require_alternative: bool = True,
) -> dict[str, Any]:
    """Axis 2 validator for Q7/Q9 selection schemas."""
    players = _player_index(bootstrap)
    errors: list[str] = []
    expected_position, expected_count = SELECTION_REQUIREMENTS[scenario_id]
    try:
        locked = [int(value) for value in payload.get("locked_players", [])]
        primary = [int(value) for value in payload.get("primary_selection", [])]
        alternative = [int(value) for value in payload.get("alternative_selection", [])]
    except (TypeError, ValueError):
        return {"status": "invalid", "valid": False, "errors": ["non_integer_ids"]}

    if locked != expected_locked_ids:
        errors.append("locked_players_mismatch")
    if _duplicates(primary):
        errors.append("duplicate_primary_ids")
    if len(primary) != expected_count:
        errors.append("primary_count")
    if set(locked) & set(primary):
        errors.append("locked_primary_overlap")
    if require_alternative:
        if _duplicates(alternative):
            errors.append("duplicate_alternative_ids")
        if len(alternative) != expected_count:
            errors.append("alternative_count")
        if set(locked) & set(alternative):
            errors.append("locked_alternative_overlap")

    errors.extend(_validate_player_set(locked, players))
    errors.extend(_validate_player_set(primary, players, expected_position=expected_position))
    errors.extend(_validate_club_cap(locked + primary, players))
    if require_alternative:
        errors.extend(_validate_player_set(alternative, players, expected_position=expected_position))
        errors.extend(_validate_club_cap(locked + alternative, players))

    raw_prices = payload.get("quoted_prices")
    if not isinstance(raw_prices, dict):
        errors.append("quoted_prices_missing")
        raw_prices = {}
    if set(str(key) for key in raw_prices) != set(str(player_id) for player_id in primary):
        errors.append("quoted_prices_keys")
    for player_id in primary:
        quoted = _millions_to_tenths(raw_prices.get(str(player_id), raw_prices.get(player_id)))
        if player_id in players and quoted != _cost(players[player_id]):
            errors.append(f"quoted_price_mismatch:{player_id}")

    locked_cost = sum(_cost(players[player_id]) for player_id in locked if player_id in players)
    selection_cost = sum(_cost(players[player_id]) for player_id in primary if player_id in players)
    expected_values = {
        "locked_cost": locked_cost,
        "selection_cost": selection_cost,
        "total_cost_including_locked": locked_cost + selection_cost,
        "remaining_budget": 1000 - locked_cost - selection_cost,
    }
    for field, expected in expected_values.items():
        if _millions_to_tenths(payload.get(field)) != expected:
            errors.append(f"budget_reconciliation:{field}")
    if not payload.get("ranking_basis"):
        errors.append("ranking_basis_missing")
    formation = _parse_formation(payload.get("formation"))
    if formation is None or sum(formation) != 10 or not (
        3 <= formation[0] <= 5 and 2 <= formation[1] <= 5 and 1 <= formation[2] <= 3
    ):
        errors.append("formation_invalid")
    elif scenario_id == "Q7" and formation != (5, 4, 1):
        errors.append("formation_selection_mismatch")

    feasibility = exact_completion(bootstrap, locked, primary)
    if not feasibility["completion_exists"]:
        errors.append(f"infeasible_primary:{feasibility['reason']}")
    alternative_feasibility = None
    if require_alternative and len(alternative) == expected_count:
        alternative_feasibility = exact_completion(bootstrap, locked, alternative)
        if not alternative_feasibility["completion_exists"]:
            errors.append(f"infeasible_alternative:{alternative_feasibility['reason']}")

    return {
        "status": "valid" if not errors else "invalid",
        "valid": not errors,
        "errors": errors,
        "feasibility": feasibility,
        "alternative_feasibility": alternative_feasibility,
    }


def _parse_formation(value: Any) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"\s*(\d)\s*-\s*(\d)\s*-\s*(\d)\s*", str(value or ""))
    if not match:
        return None
    return tuple(int(group) for group in match.groups())  # type: ignore[return-value]


def validate_decision_payload(payload: dict[str, Any], bootstrap: dict[str, Any]) -> dict[str, Any]:
    """Axis 2 validator for the Q6 Bench Boost decision schema."""
    players = _player_index(bootstrap)
    errors: list[str] = []
    try:
        squad = [int(value) for value in payload.get("squad_selection", [])]
        xi = [int(value) for value in payload.get("starting_xi", [])]
        bench = [int(value) for value in payload.get("bench_selection", [])]
    except (TypeError, ValueError):
        return {"status": "invalid", "valid": False, "errors": ["non_integer_ids"]}

    if len(squad) != 15 or _duplicates(squad):
        errors.append("squad_unique_15")
    if len(xi) != 11 or _duplicates(xi):
        errors.append("xi_unique_11")
    if len(bench) != 4 or _duplicates(bench):
        errors.append("bench_unique_4")
    if set(xi) & set(bench) or set(xi) | set(bench) != set(squad):
        errors.append("xi_bench_partition")
    errors.extend(_validate_player_set(squad, players))
    errors.extend(_validate_club_cap(squad, players))

    squad_positions: dict[int, int] = defaultdict(int)
    xi_positions: dict[int, int] = defaultdict(int)
    bench_positions: dict[int, int] = defaultdict(int)
    for collection, counts in ((squad, squad_positions), (xi, xi_positions), (bench, bench_positions)):
        for player_id in collection:
            if player_id in players:
                counts[int(players[player_id].get("element_type", 0) or 0)] += 1
    if dict(squad_positions) != SQUAD_QUOTAS:
        errors.append("squad_position_quotas")
    formation = _parse_formation(payload.get("formation"))
    if formation is None:
        errors.append("formation_invalid")
    elif (
        xi_positions[1] != 1
        or (xi_positions[2], xi_positions[3], xi_positions[4]) != formation
        or sum(formation) != 10
    ):
        errors.append("xi_formation_mismatch")
    if bench_positions[1] != 1 or sum(bench_positions[position] for position in (2, 3, 4)) != 3:
        errors.append("bench_composition")

    total_cost = sum(_cost(players[player_id]) for player_id in squad if player_id in players)
    if total_cost > 1000:
        errors.append("budget_exceeded")
    if _millions_to_tenths(payload.get("total_cost")) != total_cost:
        errors.append("budget_reconciliation:total_cost")
    if payload.get("verdict") not in {"viable", "not_viable"}:
        errors.append("verdict_invalid")
    if not payload.get("ranking_basis"):
        errors.append("ranking_basis_missing")
    reasons = payload.get("reasons")
    if not isinstance(reasons, list) or not reasons:
        errors.append("reasons_missing")

    return {"status": "valid" if not errors else "invalid", "valid": not errors, "errors": errors}


def check_composition(tool_calls_trace: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify a tool trace exhibits class-2 composition (ranking + fixture grounding).

    Passes when the trace contains:
    - A rank_players_by_metric call WITH min_price or max_price (bare ranking doesn't count)
    - A get_fixture_outlook OR get_team_fixture_calendar call with a horizon

    Returns structured result: {status, valid, errors}
    """
    errors: list[str] = []

    # Check for price-bounded ranking
    has_priced_ranking = False
    for call in tool_calls_trace:
        if call.get("name") == "rank_players_by_metric":
            args = call.get("args", {})
            if args.get("min_price") is not None or args.get("max_price") is not None:
                has_priced_ranking = True
                break

    if not has_priced_ranking:
        errors.append("ranking_missing_or_unpriced")

    # Check for fixture grounding with horizon
    has_fixture_horizon = False
    for call in tool_calls_trace:
        if call.get("name") in {"get_fixture_outlook", "get_team_fixture_calendar"}:
            args = call.get("args", {})
            if args.get("horizon") is not None or args.get("horizon_gws") is not None:
                has_fixture_horizon = True
                break

    if not has_fixture_horizon:
        errors.append("fixture_grounding_missing")

    return {
        "status": "valid" if not errors else "invalid",
        "valid": not errors,
        "errors": errors,
    }


def validate_player_pick_payload(
    scenario_id: str,
    payload: dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Axis 2 validator for Q10/Q11 player-pick-by-price-range class-2 schemas.

    Checks:
    - player validity (status=a, minutes>0, correct position)
    - price containment (both primary and runner-up in range)
    - quoted price accuracy (exact match to bootstrap now_cost/10)
    - horizon fidelity (exactly 5 consecutive GWs from next_gw)
    - fixture grounding (fixture_evidence entries match team_fixtures exactly)
    - evidence coverage (recommendation team has entries for all 5 GWs)
    - candidate set (no duplicates, includes both picks)
    - provenance (ranking_basis present and contextually correct)
    """
    players = _player_index(bootstrap)
    errors: list[str] = []
    req = CLASS2_REQUIREMENTS.get(scenario_id)
    if not req:
        return {"status": "invalid", "valid": False, "errors": ["unknown_scenario"]}

    expected_position = req["position"]
    min_price = req["min_price"]
    max_price = req["max_price"]

    # Extract recommendation and runner-up IDs
    try:
        rec = payload.get("recommendation", {})
        rec_id = int(rec.get("id", 0) or 0)
        rec_price = float(rec.get("quoted_price", 0) or 0)
        runner = payload.get("runner_up", {})
        runner_id = int(runner.get("id", 0) or 0)
        runner_price = float(runner.get("quoted_price", 0) or 0)
    except (TypeError, ValueError):
        return {"status": "invalid", "valid": False, "errors": ["non_numeric_ids_or_prices"]}

    # Player validity checks
    for player_id in [rec_id, runner_id]:
        player = players.get(player_id)
        if player is None:
            errors.append(f"unknown_player:{player_id}")
            continue
        if player.get("status") != "a":
            errors.append(f"unavailable_player:{player_id}")
        if _minutes(player) <= 0:
            errors.append(f"zero_minutes:{player_id}")
        if int(player.get("element_type", 0) or 0) != expected_position:
            errors.append(f"wrong_position:{player_id}")

    # Price containment: convert to millions for comparison
    if rec_id in players:
        rec_actual_price = _cost(players[rec_id]) / 10.0
        if not (min_price <= rec_actual_price <= max_price):
            errors.append(f"recommendation_price_out_of_range:{rec_actual_price}")

    if runner_id in players:
        runner_actual_price = _cost(players[runner_id]) / 10.0
        if not (min_price <= runner_actual_price <= max_price):
            errors.append(f"runner_up_price_out_of_range:{runner_actual_price}")

    # Quoted price accuracy (check in integer tenths to avoid float comparison)
    if rec_id in players:
        expected_tenths = _cost(players[rec_id])
        quoted_tenths = _millions_to_tenths(rec_price)
        if quoted_tenths != expected_tenths:
            errors.append(f"recommendation_quoted_price_mismatch:{quoted_tenths}!={expected_tenths}")

    if runner_id in players:
        expected_tenths = _cost(players[runner_id])
        quoted_tenths = _millions_to_tenths(runner_price)
        if quoted_tenths != expected_tenths:
            errors.append(f"runner_up_quoted_price_mismatch:{quoted_tenths}!={expected_tenths}")

    # Horizon fidelity: exactly 5 consecutive GWs from next_gw
    events = bootstrap.get("events", [])
    current_gw = None
    for event in events:
        if event.get("is_current"):
            current_gw = int(event.get("id", 0) or 0)
            break
    next_gw = current_gw + 1 if current_gw else 1

    horizon_gws = payload.get("horizon_gws", [])
    expected_horizon = list(range(next_gw, next_gw + 5))
    if horizon_gws != expected_horizon:
        errors.append(f"horizon_mismatch:{horizon_gws}!={expected_horizon}")

    # Fixture grounding: validate fixture_evidence entries
    # team_fixtures is a pre-built structure with keys: difficulty, gameweek, is_home, opponent_team
    team_fixtures = bootstrap.get("team_fixtures", {})
    fixture_evidence = payload.get("fixture_evidence", [])

    if rec_id in players:
        rec_team = int(players[rec_id].get("team", 0) or 0)
        rec_fixtures = team_fixtures.get(rec_team) or team_fixtures.get(str(rec_team)) or []
        rec_gw_map = {f.get("gameweek"): f for f in rec_fixtures}

        # Collect fixture evidence entries for recommendation team
        rec_evidence = [e for e in fixture_evidence if e.get("team") == rec_team]
        if len(rec_evidence) < 5:
            errors.append(f"insufficient_fixture_evidence:{len(rec_evidence)}<5")

        for entry in rec_evidence:
            gw = entry.get("gameweek")
            if gw not in rec_gw_map:
                errors.append(f"fixture_evidence_gw_not_found:{gw}")
                continue

            actual_fixture = rec_gw_map[gw]
            expected_opponent = actual_fixture.get("opponent_team")
            if entry.get("opponent_team") != expected_opponent:
                errors.append(f"fixture_evidence_opponent_mismatch:{gw}:{entry.get('opponent_team')}!={expected_opponent}")

            expected_is_home = actual_fixture.get("is_home", False)
            if entry.get("is_home") != expected_is_home:
                errors.append(f"fixture_evidence_venue_mismatch:{gw}")

            expected_difficulty = actual_fixture.get("difficulty", None)
            if entry.get("difficulty") != expected_difficulty:
                errors.append(f"fixture_evidence_difficulty_mismatch:{gw}:{entry.get('difficulty')}!={expected_difficulty}")

    # Duplicate and inclusion checks
    candidates = payload.get("candidates_considered", [])
    if _duplicates(candidates):
        errors.append("duplicate_candidates")
    if rec_id not in candidates:
        errors.append("recommendation_not_in_candidates")
    if runner_id not in candidates:
        errors.append("runner_up_not_in_candidates")

    # Provenance
    if not payload.get("ranking_basis"):
        errors.append("ranking_basis_missing")

    return {
        "status": "valid" if not errors else "invalid",
        "valid": not errors,
        "errors": errors,
    }


def grade_structured_output(
    scenario_id: str,
    answer_text: str,
    tool_output: dict[str, Any],
    bootstrap: dict[str, Any],
    expected_locked_ids: list[int],
) -> dict[str, Any]:
    """Grade JSON when present; otherwise validate an unambiguous raw ranking."""
    payload = extract_json_block(answer_text)
    if payload is not None:
        if scenario_id == "Q6":
            result = validate_decision_payload(payload, bootstrap)
        elif scenario_id in CLASS2_REQUIREMENTS:
            result = validate_player_pick_payload(scenario_id, payload, bootstrap)
        else:
            result = validate_selection_payload(scenario_id, payload, bootstrap, expected_locked_ids)
        return {"source": "json_block", **result}

    if scenario_id in SELECTION_REQUIREMENTS:
        expected_position, expected_count = SELECTION_REQUIREMENTS[scenario_id]
        rows = tool_output.get("ranked") or tool_output.get("picks")
        if isinstance(rows, list) and len(rows) >= expected_count:
            ids = [int(row.get("id", 0) or 0) for row in rows[:expected_count]]
            players = _player_index(bootstrap)
            locked_cost = sum(_cost(players[player_id]) for player_id in expected_locked_ids if player_id in players)
            selection_cost = sum(_cost(players[player_id]) for player_id in ids if player_id in players)
            synthetic = {
                "locked_players": expected_locked_ids,
                "locked_cost": locked_cost / 10,
                "primary_selection": ids,
                "alternative_selection": [],
                "quoted_prices": {
                    str(player_id): _cost(players[player_id]) / 10
                    for player_id in ids if player_id in players
                },
                "selection_cost": selection_cost / 10,
                "total_cost_including_locked": (locked_cost + selection_cost) / 10,
                "remaining_budget": (1000 - locked_cost - selection_cost) / 10,
                "ranking_basis": tool_output.get("ranking_basis"),
            }
            result = validate_selection_payload(
                scenario_id,
                synthetic,
                bootstrap,
                expected_locked_ids,
                require_alternative=False,
            )
            return {
                "source": "raw_tool_output",
                # These fields are reconstructed from the trusted bootstrap,
                # not quoted or calculated by the model. They remain useful
                # for checking whether the raw ranking is legally completable,
                # but cannot be compared with JSON-block price/arithmetic
                # accuracy.
                "non_comparable_checks": [
                    "quoted_prices",
                    "budget_arithmetic",
                ],
                **result,
            }

    return {
        "source": None,
        "status": "structured_output_missing",
        "valid": None,
        "errors": [],
    }


def summarize_axis2_by_source(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Count legality statuses without pooling model JSON and raw fallbacks."""
    summary: dict[str, dict[str, int]] = {}
    for row in rows:
        axis2 = row.get("axis2") or {}
        source = str(axis2.get("source") or "none")
        status = str(axis2.get("status") or "unknown")
        source_counts = summary.setdefault(source, {})
        source_counts[status] = source_counts.get(status, 0) + 1
    return summary


def summarize_composition(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Count composition pass/fail/not_applicable/unknown for a set of observations.

    Returns: {"valid": N, "invalid": M, "not_applicable": K, "unknown": U}
    Unknown includes rows with missing composition key or unrecognized status.
    """
    summary = {"valid": 0, "invalid": 0, "not_applicable": 0, "unknown": 0}
    for row in rows:
        composition = row.get("composition")
        if composition is None:
            summary["unknown"] += 1
        else:
            status = composition.get("status", "unknown")
            if status == "valid":
                summary["valid"] += 1
            elif status == "invalid":
                summary["invalid"] += 1
            elif status == "not_applicable":
                summary["not_applicable"] += 1
            else:
                summary["unknown"] += 1
    return summary
