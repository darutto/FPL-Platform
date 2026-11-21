"""Follow-ups to a ``plan_to_sign`` answer: "who else can I sell to get the money?".

The question carries no player, so on its own it lands on the player snapshot
(the last of three failures that opened this track). The state of the previous
plan has to travel with the turn:

* ``plan_to_sign`` returns a ``plan_state`` (target, move choice, bank, prices,
  free transfers, everyone already offered as a sale);
* the server hands it back on the response (``AskResponse.plan_state``);
* the UI sends it again on the NEXT turn only (``AskRequest.plan_state``) --
  the chat posts every plain turn to the stateless ``/ask`` and drops any
  session, so a server-side session would not survive to this turn;
* ``ask_v2`` matches the follow-up here and re-runs ``plan_to_sign`` with that
  state. No model call: the question is a recognised phrase and the answer is
  the same deterministic tool.

The state arrives from the client, so it is a trust boundary: only the fields
this module names are read, ints and numbers are coerced, and anything else is
dropped. A state that does not validate means "no follow-up", never an error.
"""
from __future__ import annotations

import re
from typing import Any

from fpl_player_registry import normalize_player_name

BOOTSTRAP_KEY = "_plan_state"
_MOVES = ("one", "free", "hits")
_MAX_IDS = 40

#: Accent-folded, lower-cased phrases (``normalize_player_name`` is the project's
#: one folding function). Each asks for OTHER players to sell for the same target.
_FOLLOWUP_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        # English
        r"\bwho else\b.*\b(sell|sold|sale|move out|drop)\b",
        r"\b(anyone|anybody|someone|somebody) else\b.*\b(sell|sold|sale)\b",
        r"\bwhat else\b.*\b(sell|sale)\b",
        r"\bwho (other|different)\b.*\b(sell|sale)\b",
        r"\b(other|another|different|more|alternative) (players?|options?|sales?|sells?)\b.*\b(sell|sale|money|cash|funds?)\b",
        r"\bwho (can|could|should|do) i sell (instead|too|also|otherwise)\b",
        r"\b(other|another|more|different) options?\b",
        # Spanish
        r"\ba quien mas\b.*\b(vendo|vender|vendes|sacrifico|sacar)\b",
        r"\bquien mas\b.*\b(vender|vendo|sacar)\b",
        r"\bque (otro|otros|mas)\b.*\b(vender|vendo|venta|ventas)\b",
        r"\b(otro|otros|otra|otras) (jugadores?|opciones?|ventas?)\b.*\b(vender|venta|ventas|dinero|plata|fondos)\b",
        r"\bvender a alguien mas\b",
        r"\b(otras|otra|mas) opciones?\b",
    )
)


def is_plan_followup(question: Any) -> bool:
    """True when *question* asks for other players to sell for the same target."""
    text = normalize_player_name(question)
    if not text or len(text) > 300:
        return False
    return any(pattern.search(text) for pattern in _FOLLOWUP_PATTERNS)


def _ids(value: Any) -> list[int]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[int] = []
    for item in value[:_MAX_IDS]:
        if isinstance(item, bool) or not isinstance(item, int):
            continue
        out.append(item)
    return out


def sanitize_plan_state(raw: Any) -> dict[str, Any] | None:
    """The validated subset of a client-sent ``plan_state``, or ``None``."""
    if not isinstance(raw, dict):
        return None
    target = raw.get("target_id")
    moves = raw.get("moves")
    if isinstance(target, bool) or not isinstance(target, int) or moves not in _MOVES:
        return None
    state: dict[str, Any] = {
        "target_id": target,
        "moves": moves,
        "shown_out_ids": _ids(raw.get("shown_out_ids")),
        "planned_out_ids": _ids(raw.get("planned_out_ids")),
        "excluded_out_ids": _ids(raw.get("excluded_out_ids")),
        "bank_source": "user" if raw.get("bank_source") == "user" else "squad",
    }
    bank = raw.get("bank_tenths")
    if state["bank_source"] == "user" and isinstance(bank, int) and not isinstance(bank, bool) and bank >= 0:
        state["bank_tenths"] = bank
    free = raw.get("free_transfers")
    if isinstance(free, int) and not isinstance(free, bool) and 0 <= free <= 5:
        state["free_transfers"] = free
    prices: list[dict[str, Any]] = []
    for item in (raw.get("user_sell_prices") or [])[:15] if isinstance(raw.get("user_sell_prices"), list) else []:
        if (
            isinstance(item, dict)
            and isinstance(item.get("player"), str)
            and item["player"].isdigit()
            and isinstance(item.get("price"), (int, float))
            and not isinstance(item["price"], bool)
            and 0 < item["price"] < 30
        ):
            prices.append({"player": item["player"], "price": float(item["price"])})
    state["user_sell_prices"] = prices
    return state


def followup_args(state: dict[str, Any]) -> dict[str, Any]:
    """``plan_to_sign`` arguments that ask for NEW sales on the same plan.

    Everyone already offered stays excluded, so each "who else?" moves on. The
    target is passed as its numeric id, which the resolver treats as
    authoritative. The user's own bank and selling prices carry over; the
    squad's bank is re-read, not remembered.
    """
    args: dict[str, Any] = {
        "target": str(state["target_id"]),
        "moves": state["moves"],
        "exclude_out_ids": sorted(
            set(state["shown_out_ids"]) | set(state["planned_out_ids"]) | set(state["excluded_out_ids"])
        ),
    }
    if "bank_tenths" in state:
        args["bank"] = state["bank_tenths"] / 10
    if "free_transfers" in state:
        args["free_transfers"] = state["free_transfers"]
    if state["user_sell_prices"]:
        args["sell_prices"] = list(state["user_sell_prices"])
    return args
