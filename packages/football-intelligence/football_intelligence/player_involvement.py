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
* **Unknown is not zero.** The ingestion writes a count as empty when the provider's name for it was not known yet
  (absent = zero only holds for a known type). Here an empty count stays ``None`` per match, and a per-90 figure,
  accuracy or share that would need it is ``None`` (no data), never computed as if it were 0.
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


def _opt(value: Any) -> int | None:
    """A stored count, or None when it is unknown (empty in the store): never read as zero."""
    return None if value is None or pd.isna(value) else int(value)


def _pct(part: int | None, whole: int | None) -> float | None:
    return round(100.0 * part / whole, 1) if part is not None and whole else None


def _per90(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Pooled figures over the rows with enough minutes: totals divided by minutes, accuracy and backward share."""
    used = [r for r in rows if _int(r["minutes"]) >= MIN_MINUTES]
    minutes = sum(_int(r["minutes"]) for r in used)
    # a column unknown in any pooled match has no pooled total: a partial sum would read as fewer actions
    total = {c: (None if any(_opt(r[c]) is None for r in used) else sum(_int(r[c]) for r in used)) for c in _COUNTS}
    scale = 90.0 / minutes if minutes else None
    out: dict[str, Any] = {"matches": len(used), "minutes": minutes}
    for column in ("touches", "passes", "key_passes", "backward_passes"):
        out[f"{column}_per90"] = round(total[column] * scale, 1) if scale and total[column] is not None else None
    out["pass_accuracy_pct"] = _pct(total["accurate_passes"], total["passes"])
    out["backward_share_pct"] = _pct(total["backward_passes"], total["passes"])
    return out


def _person(element: int, names: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    info = names.get(element, {})
    return {"player_id": element, "web_name": info.get("web_name"), "team_short": info.get("team_short")}


def _match(row: Mapping[str, Any], meta: FixtureMeta) -> dict[str, Any]:
    passes, back, accurate = _opt(row["passes"]), _opt(row["backward_passes"]), _opt(row["accurate_passes"])
    team = str(row["team"])
    return {
        "gameweek": meta.gameweek, "opponent": meta.away if team == meta.home else meta.home, "is_home": team == meta.home,
        "started": bool(row["starter"]), "minutes": _int(row["minutes"]), "touches": _opt(row["touches"]),
        "passes": passes, "accurate_passes": accurate, "pass_accuracy_pct": _pct(accurate, passes),
        "key_passes": _opt(row["key_passes"]), "backward_passes": back, "backward_share_pct": _pct(back, passes),
        "passes_final_third": _opt(row["passes_final_third"]), "claim_status": OBSERVED,
    }


def _shown(own: pd.DataFrame, fixtures: Mapping[int, FixtureMeta], limit: int) -> pd.DataFrame:
    """The player's latest ``limit`` matches, latest first (by kickoff, then fixture id)."""
    own = own.assign(_k=[(fixtures[int(f)].kickoff or "", int(f)) for f in own.fixture_id]).sort_values("_k", ascending=False)
    return own.head(limit)


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
    shown = _shown(own, fixtures, limit)
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


# ---------------------------------------------------------------------------------------------------------------------
# Two players side by side ("compara los toques de Palmer y Saka"). Same store, same windows, nothing new is measured:
# the per-90 figures are the two ``averages`` blocks, the series are the listed match totals, and the trend is a plain
# least-squares slope over them. Observed values only; the comparison names no cause and predicts nothing.
# ---------------------------------------------------------------------------------------------------------------------

#: The per-90 rows of a comparison, in display order: (metric, field in ``averages``, has a winner).
#: The backward share is neither better nor worse, so it never has one.
COMPARE_METRICS = (
    ("touches", "touches_per90", True),
    ("key_passes", "key_passes_per90", True),
    ("passes", "passes_per90", True),
    ("pass_accuracy", "pass_accuracy_pct", True),
    ("backward_share", "backward_share_pct", False),
)
#: The per-match series a comparison carries (match totals, as listed).
SERIES_METRICS = ("touches", "key_passes", "passes")
#: A trend needs at least this many known values.
TREND_MIN_POINTS = 3
#: The least-squares slope must move at least this share of the mean per match to read as up or down.
TREND_THRESHOLD = 0.03


def trend(values: list[int | float | None]) -> str | None:
    """``up`` / ``down`` / ``flat`` from the least-squares slope over the known values, relative to their mean per step
    of the axis; ``None`` with fewer than ``TREND_MIN_POINTS`` known values. Each value sits at its position on the axis
    (a gap keeps its place, so the fit is the line the card draws); unknown values (``None``) are skipped, never 0."""
    known = [(float(i), float(v)) for i, v in enumerate(values) if v is not None]
    if len(known) < TREND_MIN_POINTS:
        return None
    n = len(known)
    xm, ym = sum(x for x, _ in known) / n, sum(v for _, v in known) / n
    if ym == 0:
        return "flat"
    slope = sum((x - xm) * (v - ym) for x, v in known) / sum((x - xm) ** 2 for x, _ in known)
    ratio = slope / ym
    return "up" if ratio >= TREND_THRESHOLD else "down" if ratio <= -TREND_THRESHOLD else "flat"


def _winner(a: float | None, b: float | None) -> str | None:
    """``a`` / ``b`` / ``None``: compared at the shown precision (one decimal), so a tie on screen is a tie here."""
    if a is None or b is None:
        return None
    ra, rb = round(a, 1), round(b, 1)
    return "a" if ra > rb else "b" if rb > ra else None


def _series(a_matches: list[Mapping[str, Any]], b_matches: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Both players' listed matches on one gameweek axis, oldest first. A gameweek one of them did not play is a gap
    (``None``), as is an unknown value; a double gameweek is two entries with the same label, never averaged."""
    def by_gw(matches):
        out: dict[Any, list[Mapping[str, Any]]] = {}
        for m in reversed(matches):                       # listed latest first; the axis runs oldest first
            out.setdefault(m.get("gameweek"), []).append(m)
        return out

    a_gw, b_gw = by_gw(a_matches), by_gw(b_matches)
    order = sorted(set(a_gw) | set(b_gw), key=lambda g: (g is None, g if g is not None else 0))
    labels: list[Any] = []
    side: dict[str, dict[str, list[Any]]] = {s: {k: [] for k in (*SERIES_METRICS, "minutes")} for s in ("a", "b")}
    for gw in order:
        for i in range(max(len(a_gw.get(gw, ())), len(b_gw.get(gw, ())))):
            labels.append(gw)
            for s, rows in (("a", a_gw.get(gw, ())), ("b", b_gw.get(gw, ()))):
                m = rows[i] if i < len(rows) else None
                for k in (*SERIES_METRICS, "minutes"):
                    side[s][k].append(None if m is None else m.get(k))
    return {"gameweeks": labels, "a": side["a"], "b": side["b"]}


def compare(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    """The side-by-side block from two ``analyse`` answers (both ``ok``). Pure; reads only their output."""
    avg_a, avg_b = a.get("averages") or {}, b.get("averages") or {}
    per90 = []
    for metric, field, has_winner in COMPARE_METRICS:
        va, vb = avg_a.get(field), avg_b.get(field)
        per90.append({"metric": metric, "a": va, "b": vb, "winner": _winner(va, vb) if has_winner else None})
    series = _series(a.get("matches") or [], b.get("matches") or [])
    trends = {s: {k: trend([v for v in series[s][k]]) for k in SERIES_METRICS} for s in ("a", "b")}

    def sample(r):
        s = r.get("sample") or {}
        return {"matches_with_stats": s.get("matches_with_stats"), "listed": s.get("listed"),
                "per90_matches": (r.get("averages") or {}).get("matches"), "small_sample": bool(s.get("small_sample"))}

    return {"players": {"a": a.get("player"), "b": b.get("player")}, "per90": per90, "series": series,
            "trends": trends, "sample": {"a": sample(a), "b": sample(b)}, "claim_status": OBSERVED}
