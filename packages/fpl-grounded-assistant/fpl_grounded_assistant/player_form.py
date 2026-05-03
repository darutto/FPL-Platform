"""
fpl_grounded_assistant.player_form
====================================
Phase 2.6d Story 2.1: Player form history over last N gameweeks.

Calls the FPL element-summary API (``element-summary/{id}/``) to retrieve
per-GW history for a named player, then returns the last ``n_games`` entries.

Test-injection path
-------------------
Embed pre-fetched history data in the bootstrap under the key
``_element_summaries``:

    bootstrap["_element_summaries"] = {
        "2": {"history": [...]}   # element_id → element_summary response
    }

When this key is present the live API call is skipped — used by the
validation corpus and unit tests to avoid network access.

Design rules
------------
* Uses existing player resolution from fpl_tool_contract.
* Falls back gracefully when the element-summary API is unavailable.
* Returns ``status="ok"`` with a (possibly empty) history list.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any

from fpl_api_client.fpl_client import get_element_summary
from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec


# ---------------------------------------------------------------------------
# Tool spec (self-registers at import)
# ---------------------------------------------------------------------------

PLAYER_FORM_SPEC = ToolSpec(
    name="get_player_form",
    description=(
        "Return a player's FPL points history over the last N gameweeks. "
        "Requires a player query and an optional n_games integer (default 5). "
        "Uses the element-summary API; test-injectable via bootstrap._element_summaries."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query":   {"type": ["string", "integer"], "description": "Player name or ID"},
            "n_games": {"type": "integer", "description": "Number of recent GWs (default 5)"},
        },
        "required": ["query"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":   {"type": "string"},
            "web_name": {"type": "string"},
            "n_games":  {"type": "integer"},
            "history":  {"type": "array"},
        },
    },
)
def _get_player_form_handler(
    args:      "dict",
    bootstrap: "dict",
) -> "dict":
    query  = args.get("query", "")
    n_games = int(args.get("n_games", DEFAULT_N_GAMES))
    return get_player_form(query, bootstrap, n_games=n_games)


TOOL_REGISTRY.register(PLAYER_FORM_SPEC, _get_player_form_handler)


# ---------------------------------------------------------------------------
# Public defaults and latency constants
# ---------------------------------------------------------------------------

DEFAULT_N_GAMES: int = 5

#: Hard total-latency budget (seconds) for the element-summary API call,
#: enforced in ``_fetch_element_summary`` via daemon thread + join(timeout).
#: A delayed or hanging upstream call exceeding this budget returns ``None``
#: and the handler surfaces ``missing_context`` to the caller.
FORM_API_BUDGET_S: float = 5.0

#: Duration (seconds) the circuit guard stays open after a timeout miss.
#: During this window ``_fetch_element_summary`` fast-fails without spawning
#: a thread, capping thread accumulation under sustained API degradation.
ELEMENT_SUMMARY_COOLDOWN_S: float = 20.0


# ---------------------------------------------------------------------------
# Circuit guard  (Phase 2.6d.2)
# ---------------------------------------------------------------------------

class _ElementSummaryCircuitGuard:
    """Open/closed circuit guard for the element-summary endpoint.

    Protects against thread accumulation when the upstream API is
    persistently slow: after one timeout the guard opens, and subsequent
    calls fast-fail (returning ``None``) until the cooldown expires.

    State transitions
    -----------------
    CLOSED → OPEN  : ``record_timeout()`` — first thread-alive miss
    OPEN   → CLOSED: cooldown timer expires naturally (``is_open()``
                     returns ``False`` after ``cooldown_s`` seconds)
    OPEN   → CLOSED: ``record_success()`` — successful call during half-open
    CLOSED → CLOSED: exception / network error (does not open circuit;
                     thread terminates normally, no accumulation risk)

    Observability counters  (Phase 2.6d.3)
    ---------------------------------------
    ``timeout_open_events``   — increments each time ``record_timeout()`` fires
    ``fast_fail_events``      — increments each call that fast-fails via ``check_fast_fail()``
    ``successful_recoveries`` — increments each time ``record_success()`` closes an
                                open guard (normal closed→closed successes do not count)

    Thread-safety
    -------------
    All state mutations are protected by ``threading.Lock``.

    Test hooks
    ----------
    ``_reset()``     — force-close, restore canonical cooldown, zero counters.
    ``_cooldown_s``  — writable; set to a small value in tests for expiry checks.
    ``get_stats()``  — returns a read-only counter snapshot dict.
    """

    def __init__(self, cooldown_s: float = ELEMENT_SUMMARY_COOLDOWN_S) -> None:
        self._cooldown_s              = cooldown_s
        self._open_until              = 0.0   # monotonic timestamp; 0.0 == closed
        self._lock                    = threading.Lock()
        # Observability counters — all protected by _lock
        self._timeout_open_events:   int = 0
        self._fast_fail_events:      int = 0
        self._successful_recoveries: int = 0
        # Per-cycle flag: set True by record_timeout(), consumed once by
        # record_success() to count exactly one recovery per guard-open cycle.
        self._ever_opened:           bool = False

    def is_open(self) -> bool:
        """Return ``True`` when fast-fail is in effect.

        Side-effect free — does not modify counters.  Use for plain state
        assertions in tests or external inspection.
        """
        with self._lock:
            return time.monotonic() < self._open_until

    def check_fast_fail(self) -> bool:
        """Return ``True`` and increment ``fast_fail_events`` when guard is open.

        Preferred over ``is_open()`` inside ``_fetch_element_summary`` so that
        every skipped upstream call is counted atomically with the open check.
        """
        with self._lock:
            if time.monotonic() < self._open_until:
                self._fast_fail_events += 1
                return True
            return False

    def record_timeout(self) -> None:
        """Open the guard for ``_cooldown_s`` seconds and count the event."""
        with self._lock:
            self._open_until   = time.monotonic() + self._cooldown_s
            self._ever_opened  = True
            self._timeout_open_events += 1

    def record_success(self) -> None:
        """Close the guard; count one recovery per guard-open cycle.

        ``successful_recoveries`` increments exactly once per
        ``record_timeout()`` cycle, on the first successful call after
        cooldown expires (whether guard is still technically open or has
        already timed out).  Subsequent successes in the same closed
        period do not count.
        """
        with self._lock:
            was_ever_opened   = self._ever_opened
            self._open_until  = 0.0
            self._ever_opened = False   # consume the flag
            if was_ever_opened:
                self._successful_recoveries += 1

    def get_stats(self) -> dict[str, int]:
        """Return a thread-safe snapshot of all observability counters.

        Suitable for ops dashboards, structured logging, or test assertions.
        Keys are stable; values are cumulative since last ``_reset()``.
        """
        with self._lock:
            return {
                "timeout_open_events":   self._timeout_open_events,
                "fast_fail_events":      self._fast_fail_events,
                "successful_recoveries": self._successful_recoveries,
            }

    def _reset(self) -> None:
        """Force-close the guard, restore canonical cooldown, zero counters.

        For tests only.  Not safe to call from production hot path.
        """
        with self._lock:
            self._open_until              = 0.0
            self._cooldown_s              = ELEMENT_SUMMARY_COOLDOWN_S
            self._ever_opened             = False
            self._timeout_open_events     = 0
            self._fast_fail_events        = 0
            self._successful_recoveries   = 0


#: Module-level singleton.  Tests reset via ``_element_summary_guard._reset()``.
_element_summary_guard = _ElementSummaryCircuitGuard()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_GW_NUMBER_RE = re.compile(r'\b([1-9][0-9]?)\b')


def _fetch_element_summary(
    element_id: int,
    bootstrap: dict[str, Any],
    *,
    _budget_s: float = FORM_API_BUDGET_S,
) -> dict[str, Any] | None:
    """Fetch element summary with a wall-clock budget and circuit guard.

    Resolution order
    ----------------
    1. Bootstrap injection path (``_element_summaries`` key) — instant;
       bypasses both the guard and the thread gate; used by tests/caches.
    2. Circuit guard open check — if a previous call timed out within
       ``ELEMENT_SUMMARY_COOLDOWN_S``, fast-fail with ``None`` immediately
       without spawning a thread.
    3. Live API via a daemon ``threading.Thread`` + ``join(timeout=_budget_s)``.
       On success the guard is closed; on timeout the guard is opened.

    Why daemon Thread instead of ThreadPoolExecutor?
    ``ThreadPoolExecutor.__exit__`` calls ``shutdown(wait=True)``, which blocks
    until the worker finishes regardless of whether the timeout fired — the
    wall-clock cap is defeated.  A daemon ``Thread`` + ``join(timeout)``
    returns immediately, giving true bounded behaviour.

    Parameters
    ----------
    element_id:
        FPL element integer id.
    bootstrap:
        FPL bootstrap dict; checked for ``_element_summaries`` first.
    _budget_s:
        Total latency budget in seconds.  For test injection only —
        production code always uses the module-level ``FORM_API_BUDGET_S``.
    """
    # 1. Bootstrap injection path — always instant; bypasses guard.
    injected = bootstrap.get("_element_summaries", {})
    if str(element_id) in injected:
        return injected[str(element_id)]

    # 2. Circuit guard — fast-fail during cooldown without spawning a thread.
    #    check_fast_fail() is used (not is_open()) so the fast_fail counter
    #    is incremented atomically with the state check.
    if _element_summary_guard.check_fast_fail():
        return None

    # 3. Live API path — daemon thread with wall-clock budget.
    _result: list[dict | None]          = [None]
    _exc:    list[BaseException | None] = [None]

    def _call() -> None:
        try:
            _result[0] = get_element_summary(element_id)
        except Exception as exc:  # noqa: BLE001
            _exc[0] = exc

    thread = threading.Thread(target=_call, daemon=True)
    thread.start()
    thread.join(timeout=_budget_s)

    if thread.is_alive():
        _element_summary_guard.record_timeout()   # open circuit for cooldown period
        return None
    if _exc[0] is not None:
        # Network/HTTP error — thread terminated normally, no thread accumulation;
        # do NOT open the circuit (guard protects against *timeout* accumulation only).
        return None
    _element_summary_guard.record_success()       # close circuit
    return _result[0]


def _position_label(element_type: int) -> str:
    _MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
    return _MAP.get(element_type, "UNK")


def _team_short_for_element(element: dict, bootstrap: dict) -> str:
    team_id = element.get("team")
    for t in bootstrap.get("teams", []):
        if t.get("id") == team_id:
            return t.get("short_name", "?")
    return "?"


# ---------------------------------------------------------------------------
# Resolve player helper — returns (status, element_dict | None, player_meta)
# ---------------------------------------------------------------------------

def _resolve_player(
    query: str,
    bootstrap: dict[str, Any],
) -> tuple[str, dict | None, dict]:
    """Resolve the player and return (status, element, meta).

    status: "ok" | "not_found" | "ambiguous"
    element: the raw bootstrap element dict (or None on non-ok)
    meta: dict with web_name, team_short, position, player_id
    """
    from fpl_api_client.fpl_client import get_players, get_teams  # noqa: PLC0415
    from fpl_player_registry import build_registry               # noqa: PLC0415
    from fpl_query_tools import get_player_summary               # noqa: PLC0415

    players = get_players(bootstrap)
    teams   = get_teams(bootstrap)

    q = str(query).strip()
    try:
        int(q)
        is_numeric = True
    except (ValueError, TypeError):
        is_numeric = False

    if not is_numeric:
        reg = build_registry(players, teams)
        if q.lower() in reg.ambiguous_web_names:
            return "ambiguous", None, {}

    summary = get_player_summary(q, players, teams)
    if summary is None:
        return "not_found", None, {}

    element = next(
        (e for e in bootstrap.get("elements", []) if e.get("id") == summary["id"]),
        None,
    )

    meta = {
        "player_id":  summary["id"],
        "web_name":   summary["web_name"],
        "team_short": summary["team_short"],
        "position":   summary["position"],
    }
    return "ok", element, meta


# ---------------------------------------------------------------------------
# Public handler
# ---------------------------------------------------------------------------

def get_player_form(
    query: str,
    bootstrap: dict[str, Any],
    n_games: int = DEFAULT_N_GAMES,
    *,
    _budget_s: float = FORM_API_BUDGET_S,
) -> dict[str, Any]:
    """Return the last ``n_games`` FPL gameweek results for *query*.

    Parameters
    ----------
    query:
        Player web name, alias, or id.
    bootstrap:
        FPL bootstrap dict.  Embed ``_element_summaries`` for test injection.
    n_games:
        Number of most-recent gameweeks to include (default 5, capped at 38).

    Returns — status "ok"
    ----------------------
    ``status``      "ok"
    ``player_id``   FPL element id
    ``web_name``    Player display name
    ``team_short``  Three-letter team abbreviation
    ``position``    "GKP" | "DEF" | "MID" | "FWD"
    ``n_games``     Number of entries returned (≤ requested)
    ``history``     List of per-GW dicts, most-recent first:
                    {gameweek, minutes, goals_scored, assists, bonus, total_points}

    Returns — status "not_found" / "ambiguous"
    -------------------------------------------
    ``status``  "not_found" | "ambiguous"
    ``query``   Original query string

    Returns — status "missing_context"
    ------------------------------------
    ``status``   "missing_context"
    ``message``  Explanation (API unavailable)
    """
    n_games = max(1, min(int(n_games), 38))

    res_status, element, meta = _resolve_player(query, bootstrap)
    if res_status == "ambiguous":
        return {"status": "ambiguous", "query": str(query)}
    if res_status == "not_found":
        return {"status": "not_found", "query": str(query)}

    player_id = meta["player_id"]

    elem_summary = _fetch_element_summary(player_id, bootstrap, _budget_s=_budget_s)
    if elem_summary is None:
        return {
            "status":  "missing_context",
            "message": (
                f"Could not retrieve match history for {meta['web_name']}. "
                "The element-summary API may be unavailable."
            ),
            "query": str(query),
        }

    raw_history: list[dict] = elem_summary.get("history", [])

    # Take the last n_games entries (most recent), then reverse to get
    # most-recent-first ordering.
    tail = raw_history[-n_games:] if raw_history else []
    tail = list(reversed(tail))

    history = [
        {
            "gameweek":     int(entry.get("round", 0)),
            "minutes":      int(entry.get("minutes", 0)),
            "goals_scored": int(entry.get("goals_scored", 0)),
            "assists":      int(entry.get("assists", 0)),
            "bonus":        int(entry.get("bonus", 0)),
            "total_points": int(entry.get("total_points", 0)),
        }
        for entry in tail
    ]

    return {
        "status":     "ok",
        "player_id":  player_id,
        "web_name":   meta["web_name"],
        "team_short": meta["team_short"],
        "position":   meta["position"],
        "n_games":    len(history),
        "history":    history,
        "query":      str(query),
    }
