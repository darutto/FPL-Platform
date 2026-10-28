"""R6: how involved a player was in the match (touches, passes, backward passes), from the licensed store. Pure.

Input is the ``player_match_stats`` table: per player and finished match, the provider's totals. It says HOW MUCH the
player did, never WHERE or WHEN: no zones, no heat maps, no minutes of the action, no progressive or forward-pass
counts (the provider has none). The backward-pass share is "backward passes / passes", a share of the totals.

Claims, each marked with ``claim_status``:

* ``observed``    a fact of the stored match: the player had N touches and made M passes.
* ``associated``  two observed facts that coincide: the player's per-90 touches in the matches where a named teammate
                  did not play versus those where the teammate started. Coinciding is all it says; it names no cause.

What this module does not do: say why (no "because of the injury"), predict, or compare unlike things.

* **Per 90, not per match.** Different minutes make raw totals incomparable, so the comparison pools the matches in
  which the player played at least ``MIN_MINUTES`` and divides by the minutes.
* **Teammate sides.** "Without" = the teammate has no row in a match the store holds for the club (the table keeps only
  players with minutes); "with" = he started. A substitute appearance is neither and is counted apart (``mixed``). The
  store drops players the identity crosswalk could not map, so a match whose club has fewer than 11 stored starters is
  ``uncertain`` and sits in neither side: an unmapped starter must not read as an absence.
* **Small samples are said**: fewer than ``SMALL_SAMPLE_BELOW`` matches overall, fewer than ``SMALL_SIDE_BELOW`` on a side.

Identity: everything joins on the FPL element id and the club code stored on the row of the match. No name is matched
here; names are only attached afterwards for display.
"""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from .position_changes import DEFAULT_LIMIT, MAX_LIMIT, FixtureMeta  # noqa: F401  (re-exported for the adapter)

OBSERVED = "observed"
ASSOCIATED = "associated"
SMALL_SAMPLE_BELOW = 5
SMALL_SIDE_BELOW = 3
#: A match counts towards a per-90 figure only if the player had at least this many minutes in it.
MIN_MINUTES = 30
#: Per-90 touches within this relative difference read as "similar", not more or fewer.
SIMILAR_WITHIN = 0.10
STARTERS = 11
_COUNTS = ("touches", "passes", "accurate_passes", "key_passes", "backward_passes", "passes_final_third")


def _latest(stats: pd.DataFrame) -> pd.DataFrame:
    """One row per (element, fixture): the latest observation (a correction replaces the first read)."""
    ordered = stats.sort_values("observed_at", kind="stable")
    return ordered.drop_duplicates(subset=["element", "fixture_id"], keep="last")


def _int(value: Any) -> int:
    return 0 if value is None or pd.isna(value) else int(value)


def _pct(part: int, whole: int) -> float | None:
    return round(100.0 * part / whole, 1) if whole > 0 else None


def _per90(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Pooled figures over the rows with enough minutes: totals divided by minutes, accuracy and backward share."""
    used = [r for r in rows if _int(r["minutes"]) >= MIN_MINUTES]
    minutes = sum(_int(r["minutes"]) for r in used)
    total = {c: sum(_int(r[c]) for r in used) for c in _COUNTS}
    scale = 90.0 / minutes if minutes else None
    out: dict[str, Any] = {"matches": len(used), "minutes": minutes}
    for column in ("touches", "passes", "key_passes", "backward_passes"):
        out[f"{column}_per90"] = round(total[column] * scale, 1) if scale else None
    out["pass_accuracy_pct"] = _pct(total["accurate_passes"], total["passes"])
    out["backward_share_pct"] = _pct(total["backward_passes"], total["passes"])
    return out


def _person(element: int, names: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    info = names.get(element, {})
    return {"player_id": element, "web_name": info.get("web_name"), "team_short": info.get("team_short")}


def _match(row: Mapping[str, Any], meta: FixtureMeta) -> dict[str, Any]:
    passes, back = _int(row["passes"]), _int(row["backward_passes"])
    team = str(row["team"])
    return {
        "gameweek": meta.gameweek, "opponent": meta.away if team == meta.home else meta.home, "is_home": team == meta.home,
        "started": bool(row["starter"]), "minutes": _int(row["minutes"]), "touches": _int(row["touches"]),
        "passes": passes, "accurate_passes": _int(row["accurate_passes"]), "pass_accuracy_pct": _pct(_int(row["accurate_passes"]), passes),
        "key_passes": _int(row["key_passes"]), "backward_passes": back, "backward_share_pct": _pct(back, passes),
        "passes_final_third": _int(row["passes_final_third"]), "claim_status": OBSERVED,
    }


def _direction(without: float | None, with_him: float | None) -> str | None:
    if without is None or with_him is None or with_him == 0:
        return None
    ratio = without / with_him
    return "more" if ratio > 1 + SIMILAR_WITHIN else "fewer" if ratio < 1 - SIMILAR_WITHIN else "similar"


def _focus(own: pd.DataFrame, everyone: pd.DataFrame, absent: int, names: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    """The player's per-90 involvement in matches without the teammate versus with him starting."""
    seen = everyone[everyone.element == absent]
    sides: dict[str, list[Mapping[str, Any]]] = {"without": [], "with": []}
    counts = {"mixed": 0, "uncertain": 0}
    for row in own.to_dict("records"):
        team_rows = everyone[(everyone.fixture_id == row["fixture_id"]) & (everyone.team == row["team"])]
        if int(team_rows.starter.astype(bool).sum()) < STARTERS:
            counts["uncertain"] += 1
            continue
        mate = team_rows[team_rows.element == absent]
        if mate.empty:
            sides["without"].append(row)
        elif bool(mate.iloc[0]["starter"]):
            sides["with"].append(row)
        else:
            counts["mixed"] += 1
    without, with_him = _per90(sides["without"]), _per90(sides["with"])
    return {
        "teammate": _person(absent, names), "claim_status": ASSOCIATED,
        "teammate_in_store": not seen.empty,
        "without_him": without, "with_him_starting": with_him,
        "matches_mixed": counts["mixed"], "matches_uncertain": counts["uncertain"],
        "touches_without_vs_with": _direction(without["touches_per90"], with_him["touches_per90"]),
        "small_sample": without["matches"] < SMALL_SIDE_BELOW or with_him["matches"] < SMALL_SIDE_BELOW,
    }


def analyse(
    *,
    element: int,
    stats: pd.DataFrame,
    fixtures: Mapping[int, FixtureMeta],
    names: Mapping[int, Mapping[str, Any]],
    limit: int = DEFAULT_LIMIT,
    absent_element: int | None = None,
) -> dict[str, Any]:
    limit = max(1, min(int(limit), MAX_LIMIT))
    latest = _latest(stats) if len(stats) else stats
    latest = latest[latest.fixture_id.isin(list(fixtures))] if len(latest) else latest
    own = latest[latest.element == element] if len(latest) else latest
    if own.empty:
        return {"status": "missing_context", "reason_codes": ["no_player_stats"], "matches": [], "evidence": [],
                "player": _person(element, names)}
    own = own.assign(_k=[(fixtures[int(f)].kickoff or "", int(f)) for f in own.fixture_id]).sort_values("_k", ascending=False)
    shown = own.head(limit)
    matches = [_match(r, fixtures[int(r["fixture_id"])]) for r in shown.to_dict("records")]
    result: dict[str, Any] = {
        "status": "ok", "player": _person(element, names), "matches": matches,
        "averages": {**_per90(shown.to_dict("records")), "claim_status": OBSERVED},
        "sample": {"matches_with_stats": len(own), "listed": len(matches), "small_sample": len(own) < SMALL_SAMPLE_BELOW},
        "evidence": [],
    }
    if absent_element is not None:
        result["absence_focus"] = _focus(own, latest, absent_element, names)
    return result
