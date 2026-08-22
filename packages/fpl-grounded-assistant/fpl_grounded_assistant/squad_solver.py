"""Exact squad feasibility and best-squad generation over the FPL bootstrap.

Why this module exists
----------------------
A 120-observation experiment established that the LLM cannot do constrained
squad arithmetic, and that it fails *convincingly*: ``anthropic/C/Q6/1``
asserted "Coste Total: 133.5m (dentro del presupuesto de 100m)", and the arm-B
Q6 squad was grounded correctly in every per-player price and club yet totalled
117.5 against a 100.0 budget with four players from ARS and four from MCI,
while the prose claimed "Coste total: 100.0m". Grounding was never the problem;
arithmetic under constraints was.

So the arithmetic moves here, and the division of labour becomes explicit: the
model interprets the question, picks an objective and explains the result; this
module decides who is in the squad and what it costs. Every number the model
may quote is produced here.

Money is integer ``now_cost`` tenths end to end. Millions appear only in
display fields derived from those tenths, so a stated total can never drift
from the squad that produced it.

Contents
--------
``exact_completion``
    Was the measurement harness's legality oracle and still is: given a fixed
    set of players and a budget, does a legal completion exist, and what is the
    cheapest one?  Exact in both directions via min-cost flow, so a negative
    answer is a proof of infeasibility rather than a failed search.
``build_squad``
    The generator.  Same graph, different objective: maximise expected score
    subject to a budget ceiling instead of minimising cost.

The flow network
----------------
``source → position → player → club → sink``, capacity 1 per player, position
edges carrying the per-position quota, club edges capped at ``3 − |already from
that club|``.  Positional quotas and the three-per-club cap are therefore
structural: no post-hoc repair step can be forgotten, because an illegal squad
is not a flow in this graph at all.

Optimality claims, stated plainly
---------------------------------
*  Legality of any returned squad: guaranteed, and re-checked by
   ``validate_squad`` before the result leaves this module.
*  Infeasibility: exact.  ``build_squad`` reports infeasible only when the
   cheapest legal completion provably exceeds the budget.
*  The score maximum: near-optimal, not proven optimal.  Maximising a score
   subject to both a budget and the club/position structure is a
   multi-dimensional knapsack, so the search is a Lagrangian sweep over the
   budget multiplier followed by a single-swap improvement pass to a fixpoint.
   The result carries ``objective_optimality`` saying exactly this.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Callable, Iterable


#: The standard FPL 15-man squad split, keyed by ``element_type``.
SQUAD_QUOTAS: dict[int, int] = {1: 2, 2: 5, 3: 5, 4: 3}
POSITION_LABELS: dict[int, str] = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
POSITION_CODES: dict[str, int] = {label: code for code, label in POSITION_LABELS.items()}

#: Maximum players from one club.
CLUB_CAP: int = 3

#: Starting-XI shape rules: element_type -> (min, max) within the eleven.
XI_BOUNDS: dict[int, tuple[int, int]] = {1: (1, 1), 2: (3, 5), 3: (0, 5), 4: (1, 3)}
XI_SIZE: int = 11

#: Objective field -> integer scale applied to the raw bootstrap value, so the
#: whole search runs in integers.
#:
#: ``form`` is deliberately absent.  It reads 0.0 for every element pre-season,
#: so a form objective makes all squads tie and the solver returns whichever
#: one the tie-break happens to reach — an arbitrary answer wearing the shape
#: of a computed one.
OBJECTIVE_SCALES: dict[str, int] = {
    "total_points": 1,
    "points_per_game": 10,
}
DEFAULT_OBJECTIVE: str = "total_points"


# ---------------------------------------------------------------------------
# Bootstrap field access
# ---------------------------------------------------------------------------

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


def _duplicates(values: Iterable[int]) -> list[int]:
    seen: set[int] = set()
    duplicates: set[int] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _team_shorts(bootstrap: dict[str, Any]) -> dict[int, str]:
    return {
        int(team["id"]): str(team.get("short_name") or team.get("name") or team["id"])
        for team in bootstrap.get("teams", []) or []
        if isinstance(team, dict) and "id" in team
    }


def _tenths_to_millions(tenths: int) -> float:
    """Display-only conversion.  All arithmetic stays in ``tenths``."""
    return round(tenths / 10, 1)


# ---------------------------------------------------------------------------
# Min-cost flow (successive shortest paths, SPFA for residual negatives)
# ---------------------------------------------------------------------------

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
    """Small successive-shortest-paths solver using SPFA for residual negatives.

    Edge costs may be negative — ``build_squad`` minimises ``λ·price − score``.
    The underlying network is acyclic, so the zero flow is optimal for its value
    and successive shortest paths keeps every residual graph free of negative
    cycles.
    """
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


def _build_flow_graph(
    candidates: list[dict[str, Any]],
    remaining: dict[int, int],
    club_counts: dict[int, int],
    edge_cost: Callable[[dict[str, Any]], int],
) -> tuple[dict[Any, list[_Edge]], Any, Any, dict[int, tuple[Any, int]]]:
    """Assemble ``source → position → player → club → sink`` for one cost function."""
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
        player_node = ("player", player_id)
        _add_edge(graph, ("position", position), player_node, 1, 0)
        edge_index = _add_edge(graph, player_node, ("club", club), 1, edge_cost(player))
        player_edges[player_id] = (player_node, edge_index)
    for club in {int(player["team"]) for player in candidates}:
        _add_edge(graph, ("club", club), sink, CLUB_CAP - club_counts.get(club, 0), 0)
    return graph, source, sink, player_edges


def _saturated_ids(
    graph: dict[Any, list[_Edge]], player_edges: dict[int, tuple[Any, int]]
) -> list[int]:
    return sorted(
        player_id
        for player_id, (node, edge_index) in player_edges.items()
        if graph[node][edge_index].cap == 0
    )


# ---------------------------------------------------------------------------
# Feasibility oracle (the measurement harness's original entry point)
# ---------------------------------------------------------------------------

def exact_completion(
    bootstrap: dict[str, Any],
    locked_ids: Iterable[int],
    selected_ids: Iterable[int],
    *,
    budget_tenths: int = 1000,
    quotas: dict[int, int] | None = None,
    min_minutes: int = 1,
) -> dict[str, Any]:
    """Return whether the fixed players have an exact legal, affordable completion.

    ``quotas`` and ``min_minutes`` default to the standard 15-man split and
    "played at least a minute", which is the behaviour the measurement harness
    has always relied on; ``build_squad`` passes its own.
    """
    quotas = dict(quotas) if quotas else dict(SQUAD_QUOTAS)
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
    if any(count > CLUB_CAP for count in club_counts.values()):
        return {"completion_exists": False, "witness_squad": [], "reason": "fixed_club_cap_exceeded"}
    if any(position_counts[position] > quota for position, quota in quotas.items()):
        return {"completion_exists": False, "witness_squad": [], "reason": "fixed_position_quota_exceeded"}
    if any(position not in quotas for position in position_counts if position_counts[position]):
        return {"completion_exists": False, "witness_squad": [], "reason": "fixed_position_quota_exceeded"}

    remaining = {position: quota - position_counts[position] for position, quota in quotas.items()}
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
        if player.get("status") != "a" or _minutes(player) < max(1, min_minutes):
            continue
        if club_counts[club] >= CLUB_CAP:
            continue
        grouped[(club, position)].append(player)

    # Within one (club, position) group only the cheapest ``min(quota, cap)``
    # players can ever be needed by a minimum-cost solution, and any solution
    # using k of them re-maps onto the k cheapest. Pruning to that set keeps the
    # answer exact while shrinking the graph.
    candidates: list[dict[str, Any]] = []
    for (_club, position), group in grouped.items():
        keep = min(remaining[position], CLUB_CAP)
        candidates.extend(sorted(group, key=lambda item: (_cost(item), int(item["id"])))[:keep])

    graph, source, sink, player_edges = _build_flow_graph(
        candidates, remaining, club_counts, _cost
    )
    flow, completion_cost = _min_cost_flow(graph, source, sink, target_flow)
    completion_ids = _saturated_ids(graph, player_edges)
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


# ---------------------------------------------------------------------------
# Legality re-check — the last gate before any squad leaves this module
# ---------------------------------------------------------------------------

def validate_squad(
    squad_ids: Iterable[int],
    players: dict[int, dict[str, Any]],
    *,
    budget_tenths: int,
    quotas: dict[int, int],
) -> list[str]:
    """Return the list of broken rules for *squad_ids* — empty means legal.

    Deliberately re-derived from the bootstrap rather than trusted from the
    search, because "the search cannot produce an illegal squad" is exactly the
    kind of claim this project has learned to verify.
    """
    ids = [int(value) for value in squad_ids]
    errors: list[str] = []
    if _duplicates(ids):
        errors.append("duplicate_players")
    unknown = [player_id for player_id in ids if player_id not in players]
    if unknown:
        errors.append(f"unknown_players:{','.join(str(value) for value in unknown)}")
        return errors

    if len(ids) != sum(quotas.values()):
        errors.append(f"squad_size:{len(ids)}!={sum(quotas.values())}")

    position_counts: dict[int, int] = defaultdict(int)
    club_counts: dict[int, int] = defaultdict(int)
    total = 0
    for player_id in ids:
        player = players[player_id]
        position_counts[int(player.get("element_type", 0) or 0)] += 1
        club_counts[int(player.get("team", 0) or 0)] += 1
        total += _cost(player)

    for position, quota in quotas.items():
        if position_counts[position] != quota:
            errors.append(
                f"position_count:{POSITION_LABELS.get(position, position)}="
                f"{position_counts[position]}!={quota}"
            )
    for club, count in sorted(club_counts.items()):
        if count > CLUB_CAP:
            errors.append(f"club_cap:{club}={count}")
    if total > budget_tenths:
        errors.append(f"budget:{total}>{budget_tenths}")
    return errors


# ---------------------------------------------------------------------------
# Objective
# ---------------------------------------------------------------------------

def _objective_scorer(objective: str) -> Callable[[dict[str, Any]], int]:
    scale = OBJECTIVE_SCALES[objective]

    def score(player: dict[str, Any]) -> int:
        try:
            return int(round(float(player.get(objective, 0) or 0) * scale))
        except (TypeError, ValueError):
            return 0

    return score


# ---------------------------------------------------------------------------
# Score maximisation under a budget ceiling
# ---------------------------------------------------------------------------

def _lagrangian_search(
    candidates: list[dict[str, Any]],
    remaining: dict[int, int],
    club_counts: dict[int, int],
    budget_left: int,
    score_of: Callable[[dict[str, Any]], int],
) -> tuple[list[int], int, int] | None:
    """Best squad completion found by sweeping the budget multiplier λ.

    For a fixed λ the problem ``minimise λ·price − score`` is a plain min-cost
    flow, solved exactly.  Raising λ buys cheaper squads, so the smallest λ
    whose solution fits the budget is found by bisection.  Returns
    ``(ids, cost_tenths, score)`` or None when no completion saturates the flow.
    """
    target_flow = sum(remaining.values())
    if target_flow == 0:
        return [], 0, 0

    by_id = {int(player["id"]): player for player in candidates}
    denominator = 1000
    max_score = max((score_of(player) for player in candidates), default=0)
    # Above this multiplier a single tenth of price outweighs the largest score
    # swing the whole completion can contain, so the solution is the plain
    # minimum-cost one and cannot get any cheaper.
    highest = denominator * (target_flow * max(max_score, 0) + 1)

    def solve(numerator: int) -> tuple[list[int], int, int] | None:
        graph, source, sink, player_edges = _build_flow_graph(
            candidates,
            remaining,
            club_counts,
            lambda player: numerator * _cost(player) - denominator * score_of(player),
        )
        flow, _ = _min_cost_flow(graph, source, sink, target_flow)
        if flow != target_flow:
            return None
        ids = _saturated_ids(graph, player_edges)
        return (
            ids,
            sum(_cost(by_id[player_id]) for player_id in ids),
            sum(score_of(by_id[player_id]) for player_id in ids),
        )

    cheapest = solve(highest)
    if cheapest is None:
        return None
    if cheapest[1] > budget_left:
        # Even the minimum-cost completion overshoots. Callers reach this only
        # when the feasibility oracle disagrees, so surface it as "no answer"
        # rather than returning an over-budget squad.
        return None

    best = cheapest
    low, high = 0, highest
    while low < high:
        middle = (low + high) // 2
        attempt = solve(middle)
        if attempt is not None and attempt[1] <= budget_left:
            high = middle
            if attempt[2] > best[2]:
                best = attempt
        else:
            low = middle + 1
    final = solve(low)
    if final is not None and final[1] <= budget_left and final[2] > best[2]:
        best = final
    return best


def _improve_by_swaps(
    squad_ids: list[int],
    candidates_by_position: dict[int, list[dict[str, Any]]],
    players: dict[int, dict[str, Any]],
    fixed_ids: set[int],
    budget_tenths: int,
    score_of: Callable[[dict[str, Any]], int],
    *,
    max_iterations: int = 500,
) -> list[int]:
    """Hill-climb on single substitutions until no swap improves the score.

    Only ever moves between legal, in-budget squads: the swap keeps positional
    counts by construction, and the club cap and budget are checked before the
    move is accepted.
    """
    current = list(squad_ids)
    for _ in range(max_iterations):
        in_squad = set(current)
        spent = sum(_cost(players[player_id]) for player_id in current)
        club_counts: dict[int, int] = defaultdict(int)
        for player_id in current:
            club_counts[int(players[player_id].get("team", 0) or 0)] += 1

        best_move: tuple[int, int, int] | None = None  # (gain, out_id, in_id)
        for out_id in current:
            if out_id in fixed_ids:
                continue
            outgoing = players[out_id]
            position = int(outgoing.get("element_type", 0) or 0)
            out_club = int(outgoing.get("team", 0) or 0)
            out_score = score_of(outgoing)
            out_cost = _cost(outgoing)
            for incoming in candidates_by_position.get(position, ()):
                in_id = int(incoming["id"])
                if in_id in in_squad:
                    continue
                gain = score_of(incoming) - out_score
                if gain <= 0:
                    continue
                if spent - out_cost + _cost(incoming) > budget_tenths:
                    continue
                in_club = int(incoming.get("team", 0) or 0)
                if club_counts[in_club] - (1 if in_club == out_club else 0) >= CLUB_CAP:
                    continue
                # Deterministic tie-break: biggest gain, then lowest ids.
                key = (gain, -out_id, -in_id)
                if best_move is None or key > (best_move[0], -best_move[1], -best_move[2]):
                    best_move = (gain, out_id, in_id)

        if best_move is None:
            return sorted(current)
        _, out_id, in_id = best_move
        current[current.index(out_id)] = in_id
    return sorted(current)


# ---------------------------------------------------------------------------
# Starting XI
# ---------------------------------------------------------------------------

def parse_formation(formation: Any) -> tuple[int, int, int] | None:
    """Parse ``"4-5-1"`` into ``(defenders, midfielders, forwards)``.

    Returns None for anything that is not a legal outfield shape; the
    goalkeeper is implicit and never part of the string.
    """
    if formation is None:
        return None
    if isinstance(formation, (list, tuple)) and len(formation) == 3:
        parts = [str(part) for part in formation]
    else:
        parts = str(formation).replace("–", "-").replace(" ", "").split("-")
    if len(parts) != 3:
        return None
    try:
        defenders, midfielders, forwards = (int(part) for part in parts)
    except (TypeError, ValueError):
        return None
    shape = (defenders, midfielders, forwards)
    if defenders + midfielders + forwards != XI_SIZE - 1:
        return None
    for position, count in zip((2, 3, 4), shape):
        low, high = XI_BOUNDS[position]
        if not low <= count <= high:
            return None
    return shape


def _legal_shapes(available: dict[int, int]) -> list[tuple[int, int, int]]:
    shapes: list[tuple[int, int, int]] = []
    for defenders in range(XI_BOUNDS[2][0], min(XI_BOUNDS[2][1], available.get(2, 0)) + 1):
        for midfielders in range(XI_BOUNDS[3][0], min(XI_BOUNDS[3][1], available.get(3, 0)) + 1):
            forwards = XI_SIZE - 1 - defenders - midfielders
            low, high = XI_BOUNDS[4]
            if low <= forwards <= min(high, available.get(4, 0)):
                shapes.append((defenders, midfielders, forwards))
    return shapes


def _pick_starting_xi(
    squad_ids: list[int],
    players: dict[int, dict[str, Any]],
    score_of: Callable[[dict[str, Any]], int],
    shape: tuple[int, int, int] | None,
) -> tuple[list[int], list[int], tuple[int, int, int]] | None:
    """Return ``(xi_ids, bench_ids, shape)`` maximising the objective.

    Within a position the best eleven always takes the highest scorers, so the
    search only enumerates shapes, not line-ups.
    """
    by_position: dict[int, list[int]] = defaultdict(list)
    for player_id in squad_ids:
        by_position[int(players[player_id].get("element_type", 0) or 0)].append(player_id)
    for position in by_position:
        by_position[position].sort(key=lambda pid: (-score_of(players[pid]), pid))

    if not by_position.get(1):
        return None
    available = {position: len(ids) for position, ids in by_position.items()}
    shapes = [shape] if shape is not None else _legal_shapes(available)

    best: tuple[int, tuple[int, int, int], list[int]] | None = None
    for candidate in shapes:
        if any(count > available.get(position, 0) for position, count in zip((2, 3, 4), candidate)):
            continue
        chosen = [by_position[1][0]]
        for position, count in zip((2, 3, 4), candidate):
            chosen.extend(by_position[position][:count])
        total = sum(score_of(players[pid]) for pid in chosen)
        if best is None or (total, [-pid for pid in chosen]) > (best[0], [-pid for pid in best[2]]):
            best = (total, candidate, chosen)
    if best is None:
        return None

    xi = best[2]
    xi_set = set(xi)
    bench = [pid for pid in squad_ids if pid not in xi_set]
    # FPL bench order: the reserve keeper occupies its own slot, the rest are
    # ordered by the objective so the first substitution is the best one.
    bench.sort(
        key=lambda pid: (
            0 if int(players[pid].get("element_type", 0) or 0) == 1 else 1,
            -score_of(players[pid]),
            pid,
        )
    )
    return xi, bench, best[1]


# ---------------------------------------------------------------------------
# Public generator
# ---------------------------------------------------------------------------

def _player_payload(
    player: dict[str, Any],
    team_shorts: dict[int, str],
    score_of: Callable[[dict[str, Any]], int],
    objective: str,
    *,
    locked: bool,
) -> dict[str, Any]:
    cost = _cost(player)
    scale = OBJECTIVE_SCALES[objective]
    return {
        "id": int(player["id"]),
        "web_name": player.get("web_name"),
        "position": POSITION_LABELS.get(int(player.get("element_type", 0) or 0), "UNK"),
        "team_short": team_shorts.get(int(player.get("team", 0) or 0)),
        "price": _tenths_to_millions(cost),
        "price_tenths": cost,
        "objective_value": round(score_of(player) / scale, 1 if scale > 1 else 0)
        if scale > 1
        else score_of(player),
        "minutes": _minutes(player),
        "status": player.get("status"),
        "locked": locked,
    }


def build_squad(
    bootstrap: dict[str, Any],
    *,
    budget_tenths: int = 1000,
    locked_ids: Iterable[int] = (),
    position_counts: dict[int, int] | None = None,
    objective: str = DEFAULT_OBJECTIVE,
    min_minutes: int = 1,
    formation: Any = None,
) -> dict[str, Any]:
    """Build the best legal squad under a budget, or prove none exists.

    All money is integer ``now_cost`` tenths; ``budget_tenths=1000`` is the
    standard £100.0m.  Locked players are kept whatever their price, and their
    cost is charged against the same budget.
    """
    if objective not in OBJECTIVE_SCALES:
        return {
            "status": "invalid_argument",
            "code": "unknown_objective",
            "message": (
                f"Unknown objective '{objective}'. "
                f"Valid objectives: {', '.join(sorted(OBJECTIVE_SCALES))}."
            ),
            "valid_objectives": sorted(OBJECTIVE_SCALES),
        }

    quotas = dict(SQUAD_QUOTAS)
    warnings: list[str] = []
    if position_counts:
        try:
            override = {int(key): int(value) for key, value in position_counts.items()}
        except (TypeError, ValueError):
            return {
                "status": "invalid_argument",
                "code": "bad_position_counts",
                "message": "position_counts values must be integers keyed by position.",
            }
        if any(value < 0 for value in override.values()) or set(override) - set(SQUAD_QUOTAS):
            return {
                "status": "invalid_argument",
                "code": "bad_position_counts",
                "message": "position_counts must be non-negative counts for GKP/DEF/MID/FWD.",
            }
        quotas.update(override)
        if quotas != SQUAD_QUOTAS:
            warnings.append(
                "non_standard_squad_structure: a real FPL squad is 2 GKP / 5 DEF / "
                "5 MID / 3 FWD; this squad cannot be entered in the game as-is."
            )

    squad_size = sum(quotas.values())
    if squad_size <= 0:
        return {
            "status": "invalid_argument",
            "code": "bad_position_counts",
            "message": "position_counts must select at least one player.",
        }

    try:
        budget_tenths = int(budget_tenths)
    except (TypeError, ValueError):
        return {
            "status": "invalid_argument",
            "code": "bad_budget",
            "message": "budget must be a number of millions.",
        }
    if budget_tenths <= 0:
        return {
            "status": "invalid_argument",
            "code": "bad_budget",
            "message": "budget must be greater than zero.",
        }

    shape = parse_formation(formation)
    if formation is not None and shape is None:
        return {
            "status": "invalid_argument",
            "code": "bad_formation",
            "message": (
                f"'{formation}' is not a legal formation. Give DEF-MID-FWD summing to 10 "
                "(the goalkeeper is implicit), with 3-5 DEF and 1-3 FWD, e.g. 4-5-1 or 3-4-3."
            ),
        }

    players = _player_index(bootstrap)
    team_shorts = _team_shorts(bootstrap)
    locked = [int(value) for value in locked_ids]
    if _duplicates(locked):
        return {
            "status": "invalid_argument",
            "code": "duplicate_locked_player",
            "message": "The same player was locked more than once.",
        }
    unknown_locked = [player_id for player_id in locked if player_id not in players]
    if unknown_locked:
        return {
            "status": "invalid_argument",
            "code": "unknown_locked_player",
            "message": f"Unknown locked element id(s): {unknown_locked}.",
        }

    score_of = _objective_scorer(objective)
    min_minutes = max(1, int(min_minutes or 1))

    # ------------------------------------------------------------------
    # 1. Feasibility. Exact: a "no" here is a proof, not a failed search.
    # ------------------------------------------------------------------
    feasibility = exact_completion(
        bootstrap,
        locked_ids=locked,
        selected_ids=[],
        budget_tenths=budget_tenths,
        quotas=quotas,
        min_minutes=min_minutes,
    )
    locked_cost = sum(_cost(players[player_id]) for player_id in locked)
    if not feasibility["completion_exists"]:
        cheapest = feasibility.get("total_cost")
        return {
            "status": "infeasible",
            "code": feasibility.get("reason") or "no_legal_squad",
            "message": _infeasible_message(feasibility, budget_tenths, cheapest),
            "budget_tenths": budget_tenths,
            "budget": _tenths_to_millions(budget_tenths),
            "locked_cost_tenths": locked_cost,
            "locked_cost": _tenths_to_millions(locked_cost),
            "minimum_possible_cost_tenths": cheapest,
            "minimum_possible_cost": _tenths_to_millions(cheapest) if cheapest is not None else None,
            "shortfall_tenths": (cheapest - budget_tenths) if cheapest is not None else None,
            "squad": [],
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # 2. Maximise the objective over the same graph.
    # ------------------------------------------------------------------
    locked_set = set(locked)
    position_filled: dict[int, int] = defaultdict(int)
    club_counts: dict[int, int] = defaultdict(int)
    for player_id in locked:
        position_filled[int(players[player_id].get("element_type", 0) or 0)] += 1
        club_counts[int(players[player_id].get("team", 0) or 0)] += 1
    remaining = {position: quota - position_filled[position] for position, quota in quotas.items()}

    candidates = [
        player
        for player in players.values()
        if int(player["id"]) not in locked_set
        and remaining.get(int(player.get("element_type", 0) or 0), 0) > 0
        and player.get("status") == "a"
        and _minutes(player) >= min_minutes
        and club_counts[int(player.get("team", 0) or 0)] < CLUB_CAP
    ]
    candidates.sort(key=lambda player: int(player["id"]))

    solution = _lagrangian_search(
        candidates, remaining, club_counts, budget_tenths - locked_cost, score_of
    )
    if solution is None:
        squad_ids = sorted(feasibility["witness_squad"])
        optimality = "cheapest_legal_fallback"
    else:
        completion_ids = solution[0]
        candidates_by_position: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for player in candidates:
            candidates_by_position[int(player["element_type"])].append(player)
        squad_ids = _improve_by_swaps(
            sorted(locked + completion_ids),
            candidates_by_position,
            players,
            locked_set,
            budget_tenths,
            score_of,
        )
        optimality = "lagrangian_plus_single_swap_fixpoint"

    # ------------------------------------------------------------------
    # 3. Re-verify legality before anything leaves this module.
    # ------------------------------------------------------------------
    errors = validate_squad(squad_ids, players, budget_tenths=budget_tenths, quotas=quotas)
    if errors:
        fallback = sorted(feasibility["witness_squad"])
        fallback_errors = validate_squad(
            fallback, players, budget_tenths=budget_tenths, quotas=quotas
        )
        if fallback_errors:
            return {
                "status": "error",
                "code": "solver_produced_illegal_squad",
                "message": (
                    "Refusing to return a squad: the search and its cheapest-legal "
                    f"fallback both failed validation ({errors}; {fallback_errors})."
                ),
                "squad": [],
                "warnings": warnings,
            }
        squad_ids, optimality = fallback, "cheapest_legal_fallback"
        warnings.append("objective_search_rejected_by_validator: fell back to the cheapest legal squad")

    # ------------------------------------------------------------------
    # 4. Totals, XI and payload. Every number derives from `squad_ids`.
    # ------------------------------------------------------------------
    total_cost = sum(_cost(players[player_id]) for player_id in squad_ids)
    total_score = sum(score_of(players[player_id]) for player_id in squad_ids)
    scale = OBJECTIVE_SCALES[objective]

    unavailable = [
        player_id
        for player_id in locked
        if players[player_id].get("status") != "a" or _minutes(players[player_id]) < min_minutes
    ]
    if unavailable:
        warnings.append(
            "locked_player_not_available: kept on request despite status/minutes — "
            f"element id(s) {unavailable}"
        )

    ordered = sorted(
        squad_ids,
        key=lambda pid: (
            int(players[pid].get("element_type", 0) or 0),
            -_cost(players[pid]),
            pid,
        ),
    )
    squad_payload = [
        _player_payload(players[pid], team_shorts, score_of, objective, locked=pid in locked_set)
        for pid in ordered
    ]

    xi_result = _pick_starting_xi(squad_ids, players, score_of, shape)
    if xi_result is None:
        starting_xi: list[dict[str, Any]] = []
        bench: list[dict[str, Any]] = []
        chosen_shape = None
        if shape is not None:
            warnings.append(
                f"formation_not_fillable: {shape[0]}-{shape[1]}-{shape[2]} cannot be "
                "filled from this squad's positional split"
            )
    else:
        xi_ids, bench_ids, chosen = xi_result
        starting_xi = [
            _player_payload(players[pid], team_shorts, score_of, objective, locked=pid in locked_set)
            for pid in sorted(
                xi_ids,
                key=lambda pid: (int(players[pid].get("element_type", 0) or 0), -score_of(players[pid]), pid),
            )
        ]
        bench = [
            _player_payload(players[pid], team_shorts, score_of, objective, locked=pid in locked_set)
            for pid in bench_ids
        ]
        chosen_shape = f"{chosen[0]}-{chosen[1]}-{chosen[2]}"

    club_breakdown: dict[str, int] = defaultdict(int)
    for player_id in squad_ids:
        club_breakdown[team_shorts.get(int(players[player_id].get("team", 0) or 0), "?")] += 1

    return {
        "status": "ok",
        "objective": objective,
        "objective_optimality": optimality,
        "objective_total": round(total_score / scale, 1) if scale > 1 else total_score,
        "ranking_basis": _ranking_basis(bootstrap),
        "squad_size": len(squad_ids),
        "position_counts": {
            POSITION_LABELS[position]: quota for position, quota in sorted(quotas.items())
        },
        "club_counts": dict(sorted(club_breakdown.items())),
        "budget_tenths": budget_tenths,
        "budget": _tenths_to_millions(budget_tenths),
        "total_cost_tenths": total_cost,
        "total_cost": _tenths_to_millions(total_cost),
        "remaining_tenths": budget_tenths - total_cost,
        "remaining": _tenths_to_millions(budget_tenths - total_cost),
        "locked_cost_tenths": locked_cost,
        "locked_cost": _tenths_to_millions(locked_cost),
        "squad": squad_payload,
        "formation": chosen_shape,
        "starting_xi": starting_xi,
        "bench": bench,
        "min_minutes_filter": min_minutes,
        "warnings": warnings,
    }


def _infeasible_message(
    feasibility: dict[str, Any], budget_tenths: int, cheapest: int | None
) -> str:
    reason = feasibility.get("reason")
    budget = _tenths_to_millions(budget_tenths)
    if reason == "fixed_club_cap_exceeded":
        return "No legal squad exists: the locked players already break the three-per-club limit."
    if reason == "fixed_position_quota_exceeded":
        return "No legal squad exists: the locked players exceed the requested position counts."
    if reason == "fixed_budget_exceeded":
        return f"No legal squad exists: the locked players alone cost more than {budget}m."
    if reason == "duplicate_fixed_id":
        return "No legal squad exists: the same player was locked more than once."
    if reason == "unknown_fixed_id":
        return "No legal squad exists: a locked element id is not in this bootstrap."
    if cheapest is not None:
        return (
            f"No legal squad exists within {budget}m. The cheapest legal squad meeting "
            f"these constraints costs {_tenths_to_millions(cheapest)}m, "
            f"{_tenths_to_millions(cheapest - budget_tenths)}m over budget."
        )
    return (
        f"No legal squad exists within {budget}m: not enough available players to fill "
        "every position without breaking the three-per-club limit."
    )


def _ranking_basis(bootstrap: dict[str, Any]) -> str:
    """Temporal provenance for the objective, shared with the ranking tools.

    Imported lazily so this module stays usable as pure arithmetic by the
    measurement harness without pulling in the tool-registry import chain.
    """
    try:
        from .ranking_provenance import get_ranking_basis
    except ImportError:  # pragma: no cover - defensive, standalone use
        return "unknown"
    return get_ranking_basis(bootstrap)
