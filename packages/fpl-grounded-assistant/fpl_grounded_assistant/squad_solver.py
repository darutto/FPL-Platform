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
``select_players``
    Partial selection: the best ``N`` players of one position that still leave
    a legal 15-man squad *completable*.  Same graph again, with the score moved
    onto ``N`` of the slots so every other slot is filled at minimum cost, and
    with ``exact_completion`` as the gate each returned selection must pass.

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

from collections import Counter, defaultdict, deque
from typing import Any, Callable, Iterable, NamedTuple

from .locale_types import Locale, DEFAULT_LOCALE


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


class _SelectionSpec(NamedTuple):
    """One position's slots split into a scored sub-quota of ``count`` places.

    ``build_squad`` scores every slot alike.  Partial selection is the same
    graph with the score moved onto ``count`` of one position's slots: the
    source feeds a dedicated ``("select", position)`` node of capacity
    ``count`` and the ordinary position node with the remainder, so exactly
    ``count`` players enter through the scored route while every other slot is
    filled at minimum cost.  ``eligible_ids`` is the set allowed to take that
    route (the price band); a player outside the band can still fill an
    ordinary slot, because the band constrains the *selection*, not the squad.

    Because the split is a capacity in the same network, "the rest of the squad
    still fits" is structural rather than repaired afterwards: a selection that
    strands the budget or the three-per-club cap is not a flow in this graph at
    all.
    """

    position: int
    count: int
    eligible_ids: frozenset[int]
    entry_cost: Callable[[dict[str, Any]], int]


def _build_flow_graph(
    candidates: list[dict[str, Any]],
    remaining: dict[int, int],
    club_counts: dict[int, int],
    edge_cost: Callable[[dict[str, Any]], int],
    *,
    selection: _SelectionSpec | None = None,
) -> tuple[
    dict[Any, list[_Edge]], Any, Any, dict[int, tuple[Any, int]], dict[int, tuple[Any, int]]
]:
    """Assemble ``source → position → player → club → sink`` for one cost function.

    With ``selection`` the source additionally feeds a scored sub-quota node,
    and the returned fifth element maps each eligible player to its edge on
    that node, so the chosen ``count`` reads back the same way the completion
    does.  Omitting ``selection`` reproduces the original graph exactly.
    """
    source = ("source",)
    sink = ("sink",)
    graph: dict[Any, list[_Edge]] = defaultdict(list)
    player_edges: dict[int, tuple[Any, int]] = {}
    selection_edges: dict[int, tuple[Any, int]] = {}
    select_node = ("select", selection.position) if selection is not None else None
    for position, needed in remaining.items():
        if selection is not None and position == selection.position:
            needed -= selection.count
        if needed:
            _add_edge(graph, source, ("position", position), needed, 0)
    if selection is not None and selection.count:
        _add_edge(graph, source, select_node, selection.count, 0)
    for player in candidates:
        player_id = int(player["id"])
        position = int(player["element_type"])
        club = int(player["team"])
        player_node = ("player", player_id)
        _add_edge(graph, ("position", position), player_node, 1, 0)
        if (
            selection is not None
            and position == selection.position
            and player_id in selection.eligible_ids
        ):
            selection_edges[player_id] = (
                select_node,
                _add_edge(graph, select_node, player_node, 1, selection.entry_cost(player)),
            )
        edge_index = _add_edge(graph, player_node, ("club", club), 1, edge_cost(player))
        player_edges[player_id] = (player_node, edge_index)
    for club in {int(player["team"]) for player in candidates}:
        _add_edge(graph, ("club", club), sink, CLUB_CAP - club_counts.get(club, 0), 0)
    return graph, source, sink, player_edges, selection_edges


def _candidate_pool(
    players: dict[int, dict[str, Any]],
    fixed_ids: set[int],
    remaining: dict[int, int],
    club_counts: dict[int, int],
    min_minutes: int,
) -> list[dict[str, Any]]:
    """Every player still eligible to fill a remaining slot, in id order.

    Shared by ``build_squad`` and ``select_players`` so the two can never
    disagree about who is available.
    """
    pool = [
        player
        for player in players.values()
        if int(player["id"]) not in fixed_ids
        and remaining.get(int(player.get("element_type", 0) or 0), 0) > 0
        and player.get("status") == "a"
        and _minutes(player) >= min_minutes
        and club_counts.get(int(player.get("team", 0) or 0), 0) < CLUB_CAP
    ]
    pool.sort(key=lambda player: int(player["id"]))
    return pool


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

    graph, source, sink, player_edges, _ = _build_flow_graph(
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
    *,
    selection: _SelectionSpec | None = None,
) -> tuple[list[int], int, int, list[int]] | None:
    """Best squad completion found by sweeping the budget multiplier λ.

    For a fixed λ the problem ``minimise λ·price − score`` is a plain min-cost
    flow, solved exactly.  Raising λ buys cheaper squads, so the smallest λ
    whose solution fits the budget is found by bisection.  Returns
    ``(ids, cost_tenths, score, selected_ids)`` or None when no completion
    saturates the flow.

    With ``selection`` the score sits on the sub-quota entry edges instead of
    the player edges, so the quantity maximised is the *selection's* score
    while the remaining slots are bought as cheaply as possible — which is what
    makes "the best N you can afford" the best N rather than the best squad.
    ``selected_ids`` is empty when no sub-quota was requested.
    """
    target_flow = sum(remaining.values())
    if target_flow == 0:
        return [], 0, 0, []

    by_id = {int(player["id"]): player for player in candidates}
    denominator = 1000
    max_score = max((score_of(player) for player in candidates), default=0)
    # Above this multiplier a single tenth of price outweighs the largest score
    # swing the whole completion can contain, so the solution is the plain
    # minimum-cost one and cannot get any cheaper.
    highest = denominator * (target_flow * max(max_score, 0) + 1)

    def solve(numerator: int) -> tuple[list[int], int, int, list[int]] | None:
        if selection is None:
            def edge_cost(player: dict[str, Any]) -> int:
                return numerator * _cost(player) - denominator * score_of(player)
        else:
            def edge_cost(player: dict[str, Any]) -> int:
                return numerator * _cost(player)

        graph, source, sink, player_edges, selection_edges = _build_flow_graph(
            candidates,
            remaining,
            club_counts,
            edge_cost,
            selection=selection,
        )
        flow, _ = _min_cost_flow(graph, source, sink, target_flow)
        if flow != target_flow:
            return None
        ids = _saturated_ids(graph, player_edges)
        chosen = _saturated_ids(graph, selection_edges) if selection is not None else []
        scored = chosen if selection is not None else ids
        return (
            ids,
            sum(_cost(by_id[player_id]) for player_id in ids),
            sum(score_of(by_id[player_id]) for player_id in scored),
            chosen,
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

    candidates = _candidate_pool(players, locked_set, remaining, club_counts, min_minutes)

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
    feasibility: dict[str, Any],
    budget_tenths: int,
    cheapest: int | None,
    locale: Locale = DEFAULT_LOCALE,
) -> str:
    """Build the infeasibility message. *locale* is a language-track F0
    carrier param; ignored for now (see F1)."""
    del locale  # F0: not yet honored.
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


# ---------------------------------------------------------------------------
# Partial selection under a budget
# ---------------------------------------------------------------------------
#
# The question this answers is "which N midfielders should I buy?", not "build
# me a team".  It is not a filter with extra steps: picking the N highest
# scorers inside a price band can strand the budget, so that the eleven slots
# left over have no legal, affordable filling at all -- or push a club past
# three once the locked players are counted.  That answer looks right and is
# wrong, which is exactly how the LLM was already wrong.
#
# So completability is not checked after the fact, it is the search space:
# ``_SelectionSpec`` makes the N picks a sub-quota inside the same 15-slot flow
# network, and a selection with no legal completion is not a flow.  On top of
# that, ``exact_completion`` -- the oracle build_squad already trusts -- is run
# on the final selection and its witness squad is re-checked by
# ``validate_squad``.  Nothing leaves this function without all three agreeing.

#: How many feasibility-oracle calls the selection hill-climb may spend.  Each
#: call is a full min-cost flow (~7ms on the live bootstrap), so this is a wall
#: clock budget, and hitting it is reported in ``objective_optimality`` rather
#: than hidden.
_SELECTION_ORACLE_BUDGET: int = 200


def _price_bound_filter(
    player: dict[str, Any], min_price_tenths: int | None, max_price_tenths: int | None
) -> bool:
    cost = _cost(player)
    if min_price_tenths is not None and cost < min_price_tenths:
        return False
    if max_price_tenths is not None and cost > max_price_tenths:
        return False
    return True


def _selection_attempt(
    candidates: list[dict[str, Any]],
    remaining: dict[int, int],
    club_counts: dict[int, int],
    budget_left: int,
    position: int,
    count: int,
    eligible_ids: frozenset[int],
    score_of: Callable[[dict[str, Any]], int],
) -> tuple[list[int], int] | None:
    """Best ``count`` eligible players of ``position``, or None if none fit.

    None is an exact answer, not a failed search: at the top of the multiplier
    sweep the flow is the cheapest way to field ``count`` eligible players of
    that position alongside a full legal squad, so if that overshoots the
    budget then no such selection exists.  Returns ``(selection_ids, score)``.
    """
    if count <= 0:
        return [], 0
    denominator = 1000
    spec = _SelectionSpec(
        position=position,
        count=count,
        eligible_ids=eligible_ids,
        entry_cost=lambda player: -denominator * score_of(player),
    )
    solution = _lagrangian_search(
        candidates, remaining, club_counts, budget_left, score_of, selection=spec
    )
    if solution is None or len(solution[3]) != count:
        return None
    return solution[3], solution[2]


def _improve_selection(
    bootstrap: dict[str, Any],
    players: dict[int, dict[str, Any]],
    locked: list[int],
    selection_ids: list[int],
    eligible: list[dict[str, Any]],
    score_of: Callable[[dict[str, Any]], int],
    *,
    budget_tenths: int,
    quotas: dict[int, int],
    min_minutes: int,
    oracle_budget: int = _SELECTION_ORACLE_BUDGET,
) -> tuple[list[int], bool]:
    """Hill-climb on the selection with ``exact_completion`` as the gate.

    The multiplier sweep is exact for each λ but the budget-constrained maximum
    can sit in a concavity no λ reaches, so a single-substitution pass follows,
    the same shape ``build_squad`` uses.  The difference that matters: a swap is
    accepted only when the feasibility oracle finds a legal, affordable 15-man
    completion for the *new* selection, so an improving-but-stranding swap is
    rejected rather than taken.

    Returns ``(selection, reached_fixpoint)``.
    """
    locked_cost = sum(_cost(players[player_id]) for player_id in locked)
    locked_clubs = Counter(int(players[player_id].get("team", 0) or 0) for player_id in locked)
    ranked = sorted(eligible, key=lambda player: (-score_of(player), int(player["id"])))
    current = list(selection_ids)
    calls = 0

    for _ in range(len(current) * 4 + 1):
        current_set = set(current)
        improved = False
        # Worst-scoring slot first: it has the most room to gain.
        for out_id in sorted(current, key=lambda pid: (score_of(players[pid]), pid)):
            out_score = score_of(players[out_id])
            for player in ranked:
                if score_of(player) <= out_score:
                    break  # ranked descending -- nothing further can improve
                in_id = int(player["id"])
                if in_id in current_set:
                    continue
                trial = [pid for pid in current if pid != out_id] + [in_id]
                # Two free structural rejections before spending an oracle call.
                if locked_cost + sum(_cost(players[pid]) for pid in trial) > budget_tenths:
                    continue
                clubs = Counter(locked_clubs)
                for pid in trial:
                    clubs[int(players[pid].get("team", 0) or 0)] += 1
                if max(clubs.values(), default=0) > CLUB_CAP:
                    continue
                if calls >= oracle_budget:
                    return sorted(current), False
                calls += 1
                if exact_completion(
                    bootstrap,
                    locked_ids=locked,
                    selected_ids=trial,
                    budget_tenths=budget_tenths,
                    quotas=quotas,
                    min_minutes=min_minutes,
                )["completion_exists"]:
                    current = trial
                    improved = True
                    break
            if improved:
                break
        if not improved:
            return sorted(current), True
    return sorted(current), False


def _selection_payload(
    ids: Iterable[int],
    players: dict[int, dict[str, Any]],
    team_shorts: dict[int, str],
    score_of: Callable[[dict[str, Any]], int],
    objective: str,
    locked_set: set[int],
) -> list[dict[str, Any]]:
    """Per-player rows, best first, so the caller never has to sort or add up."""
    ordered = sorted(
        ids, key=lambda pid: (-score_of(players[pid]), -_cost(players[pid]), pid)
    )
    return [
        _player_payload(
            players[pid], team_shorts, score_of, objective, locked=pid in locked_set
        )
        for pid in ordered
    ]


def select_players(
    bootstrap: dict[str, Any],
    *,
    position: int,
    count: int,
    budget_tenths: int = 1000,
    locked_ids: Iterable[int] = (),
    objective: str = DEFAULT_OBJECTIVE,
    min_minutes: int = 1,
    min_price_tenths: int | None = None,
    max_price_tenths: int | None = None,
    oracle_budget: int = _SELECTION_ORACLE_BUDGET,
) -> dict[str, Any]:
    """Pick the best ``count`` players of one position that a full squad can absorb.

    Every returned selection is *completable*: a legal 15-man squad exists that
    contains the locked players plus the selection, inside the same budget and
    the three-per-club cap.  The witness for that claim is returned, and it has
    itself been through ``validate_squad``.

    When no such selection exists the answer is an explicit ``infeasible``
    naming what would be affordable instead.  A near-miss is never dressed up
    as a valid answer -- that is the failure this whole module exists to remove.

    Money is integer ``now_cost`` tenths throughout; millions are display only.
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
    if position not in SQUAD_QUOTAS:
        return {
            "status": "invalid_argument",
            "code": "bad_position",
            "message": f"Unknown position code {position!r}. Use GKP, DEF, MID or FWD.",
        }
    try:
        count = int(count)
    except (TypeError, ValueError):
        return {
            "status": "invalid_argument",
            "code": "bad_count",
            "message": "count must be a whole number of players.",
        }
    if count <= 0:
        return {
            "status": "invalid_argument",
            "code": "bad_count",
            "message": "count must be at least 1.",
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
    if (
        min_price_tenths is not None
        and max_price_tenths is not None
        and min_price_tenths > max_price_tenths
    ):
        return {
            "status": "invalid_argument",
            "code": "bad_price_bounds",
            "message": (
                f"min_price {_tenths_to_millions(min_price_tenths)}m is above max_price "
                f"{_tenths_to_millions(max_price_tenths)}m."
            ),
        }

    quotas = dict(SQUAD_QUOTAS)
    players = _player_index(bootstrap)
    team_shorts = _team_shorts(bootstrap)
    label = POSITION_LABELS[position]

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
    locked_set = set(locked)
    locked_cost = sum(_cost(players[player_id]) for player_id in locked)
    warnings: list[str] = []
    unavailable = [
        player_id
        for player_id in locked
        if players[player_id].get("status") != "a"
        or _minutes(players[player_id]) < min_minutes
    ]
    if unavailable:
        warnings.append(
            "locked_player_not_available: kept on request despite status/minutes — "
            f"element id(s) {unavailable}"
        )

    position_filled: dict[int, int] = defaultdict(int)
    club_counts: dict[int, int] = defaultdict(int)
    for player_id in locked:
        position_filled[int(players[player_id].get("element_type", 0) or 0)] += 1
        club_counts[int(players[player_id].get("team", 0) or 0)] += 1
    remaining = {slot: quota - position_filled[slot] for slot, quota in quotas.items()}

    header = {
        "position": label,
        "count": count,
        "objective": objective,
        "ranking_basis": _ranking_basis(bootstrap),
        "budget_tenths": budget_tenths,
        "budget": _tenths_to_millions(budget_tenths),
        "locked_cost_tenths": locked_cost,
        "locked_cost": _tenths_to_millions(locked_cost),
        "locked_players": _selection_payload(
            locked, players, team_shorts, score_of, objective, locked_set
        ),
        "price_bounds": {
            "min": _tenths_to_millions(min_price_tenths) if min_price_tenths is not None else None,
            "max": _tenths_to_millions(max_price_tenths) if max_price_tenths is not None else None,
        },
        "min_minutes_filter": min_minutes,
    }

    open_slots = remaining.get(position, 0)
    if count > open_slots:
        return {
            **header,
            "status": "invalid_argument",
            "code": "selection_exceeds_position_quota",
            "message": (
                f"A squad holds {quotas[position]} {label}, and the locked players already "
                f"fill {position_filled[position]} of them, so at most {open_slots} more can "
                f"be picked — not {count}. Ask for {open_slots} or fewer, or use build_squad "
                "to rebuild the whole squad."
            ),
            "selection": [],
            "completable": False,
            "warnings": warnings,
        }

    # -- 1. Can the locked set be a squad at all?  Exact, so "no" is a proof. --
    feasibility = exact_completion(
        bootstrap,
        locked_ids=locked,
        selected_ids=[],
        budget_tenths=budget_tenths,
        quotas=quotas,
        min_minutes=min_minutes,
    )
    if not feasibility["completion_exists"]:
        cheapest = feasibility.get("total_cost")
        return {
            **header,
            "status": "infeasible",
            "code": feasibility.get("reason") or "no_legal_squad",
            "message": _infeasible_message(feasibility, budget_tenths, cheapest),
            "minimum_possible_cost_tenths": cheapest,
            "minimum_possible_cost": _tenths_to_millions(cheapest) if cheapest is not None else None,
            "selection": [],
            "completable": False,
            "affordable": None,
            "warnings": warnings,
        }

    # -- 2. Who may be selected, and who may merely fill a slot. --------------
    candidates = _candidate_pool(players, locked_set, remaining, club_counts, min_minutes)
    at_position = [
        player for player in candidates if int(player["element_type"]) == position
    ]
    in_band = [
        player
        for player in at_position
        if _price_bound_filter(player, min_price_tenths, max_price_tenths)
    ]
    banded = min_price_tenths is not None or max_price_tenths is not None
    header["candidate_pool"] = {
        "position_total": len(at_position),
        "within_price_bounds": len(in_band),
    }

    budget_left = budget_tenths - locked_cost

    def attempt(pool: list[dict[str, Any]], size: int, scorer):
        return _selection_attempt(
            candidates,
            remaining,
            club_counts,
            budget_left,
            position,
            size,
            frozenset(int(player["id"]) for player in pool),
            scorer,
        )

    result = attempt(in_band, count, score_of) if len(in_band) >= count else None

    if result is not None:
        selection, _score = result
        selection, fixpoint = _improve_selection(
            bootstrap,
            players,
            locked,
            selection,
            in_band,
            score_of,
            budget_tenths=budget_tenths,
            quotas=quotas,
            min_minutes=min_minutes,
            oracle_budget=oracle_budget,
        )

        # -- 3. The completability claim, proved and then re-checked. --------
        witness = exact_completion(
            bootstrap,
            locked_ids=locked,
            selected_ids=selection,
            budget_tenths=budget_tenths,
            quotas=quotas,
            min_minutes=min_minutes,
        )
        witness_ids = sorted(witness.get("witness_squad") or [])
        errors = (
            validate_squad(witness_ids, players, budget_tenths=budget_tenths, quotas=quotas)
            if witness["completion_exists"]
            else ["completion_does_not_exist"]
        )
        if errors:
            return {
                **header,
                "status": "error",
                "code": "selection_failed_completion_check",
                "message": (
                    "Refusing to return a selection: its 15-man completion did not "
                    f"survive validation ({errors}). No near-miss is returned."
                ),
                "selection": [],
                "completable": False,
                "warnings": warnings,
            }

        selection_cost = sum(_cost(players[pid]) for pid in selection)
        selection_score = sum(score_of(players[pid]) for pid in selection)
        filler_cost = int(witness["minimum_completion_cost"])
        remaining_budget = budget_tenths - locked_cost - selection_cost
        scale = OBJECTIVE_SCALES[objective]
        witness_clubs: dict[str, int] = defaultdict(int)
        witness_positions: dict[str, int] = defaultdict(int)
        for player_id in witness_ids:
            witness_clubs[team_shorts.get(int(players[player_id].get("team", 0) or 0), "?")] += 1
            witness_positions[
                POSITION_LABELS.get(int(players[player_id].get("element_type", 0) or 0), "UNK")
            ] += 1

        return {
            **header,
            "status": "ok",
            "completable": True,
            "objective_optimality": (
                "lagrangian_plus_selection_swap_fixpoint"
                if fixpoint
                else "lagrangian_plus_selection_swap_truncated"
            ),
            "objective_total": round(selection_score / scale, 1) if scale > 1 else selection_score,
            "selection": _selection_payload(
                selection, players, team_shorts, score_of, objective, locked_set
            ),
            "selection_cost_tenths": selection_cost,
            "selection_cost": _tenths_to_millions(selection_cost),
            "remaining_tenths": remaining_budget,
            "remaining": _tenths_to_millions(remaining_budget),
            "completion": {
                "exists": True,
                "proof": "exact_completion",
                "slots_left": len(witness_ids) - len(locked) - len(selection),
                "cheapest_fill_cost_tenths": filler_cost,
                "cheapest_fill_cost": _tenths_to_millions(filler_cost),
                "witness_total_cost_tenths": locked_cost + selection_cost + filler_cost,
                "witness_total_cost": _tenths_to_millions(
                    locked_cost + selection_cost + filler_cost
                ),
                "witness_position_counts": dict(sorted(witness_positions.items())),
                "witness_club_counts": dict(sorted(witness_clubs.items())),
                "witness_squad": _selection_payload(
                    witness_ids, players, team_shorts, score_of, objective, locked_set
                ),
                "note": (
                    "The witness is the CHEAPEST legal completion, shown to prove the "
                    "selection is affordable — it is not a recommended bench. "
                    "Use build_squad for a squad worth entering."
                ),
            },
            "warnings": warnings,
        }

    # -- 4. Infeasible.  Say so, and name what would be affordable. ----------
    return _selection_infeasible(
        header=header,
        attempt=attempt,
        at_position=at_position,
        in_band=in_band,
        banded=banded,
        count=count,
        label=label,
        players=players,
        team_shorts=team_shorts,
        score_of=score_of,
        objective=objective,
        locked_set=locked_set,
        budget_tenths=budget_tenths,
        locked_cost=locked_cost,
        warnings=warnings,
    )


def _selection_infeasible(
    *,
    header: dict[str, Any],
    attempt: Callable[..., tuple[list[int], int] | None],
    at_position: list[dict[str, Any]],
    in_band: list[dict[str, Any]],
    banded: bool,
    count: int,
    label: str,
    players: dict[int, dict[str, Any]],
    team_shorts: dict[int, str],
    score_of: Callable[[dict[str, Any]], int],
    objective: str,
    locked_set: set[int],
    budget_tenths: int,
    locked_cost: int,
    warnings: list[str],
) -> dict[str, Any]:
    """Build the explicit no-answer, with the affordable alternative attached.

    "There is no such selection" is only half an answer; the other half is what
    the budget does reach.  Both halves come from the same search, so the
    alternative offered is itself completable rather than a guess.

    Only a price band gets here.  By the time this runs, ``exact_completion``
    has already proved a legal 15-man completion of the locked set exists, and
    that squad holds the full positional quota, of which ``count`` is a
    validated subset — so dropping the band always leaves a selection
    available.  The unbanded branch below is therefore a guard against a future
    filter, not a path the current tool takes.
    """
    affordable: dict[str, Any] | None = None
    max_price_run = None
    relaxed = attempt(at_position, count, score_of) if len(at_position) >= count else None
    if relaxed is not None:
        max_price_run = attempt(at_position, count, _cost)

    def describe(ids: list[int]) -> dict[str, Any]:
        cost = sum(_cost(players[pid]) for pid in ids)
        return {
            "count": len(ids),
            "players": _selection_payload(
                ids, players, team_shorts, score_of, objective, locked_set
            ),
            "selection_cost_tenths": cost,
            "selection_cost": _tenths_to_millions(cost),
        }

    if relaxed is not None:
        affordable = {"best_by_objective": describe(relaxed[0])}
        if max_price_run is not None:
            affordable["most_expensive_that_fits"] = describe(max_price_run[0])
        code = "no_completable_selection_in_price_band" if banded else "no_completable_selection"
        priciest_fit = affordable.get("most_expensive_that_fits")
        bounds = header.get("price_bounds") or {}
        band_text = ""
        if bounds.get("min") is not None and bounds.get("max") is not None:
            band_text = f" priced {bounds['min']}m–{bounds['max']}m"
        elif bounds.get("min") is not None:
            band_text = f" priced at least {bounds['min']}m"
        elif bounds.get("max") is not None:
            band_text = f" priced at most {bounds['max']}m"
        if len(in_band) < count:
            why = (
                f"only {len(in_band)} available {label}{band_text} exist, so {count} cannot "
                "be picked"
            )
        else:
            why = (
                f"no {count} available {label}{band_text} leave a legal 15-man squad "
                f"completable within {header['budget']}m"
            )
        message = (
            f"No selection returned: {why}. "
            f"What does fit: the best {count} {label} affordable here cost "
            f"{affordable['best_by_objective']['selection_cost']}m in total"
        )
        if priciest_fit is not None:
            # Stated as a selection that was found and proved, not as a proven
            # ceiling: this is the same near-optimal sweep as the objective.
            message += (
                f", and the priciest {count} {label} this search could still fit cost "
                f"{priciest_fit['selection_cost']}m in total"
            )
        message += "."
    else:
        # Guard, not a path: see the docstring. Still an explicit no rather
        # than a near-miss, because that is the invariant of this whole module.
        code = "no_completable_selection"
        message = (
            f"No selection returned: no {count} available {label} leave a legal 15-man "
            f"squad completable within {header['budget']}m, with or without a price "
            f"bound (locked players already account for {header['locked_cost']}m). "
            "Free a slot, raise the budget, or use build_squad to rebuild the squad."
        )

    return {
        **header,
        "status": "infeasible",
        "code": code,
        "message": message,
        "selection": [],
        "completable": False,
        "affordable": affordable,
        "warnings": warnings,
    }
