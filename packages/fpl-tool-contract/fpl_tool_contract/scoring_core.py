"""Cross-layer captain-scoring input primitives.

Single source of truth for the *base* scoring-input derivation shared across
package layers. It lives in ``fpl-tool-contract`` because that is the lowest
layer every consumer can import: ``tools.py`` here, and the grounded-assistant
consumers (``comparison``, ``transfer_advisor``, ``differential_picks``,
``chip_advisor``) which sit above it.

Scope is deliberately the *base* four values only — ``form``, ``xgi_per_90``
(raw), ``minutes_risk``, ``fixture_difficulty``. The home/away venue adjustment
(``is_home``/``effective_fdr``) and the minutes-shrunk rate
(``xgi_per_90_shrunk``) are grounded-assistant concerns — the latter depends on
``position_score.shrink_rate_by_minutes``, which is a higher layer — so they are
composed on top of this base in ``fpl_grounded_assistant.scoring_shared``.

This module imports only stdlib/typing, so nothing below it can cycle back.
"""
from __future__ import annotations

from typing import Any, Mapping

# Minutes-risk table: maps FPL ``status`` codes to a 0–100 risk score.
#   a = available, d = doubtful, i = injured, s = suspended, u = unavailable.
_STATUS_RISK: dict[str, float] = {
    "a": 0.0,
    "d": 30.0,
    "i": 100.0,
    "s": 100.0,
    "u": 100.0,
}

#: Neutral fixture difficulty used when the team's FDR is unknown *or* the FPL
#: API ships it present-but-null (season launch: fixtures exist before their
#: difficulty ratings are populated).
NEUTRAL_FDR: int = 3


def _derive_base_scoring_inputs(
    element: dict[str, Any],
    fdr_map: Mapping[int, int | None],
) -> dict[str, Any]:
    """Derive the base captain-scoring inputs from a raw FPL bootstrap element.

    Returns a dict with keys ``form`` (float), ``xgi_per_90`` (float, raw),
    ``minutes_risk`` (float), ``fixture_difficulty`` (int).

    ``fdr_map`` values may be ``None``: the FPL ``fixture_difficulty_map`` ships
    a present-but-null value per team at season launch, so a plain
    ``.get(team_id, default)`` does **not** fire the default — it returns
    ``None`` and ``int(None)`` raises. Both a missing key and a null value fall
    back to :data:`NEUTRAL_FDR`.
    """
    form = float(element.get("form", "0") or 0)

    minutes = float(element.get("minutes", 0) or 0)
    xgi_raw = float(element.get("expected_goal_involvements", "0") or 0)
    xgi_per_90 = (xgi_raw / (minutes / 90.0)) if minutes > 0 else 0.0

    status = element.get("status", "u")
    chance = element.get("chance_of_playing_this_round")
    if chance is not None and status == "d":
        minutes_risk = max(0.0, min(100.0, (1.0 - chance / 100.0) * 100.0))
    else:
        minutes_risk = _STATUS_RISK.get(status, 50.0)

    team_id = element.get("team")
    _raw_fdr = fdr_map.get(team_id)
    fixture_difficulty = int(_raw_fdr) if _raw_fdr is not None else NEUTRAL_FDR

    return {
        "form":               form,
        "xgi_per_90":         round(xgi_per_90, 6),
        "minutes_risk":       minutes_risk,
        "fixture_difficulty": fixture_difficulty,
    }
