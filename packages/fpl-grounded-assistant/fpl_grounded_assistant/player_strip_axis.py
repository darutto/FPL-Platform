"""The player card's ``strip_axis``: attack or defence, from the role the player was listed to start in and, for
wide defenders, his attacking profile.

The rule is :mod:`football_intelligence.observed_axis` (pure, tested on its own). This module reads the licensed
lineup store once per build and keeps every player's observed role in memory; the FPL side of the rule (position,
minutes, xA/90 against the other defenders) comes from the bootstrap already loaded, so a card is a dict lookup
plus one pass over the defenders.

No extra latency for the card: when the index for the current build is not ready, the card gets ``None`` at once
(the UI keeps the FPL fallback: DEF/GKP defence, else attack) and the index is built in a background thread. A store
that is missing or unreadable, a fixture list that cannot be fetched, or ``FOOTBALL_INTELLIGENCE_ENABLED`` off: also
``None``. Never raises.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

_LOG = logging.getLogger("fpl_grounded_assistant.player_strip_axis")

_lock = threading.Lock()
#: ``build_id`` -> axes of that build, and every player's position-card window (the verdict's position line,
#: player_signals.py: the same matches get_position_changes reads); only the current build is kept.
_index: dict[str, Any] = {"build_id": None, "axes": None, "windows": None}
_building: set[str] = set()


def _current_build_id(handle: Any) -> str:
    """The build the local pointer names. Reads the small pointer file only: ``handle.build_id()`` validates the whole
    manifest, too slow for every card. The tables themselves are still read (and validated) through the handle."""
    root = getattr(handle, "cache_root", None)
    if root is None:
        return str(handle.build_id())
    from football_intelligence.distribution.licensed_runtime import LICENSED_V1  # noqa: PLC0415
    from football_intelligence.distribution.service import parse_pointer  # noqa: PLC0415

    return str(parse_pointer((root / LICENSED_V1.pointer_name).read_bytes())["build_id"])


def _build(handle: Any, build_id: str, bootstrap: dict[str, Any], fetch_fixtures: Callable[[], list] | None) -> None:
    try:
        from football_intelligence.observed_axis import observed_by_element  # noqa: PLC0415
        from football_intelligence.position_changes import DEFAULT_LIMIT, recent_windows_by_element  # noqa: PLC0415

        from .position_changes_tool import fixture_index  # noqa: PLC0415

        fixtures = fixture_index(bootstrap, fetch_fixtures)
        if fixtures is None:  # not remembered: the next card tries again
            return
        snapshots, slots = handle.table("lineup_snapshots"), handle.table("lineup_slots")
        axes = observed_by_element(snapshots, slots, fixtures)
        windows: dict[int, Any] = {}
        try:  # the position line only: a failure here must not cost the strip its axis
            # Same window as the position card (get_position_changes' default): his club's latest matches.
            windows = recent_windows_by_element(
                snapshots, slots, handle.table("squad_membership"), fixtures, limit=DEFAULT_LIMIT)
        except Exception:  # noqa: BLE001
            _LOG.warning("position window index build failed", exc_info=True)
        with _lock:
            _index.update(build_id=build_id, axes=axes, windows=windows)
    except Exception:  # noqa: BLE001
        _LOG.warning("strip axis index build failed", exc_info=True)
    finally:
        with _lock:
            _building.discard(build_id)


_FPL_POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _decide(observed: dict[str, Any] | None, element_id: int, bootstrap: dict[str, Any]) -> str | None:
    """Apply the FPL side of the rule from the bootstrap: position, and for a wide defender his xA/90 profile
    (season ``expected_assists`` per 90 minutes, unrounded; see ``football_intelligence.observed_axis``)."""
    if not observed:
        return None
    from football_intelligence.observed_axis import decide_axis, profile_threshold, xa_per_90  # noqa: PLC0415

    def per_90(e: dict[str, Any]) -> float:
        return xa_per_90(_num(e.get("expected_assists")), _num(e.get("minutes")))

    elements = bootstrap.get("elements") or []
    row = next((e for e in elements if e.get("id") == int(element_id)), None)
    if row is None:
        return None
    position = _FPL_POSITIONS.get(row.get("element_type"), "")
    threshold = None
    if position == "DEF" and observed.get("wide"):
        threshold = profile_threshold(
            (_num(e.get("minutes")), per_90(e)) for e in elements if e.get("element_type") == 2
        )
    return decide_axis(
        observed, fpl_position=position, minutes=_num(row.get("minutes")),
        xa_per_90=per_90(row), threshold=threshold,
    )


def _lookup(
    field: str,
    element_id: int,
    bootstrap: dict[str, Any],
    handle: Any,
    fetch_fixtures: Callable[[], list] | None,
    background: bool,
) -> tuple[bool, Any]:
    """``(ready, value)``: the player's entry in the current build's ``field`` index. Not ready -> the index is built
    (in a background thread unless ``background`` is False) and ``(False, None)`` comes back at once."""
    from .orch_config import is_football_intelligence_enabled  # noqa: PLC0415

    if not is_football_intelligence_enabled():
        return False, None
    if handle is None:
        from football_intelligence.distribution.licensed_runtime import handle_from_env  # noqa: PLC0415

        handle = handle_from_env()
    build_id = _current_build_id(handle)
    with _lock:
        ready = _index["build_id"] == build_id
        if ready:
            return True, (_index[field] or {}).get(int(element_id))
        if build_id in _building:
            return False, None
        _building.add(build_id)
    if background:
        threading.Thread(
            target=_build, args=(handle, build_id, bootstrap, fetch_fixtures),
            name="strip-axis-index", daemon=True,
        ).start()
        return False, None
    _build(handle, build_id, bootstrap, fetch_fixtures)
    with _lock:
        if _index["build_id"] != build_id:
            return False, None
        return True, (_index[field] or {}).get(int(element_id))


def strip_axis_for(
    element_id: int,
    bootstrap: dict[str, Any],
    *,
    handle: Any = None,
    fetch_fixtures: Callable[[], list] | None = None,
    background: bool = True,
) -> str | None:
    """``"attack"`` / ``"defence"`` from the observed role, or ``None`` for the FPL fallback.

    ``handle``, ``fetch_fixtures`` and ``background`` are the seams the tests use.
    """
    try:
        ready, observed = _lookup("axes", element_id, bootstrap, handle, fetch_fixtures, background)
        return _decide(observed, element_id, bootstrap) if ready else None
    except Exception:  # noqa: BLE001  (no store synced, unreadable pointer, ...)
        return None


def position_window_for(
    element_id: int,
    bootstrap: dict[str, Any],
    *,
    handle: Any = None,
    fetch_fixtures: Callable[[], list] | None = None,
    background: bool = True,
) -> list[dict[str, Any]] | None:
    """His position-card window (``football_intelligence.position_changes.recent_windows_by_element``: his club's
    latest ``DEFAULT_LIMIT`` matches, oldest first) from the same per-build index, or ``None`` while it is not ready /
    the store is off. A player with no stored lineup gets ``[]``. Same seams as :func:`strip_axis_for`. Never raises."""
    try:
        ready, window = _lookup("windows", element_id, bootstrap, handle, fetch_fixtures, background)
        return list(window or []) if ready else None
    except Exception:  # noqa: BLE001
        return None


def _reset_for_tests() -> None:
    with _lock:
        _index.update(build_id=None, axes=None, windows=None)
        _building.clear()
