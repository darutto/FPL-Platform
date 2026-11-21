"""Plan to sign X: how the user's own squad can afford a named target.

Deterministic. The model names the target (and, once the user has chosen, the
number of moves); every number and every legality decision comes from here.

The question
------------
"How do I get <player> with my current team?" A 15-man squad is always full, so
signing X means selling somebody of X's position, and when the money is short a
second or third move (a downgrade elsewhere) has to raise the difference.

Two steps, so the answer never guesses how much the user is willing to do:

1. ``moves`` omitted -> ``stage="choose_moves"``: the tool returns the chip
   options ("1 transfer", "only free transfers", "use hits (-4 each)").
2. ``moves`` given -> ``stage="plan"``: up to :data:`MAX_OPTIONS` ranked plans.

Search
------
Plain enumeration over a 15-man squad (not an LP): one move is a single swap of
the target's position; two or three moves add downgrades -- sell a squad player,
buy the best-value cheaper player of the same position -- until the money
covers the target. Money is integer ``now_cost`` tenths throughout. Positional
quotas and the three-per-club cap are checked on every candidate squad, and
each returned option is re-proved with ``squad_solver.validate_squad``.

Ranking
-------
One scale, in points: ``score = loss * HORIZON_GWS + hit_cost``, lowest first.
``loss`` is a per-gameweek value, so ``loss * HORIZON_GWS`` is the estimated
points the squad gives up over the window and ``hit_cost`` is what the extra
moves cost outright (-4 each beyond the free transfers). A 3-move plan that
loses a little less than a 1-move plan therefore still ranks behind it once its
-8 is counted, and a 2-move plan wins only when what it saves clearly exceeds
its -4. Ties go to fewer moves, then to the player ids. The hit is shown on
every option as well as being inside the score.

``loss`` is the least value given up over the next :data:`HORIZON_GWS` gameweeks, where a
player's value is ``(form + XGI_WEIGHT * xGI/90) * availability * games / N``:
the same ``form`` and the minutes-shrunk ``xgi_per_90_shrunk`` the transfer tools
feed their position score with (reused via ``scoring_shared._derive_scoring_inputs``,
not re-derived), scaled by the chance the player plays and by how many fixtures
the club has in the window. The RAW per-90 rate is never used: a cameo of ten
minutes with one shot reads as an elite rate, and valuing a downgrade on it made a
route "gain" value (a negative loss) and rank first. ``position_score.
shrink_rate_by_minutes`` regresses a rate toward 0 in proportion to how little
playing time backs it, for every player, sold or bought.

Downgrade candidates must also have enough minutes to be judged: the repo's
existing minutes floor for rate metrics, ``rank_players_by_metric.
per_90_minutes_floor`` (270 minutes, or 30% of the minutes played so far, capped
early in the season). It applies once the bootstrap has a finished gameweek; with
none, minutes carry no information yet and the shrinkage alone limits the effect.
An injured, suspended or doubtful player therefore gives up little, which makes
him the best sale, and the card says why. Fixture difficulty is deliberately
not part of the loss: the player being sold and the one coming in are compared
on the same window and the question here is what the squad stops producing.

Money honesty
-------------
The public API exposes current prices only, never the selling price (which
keeps just half of a rise). The answer says so and accepts the user's real
bank and per-player selling prices (``bank`` / ``sell_prices``).

Free transfers are not exposed either and nothing in this repo derives them
from transfer history, so they are taken from the caller or reported as
unknown -- never guessed. "The caller" includes the turn's own text: when the
user says it («tengo 3 cambios disponibles», «2 FTs») ``free_transfers_text``
reads it and it wins over a number the model passed (or left out). With them unknown, "only free transfers" is not
offered, and the hit estimate says it assumes one free transfer.
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import Any

from fpl_tool_contract import tool_resolve_player
from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec

from .catalogue import t
from .find_players import _STATUS_MAP, _safe_float, _safe_int
from .get_my_squad import get_my_squad
from .locale_types import bootstrap_locale
from .rank_players_by_metric import finished_gameweeks, per_90_minutes_floor
from .scoring_shared import _derive_scoring_inputs
from .squad_solver import CLUB_CAP, POSITION_LABELS, SQUAD_QUOTAS, validate_squad
from .tool_schema_registry import PLAN_TO_SIGN_SCHEMA

#: Gameweeks the loss score looks ahead (Leo, 2026-11-20).
HORIZON_GWS: int = 5
#: Most moves in one plan, hits included (Leo, 2026-11-20).
MAX_MOVES: int = 3
#: Points a move beyond the free transfers costs.
HIT_COST: int = 4
#: xGI/90 is ~0-1 and form is ~0-10: this puts them on one scale.
XGI_WEIGHT: float = 5.0
MAX_OPTIONS: int = 3
#: Replacement candidates tried per downgrade (best value first).
_REPLACEMENT_POOL: int = 12

MOVES_ONE = "one"
MOVES_FREE = "free"
MOVES_HITS = "hits"
_MOVE_KEYS = (MOVES_ONE, MOVES_FREE, MOVES_HITS)


# ---------------------------------------------------------------------------
# Value
# ---------------------------------------------------------------------------

def _availability(el: dict[str, Any]) -> float:
    """Chance the player is on the pitch, 0..1. Not available and no chance -> 0."""
    status = el.get("status")
    chance = el.get("chance_of_playing_next_round")
    if chance is None:
        chance = el.get("chance_of_playing_this_round")
    if status == "a":
        return 1.0 if chance is None else max(0.0, min(1.0, _safe_float(chance) / 100.0))
    if status == "d":
        # FPL always sends a percentage for a doubt; without one, half.
        return 0.5 if chance is None else max(0.0, min(1.0, _safe_float(chance) / 100.0))
    return 0.0


def _games_factor(team_id: int, team_fixtures: dict[Any, Any], current_gw: int | None) -> float:
    """Fixtures the club has in the window over the window length (blank/double aware)."""
    if not team_fixtures or current_gw is None:
        return 1.0
    raw = team_fixtures.get(team_id) or team_fixtures.get(str(team_id)) or []
    games = sum(1 for f in raw if current_gw <= _safe_int(f.get("gameweek")) < current_gw + HORIZON_GWS)
    return games / HORIZON_GWS


class _Context:
    """Everything one call needs, read from the bootstrap once."""

    def __init__(self, bootstrap: dict[str, Any]) -> None:
        from fpl_api_client import get_current_gameweek

        self.bootstrap = bootstrap
        self.elements: dict[int, dict[str, Any]] = {
            _safe_int(el.get("id")): el for el in bootstrap.get("elements", []) if el.get("id") is not None
        }
        self.teams = {_safe_int(tm.get("id")): str(tm.get("short_name", "")) for tm in bootstrap.get("teams", [])}
        self.fdr_map = bootstrap.get("fixture_difficulty_map", {}) or {}
        self.team_fixtures = bootstrap.get("team_fixtures") or {}
        self.current_gw = get_current_gameweek(bootstrap)
        # Minutes a replacement needs before its rate means anything (see module docstring).
        self.minutes_floor = per_90_minutes_floor(bootstrap) if finished_gameweeks(bootstrap) > 0 else 0
        self._value: dict[int, float] = {}

    def cost(self, pid: int) -> int:
        return _safe_int(self.elements[pid].get("now_cost"))

    def position(self, pid: int) -> int:
        return _safe_int(self.elements[pid].get("element_type"))

    def club(self, pid: int) -> int:
        return _safe_int(self.elements[pid].get("team"))

    def value(self, pid: int) -> float:
        if pid not in self._value:
            el = self.elements[pid]
            inputs = _derive_scoring_inputs(el, self.fdr_map, self.team_fixtures, self.current_gw)
            raw = inputs["form"] + XGI_WEIGHT * inputs["xgi_per_90_shrunk"]
            self._value[pid] = raw * _availability(el) * _games_factor(self.club(pid), self.team_fixtures, self.current_gw)
        return self._value[pid]

    def card(self, pid: int, *, price_tenths: int | None = None) -> dict[str, Any]:
        el = self.elements[pid]
        code = str(el.get("status") or "")
        cost = self.cost(pid) if price_tenths is None else price_tenths
        return {
            "id": pid,
            "web_name": str(el.get("web_name", "")),
            "team_short": self.teams.get(self.club(pid), ""),
            "position": POSITION_LABELS.get(self.position(pid), ""),
            "price_tenths": cost,
            "price": round(cost / 10, 1),
            "status": _STATUS_MAP.get(code, "Unknown"),
            "status_code": code,
            "chance_of_playing": el.get("chance_of_playing_next_round"),
            "news": str(el.get("news") or ""),
            "value": round(self.value(pid), 2),
        }


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _bank_and_squad(squad: dict[str, Any]) -> tuple[int, list[int]]:
    ids = [_safe_int(p.get("id")) for p in squad.get("players", [])]
    bank = _safe_int((squad.get("summary") or {}).get("bank"))
    return bank, ids


def _clubs_ok(ids: list[int], ctx: _Context) -> bool:
    return all(n <= CLUB_CAP for n in Counter(ctx.club(i) for i in ids).values())


def _replacement(
    ctx: _Context,
    pool: list[int],
    *,
    max_cost: int,
    squad_after: list[int],
    taken: set[int],
) -> list[int]:
    """The best-value pool player costing at most ``max_cost`` that keeps clubs legal (0 or 1 items)."""
    for pid in pool:
        if pid not in taken and ctx.cost(pid) <= max_cost and _clubs_ok(squad_after + [pid], ctx):
            return [pid]
    return []


def _search(
    ctx: _Context,
    *,
    target: int,
    squad: list[int],
    bank: int,
    sell_price: dict[int, int],
    max_moves: int,
    exclude_out: set[int],
) -> list[dict[str, Any]]:
    """Every distinct plan of 1..max_moves moves, unranked."""
    target_cost = ctx.cost(target)
    pos = ctx.position(target)
    squad_set = set(squad)

    pools: dict[int, list[int]] = {}
    for pid, el in ctx.elements.items():
        if pid in squad_set or pid == target or el.get("status") != "a":
            continue
        if _safe_int(el.get("minutes")) < ctx.minutes_floor:
            continue  # too few minutes to judge: not a downgrade worth offering
        pools.setdefault(ctx.position(pid), []).append(pid)
    for position_pool in pools.values():
        position_pool.sort(key=lambda p: (-ctx.value(p), ctx.cost(p), p))

    plans: dict[frozenset[tuple[int, int]], dict[str, Any]] = {}

    def add(pairs: list[tuple[int, int]]) -> None:
        key = frozenset(pairs)
        if key in plans:
            return
        outs = {o for o, _ in pairs}
        ins = [i for _, i in pairs]
        after = [p for p in squad if p not in outs] + ins
        funds = bank + sum(sell_price[o] for o in outs)
        spend = sum(ctx.cost(i) for i in ins)
        if spend > funds or not _clubs_ok(after, ctx):
            return
        plans[key] = {"pairs": pairs, "after": after, "bank_after": funds - spend}

    out_candidates = [p for p in squad if ctx.position(p) == pos and p not in exclude_out]

    for out1 in out_candidates:
        need = target_cost - bank - sell_price[out1]
        base_squad = [p for p in squad if p != out1] + [target]
        if need <= 0 and _clubs_ok(base_squad, ctx):
            add([(out1, target)])
            continue
        if max_moves < 2:
            continue
        # Reached when the money is short, or when it is not but the target's
        # club would end up with four: a downgrade that sells a player of that
        # club can make the plan legal, so the club check is left to ``add``.
        others = [p for p in squad if p != out1 and p not in exclude_out]
        # Two moves: one downgrade covers the whole shortfall.
        for p in others:
            cap = sell_price[p] - need
            if need <= 0:
                cap = min(cap, sell_price[p])  # surplus money: a downgrade, never an upgrade
            if cap <= 0:
                continue
            after_sell = [q for q in base_squad if q != p]
            for r in _replacement(ctx, pools.get(ctx.position(p), []), max_cost=cap, squad_after=after_sell, taken=set()):
                add([(out1, target), (p, r)])
        if max_moves < 3:
            continue
        # Three moves: two downgrades share the shortfall.
        for p1, p2 in combinations(others, 2):
            for r1 in pools.get(ctx.position(p1), [])[:_REPLACEMENT_POOL * 3]:
                if ctx.cost(r1) >= sell_price[p1]:
                    continue
                saved = sell_price[p1] - ctx.cost(r1)
                after1 = [q for q in base_squad if q != p1] + [r1]
                need2 = need - saved
                if need2 <= 0:
                    continue  # one downgrade is enough: already a two-move plan
                cap2 = sell_price[p2] - need2
                if cap2 <= 0:
                    continue
                after2 = [q for q in after1 if q != p2]
                for r2 in _replacement(ctx, pools.get(ctx.position(p2), []), max_cost=cap2, squad_after=after2, taken={r1}):
                    add([(out1, target), (p1, r1), (p2, r2)])
    return list(plans.values())


def _hit_cost(moves: int, free_transfers: int | None) -> tuple[int, str]:
    """Points lost to hits and the basis: given, or assumed when unknown."""
    if free_transfers is None:
        return HIT_COST * max(0, moves - 1), "assumed_one_free"
    return HIT_COST * max(0, moves - free_transfers), "given"


def _score_plan(ctx: _Context, plan: dict[str, Any], sell_price: dict[int, int], free_transfers: int | None) -> dict[str, Any]:
    pairs = plan["pairs"]
    transfers = [
        {
            "out": ctx.card(o, price_tenths=sell_price[o]),
            "in": ctx.card(i),
            "role": "target" if idx == 0 else "downgrade",
        }
        for idx, (o, i) in enumerate(pairs)
    ]
    # The target's own value is the same in every plan, so the comparison is
    # what the squad gives up: value out minus value of the downgrades in.
    loss = sum(ctx.value(o) for o, _ in pairs) - sum(ctx.value(i) for idx, (_, i) in enumerate(pairs) if idx > 0)
    hit, basis = _hit_cost(len(pairs), free_transfers)
    rank_score = round(loss * HORIZON_GWS + hit, 4)
    return {
        "moves": len(pairs),
        "transfers": transfers,
        "loss": round(loss, 2),
        "hit_cost": hit,
        "hit_basis": basis,
        "bank_after_tenths": plan["bank_after"],
        "bank_after": round(plan["bank_after"] / 10, 1),
        "unavailable_sold": [tr["out"]["web_name"] for tr in transfers if tr["out"]["status_code"] != "a"],
        "points_given_up": round(loss * HORIZON_GWS, 2),
        "score": rank_score,
        "_sort": (rank_score, len(pairs), tuple(sorted(o for o, _ in pairs))),
    }


# ---------------------------------------------------------------------------
# Public tool
# ---------------------------------------------------------------------------

def _error(code: str, message: str, status: str = "invalid_argument") -> dict[str, Any]:
    return {"status": status, "code": code, "message": message}


def _move_options(ctx: _Context, target_name: str, free_transfers: int | None, locale: Any) -> list[dict[str, Any]]:
    """The chip step. 'Only free transfers' needs a known count of two or more."""
    options = [{"key": MOVES_ONE, "label": t("plan_to_sign.chip_one", locale)}]
    if free_transfers is not None and free_transfers >= 2:
        options.append({"key": MOVES_FREE, "label": t("plan_to_sign.chip_free", locale, n=min(free_transfers, MAX_MOVES))})
    options.append({"key": MOVES_HITS, "label": t("plan_to_sign.chip_hits", locale, cost=HIT_COST)})
    for option in options:
        option["send_text"] = t("plan_to_sign.chip_send", locale, name=target_name, choice=option["label"])
    return options


def plan_to_sign(
    target: Any = None,
    moves: Any = None,
    bank: float | None = None,
    free_transfers: Any = None,
    sell_prices: Any = None,
    exclude_out_ids: Any = None,
    bootstrap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Plan how the connected user's squad signs ``target``. See the module docstring."""
    if bootstrap is None:
        return _error("no_bootstrap", "plan_to_sign requires live bootstrap data.", "error")
    locale = bootstrap_locale(bootstrap)
    if target is None or (isinstance(target, str) and not target.strip()):
        return _error("missing_target", "target is required: the player the user wants to sign.")
    if moves is not None and moves not in _MOVE_KEYS:
        return _error("bad_moves", f"moves must be one of {', '.join(_MOVE_KEYS)}, got {moves!r}.")

    ft: int | None = None
    if free_transfers is not None:
        if isinstance(free_transfers, bool) or _safe_int(free_transfers, -1) < 0:
            return _error("bad_free_transfers", "free_transfers must be a whole number from 0 up.")
        ft = _safe_int(free_transfers)

    # What the user said in this turn's text wins over what the model passed (or
    # forgot to): the text is the user's own words. When the two disagree the card
    # says which number it used.
    ft_source = "model" if ft is not None else None
    stated = bootstrap.get("_free_transfers_stated")
    if isinstance(stated, int) and not isinstance(stated, bool) and 0 <= stated <= 5:
        if ft is None:
            ft_source = "text"
        elif ft != stated:
            ft_source = "text_over_model"
        ft = stated

    resolved = tool_resolve_player(target, bootstrap)
    if resolved.get("status") != "ok":
        return resolved
    target_id = int(resolved["player_id"])

    squad_result = get_my_squad(bootstrap)
    if squad_result.get("status") != "ok":
        return squad_result
    squad_bank, squad = _bank_and_squad(squad_result)
    if len(squad) != sum(SQUAD_QUOTAS.values()):
        return _error("squad_incomplete", "The linked squad does not have 15 players.", "error")

    ctx = _Context(bootstrap)
    if target_id not in ctx.elements:
        return _error("target_unknown", "The target is not in the current player data.", "error")
    if target_id in squad:
        return {"status": "ok", "stage": "already_owned", "target": ctx.card(target_id)}

    bank_source = "squad"
    bank_tenths = squad_bank
    if bank is not None:
        try:
            bank_tenths = int(round(float(bank) * 10))
        except (TypeError, ValueError):
            return _error("bad_bank", f"bank must be a number of millions, got {bank!r}.")
        if bank_tenths < 0:
            return _error("bad_bank", "bank cannot be negative.")
        bank_source = "user"

    sell_price = {pid: ctx.cost(pid) for pid in squad}
    price_basis = "current"
    user_sell_prices: list[dict[str, Any]] = []
    if sell_prices:
        if not isinstance(sell_prices, list):
            return _error("bad_sell_prices", "sell_prices must be a list of {player, price} items.")
        for item in sell_prices:
            hit = tool_resolve_player(str((item or {}).get("player", "")), bootstrap)
            if hit.get("status") != "ok" or int(hit["player_id"]) not in sell_price:
                return _error("bad_sell_prices", f"{(item or {}).get('player')!r} is not a player in the squad.")
            try:
                sell_price[int(hit["player_id"])] = int(round(float(item["price"]) * 10))
                user_sell_prices.append({"player": str(int(hit["player_id"])), "price": float(item["price"])})
            except (KeyError, TypeError, ValueError):
                return _error("bad_sell_prices", "each sell price needs a numeric price in millions.")
        price_basis = "user"
    if bank_source == "user":
        price_basis = "user"

    exclude: set[int] = set()
    for value in exclude_out_ids or []:
        exclude.add(_safe_int(value))

    target_cost = ctx.cost(target_id)
    base: dict[str, Any] = {
        "status": "ok",
        "target": ctx.card(target_id),
        "bank_tenths": bank_tenths,
        "bank": round(bank_tenths / 10, 1),
        "bank_source": bank_source,
        "price_basis": price_basis,
        "shortfall_tenths": max(0, target_cost - bank_tenths),
        "shortfall": round(max(0, target_cost - bank_tenths) / 10, 1),
        "free_transfers": ft,
        "free_transfers_basis": "given" if ft is not None else "unknown",
        "free_transfers_source": ft_source,
        "horizon_gws": HORIZON_GWS,
        "max_moves": MAX_MOVES,
    }

    if moves is None:
        one = _search(ctx, target=target_id, squad=squad, bank=bank_tenths, sell_price=sell_price,
                      max_moves=1, exclude_out=exclude)
        return {
            **base,
            "stage": "choose_moves",
            "one_move_options": len(one),
            "move_options": _move_options(ctx, base["target"]["web_name"], ft, locale),
        }

    if moves == MOVES_FREE and (ft is None or ft < 1):
        return _error("free_transfers_unknown", "free_transfers is needed for moves='free'.")
    max_moves = {MOVES_ONE: 1, MOVES_FREE: min(ft or 1, MAX_MOVES), MOVES_HITS: MAX_MOVES}[moves]

    plans = _search(ctx, target=target_id, squad=squad, bank=bank_tenths, sell_price=sell_price,
                    max_moves=max_moves, exclude_out=exclude)
    scored = sorted((_score_plan(ctx, p, sell_price, ft) for p in plans), key=lambda s: s["_sort"])
    options: list[dict[str, Any]] = []
    for option in scored:
        outs = {tr["out"]["id"] for tr in option["transfers"]}
        ins = [tr["in"]["id"] for tr in option["transfers"]]
        after = [p for p in squad if p not in outs] + ins
        errors = validate_squad(after, ctx.elements, budget_tenths=10**9, quotas=SQUAD_QUOTAS)
        if errors:  # the search cannot produce this; the proof is here to say so loudly
            continue
        option.pop("_sort")
        options.append(option)
        if len(options) >= MAX_OPTIONS:
            break

    best = options[0] if options else None
    plan_state = {
        "target_id": target_id,
        "moves": moves,
        "planned_out_ids": [tr["out"]["id"] for tr in best["transfers"]] if best else [],
        "shortfall_tenths": base["shortfall_tenths"],
        "bank_tenths": bank_tenths,
        "bank_source": bank_source,
        "price_basis": price_basis,
        "free_transfers": ft,
        "excluded_out_ids": sorted(exclude),
        # Everyone offered as a sale on this card, so "who else?" proposes new names.
        "shown_out_ids": sorted({tr["out"]["id"] for o in options for tr in o["transfers"]}),
        # The user's own selling prices, keyed by player id, so a follow-up keeps them.
        "user_sell_prices": user_sell_prices,
    }
    return {
        **base,
        "stage": "plan" if options else "infeasible",
        "moves": moves,
        "options": options,
        "plan_state": plan_state,
        "needs_user_numbers": True,
    }


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

PLAN_TO_SIGN_SPEC = ToolSpec(
    name=PLAN_TO_SIGN_SCHEMA.name,
    description=PLAN_TO_SIGN_SCHEMA.description,
    parameters=PLAN_TO_SIGN_SCHEMA.parameters,
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "stage": {"type": "string"},
            "target": {"type": "object"},
            "bank": {"type": "number"},
            "bank_tenths": {"type": "integer"},
            "shortfall": {"type": "number"},
            "free_transfers": {"type": ["integer", "null"]},
            "move_options": {"type": "array"},
            "options": {"type": "array"},
            "plan_state": {"type": "object"},
        },
    },
)


def _plan_to_sign_handler(args: dict[str, Any], bootstrap: dict[str, Any]) -> dict[str, Any]:
    try:
        return plan_to_sign(
            target=args.get("target"),
            moves=args.get("moves"),
            bank=args.get("bank"),
            free_transfers=args.get("free_transfers"),
            sell_prices=args.get("sell_prices"),
            exclude_out_ids=args.get("exclude_out_ids"),
            bootstrap=bootstrap,
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "code": "tool_exception", "message": f"plan_to_sign raised an unexpected error: {exc}"}


TOOL_REGISTRY.register(PLAN_TO_SIGN_SPEC, _plan_to_sign_handler)
