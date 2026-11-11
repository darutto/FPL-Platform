"""The player card's ``strip_axis``: attack or defence, from the role the player was listed to start in.

The rule is :mod:`football_intelligence.observed_axis` (pure, tested on its own). This module reads the licensed
lineup store once per build, keeps every player's axis in memory, and answers the card with a dict lookup.

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
#: ``build_id`` -> axes of that build; only the current build is kept.
_index: dict[str, Any] = {"build_id": None, "axes": None}
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
        from football_intelligence.observed_axis import axes_by_element  # noqa: PLC0415

        from .position_changes_tool import fixture_index  # noqa: PLC0415

        fixtures = fixture_index(bootstrap, fetch_fixtures)
        if fixtures is None:  # not remembered: the next card tries again
            return
        axes = axes_by_element(handle.table("lineup_snapshots"), handle.table("lineup_slots"), fixtures)
        with _lock:
            _index.update(build_id=build_id, axes=axes)
    except Exception:  # noqa: BLE001
        _LOG.warning("strip axis index build failed", exc_info=True)
    finally:
        with _lock:
            _building.discard(build_id)


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
        from .orch_config import is_football_intelligence_enabled  # noqa: PLC0415

        if not is_football_intelligence_enabled():
            return None
        if handle is None:
            from football_intelligence.distribution.licensed_runtime import handle_from_env  # noqa: PLC0415

            handle = handle_from_env()
        build_id = _current_build_id(handle)
        with _lock:
            if _index["build_id"] == build_id:
                return _index["axes"].get(int(element_id))
            if build_id in _building:
                return None
            _building.add(build_id)
        if background:
            threading.Thread(
                target=_build, args=(handle, build_id, bootstrap, fetch_fixtures),
                name="strip-axis-index", daemon=True,
            ).start()
            return None
        _build(handle, build_id, bootstrap, fetch_fixtures)
        with _lock:
            return _index["axes"].get(int(element_id)) if _index["build_id"] == build_id else None
    except Exception:  # noqa: BLE001  (no store synced, unreadable pointer, ...)
        return None


def _reset_for_tests() -> None:
    with _lock:
        _index.update(build_id=None, axes=None)
        _building.clear()
