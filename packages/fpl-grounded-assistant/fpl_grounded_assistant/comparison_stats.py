"""
comparison_stats.py
====================
Additive, deterministic raw-stat comparison table for compare_players.

Renders BELOW the existing winner/margin/reasons verdict in ComparisonCard;
never alters winner/margin computation. Row selection is position-conditional
(v1 design — see ROW SET NOTE below); values and the per-row "better" flag are
computed here from real numeric values, never left to client-side string
parsing.

Grounding invariant (non-negotiable, mirrors generic_card.py's own language):
every StatRow value here is read directly from the deterministic bootstrap
element dict compare_players() already has access to. No value ever comes
from LLM-generated text. llm_review.py is not imported by, and does not gate,
anything in this module.

Tool-output boundary
---------------------
compare_players() (comparison.py) is a *tool* whose entire return value
becomes the raw_output dict flowing through the dispatcher/routing layer
(potentially logged / dumped as debug info) before final_response.py ever
sees it. build_stat_comparison() therefore returns a PLAIN, JSON-safe dict —
never the StatComparisonMeta dataclass — consistent with every other field in
that raw_output. final_response.py reconstructs the typed dataclass via
stat_comparison_from_dict(), mirroring how _extract_comparison_player_ctx
already turns a plain player_a/player_b dict into a ComparisonPlayerContext.

ROW SET NOTE (v1, not final):
The position -> stat-row relevance mapping below is a first-pass design
choice, analogous to position_score.py's own POSITION_PROFILES weight table:
informed by, but not mechanically derived from, those weights (e.g. GKP/DEF
surface clean_sheets_per_90 because it is non-zero-weighted there; DEF does
NOT surface dc_per_90 because project memory has established it is not a
proven DEF signal). Treat this row set as open to recalibration, not a
settled taxonomy.

xGI/90 note: deliberately self-derived using the SAME formula
comparison.py's _derive_scoring_inputs uses (expected_goal_involvements /
(minutes / 90)), NOT the bootstrap's enriched expected_goal_involvements_per_90
field — so the table's number can never subtly disagree with whatever the
verdict/reasons pipeline already says about xGI. saves_per_90/
clean_sheets_per_90, by contrast, prefer the enriched bootstrap field (with a
derivation fallback) since the verdict pipeline itself already reads those
same enriched fields directly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

BetterSide = Literal["a", "b"]
RowKind = Literal["performance", "context"]

_GKP = "GKP"


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlayerStatSource:
    """Narrow, typed input to build_stat_comparison — decoupled from the full
    comparison output shape. comparison.py's compare_players() builds this
    itself, directly from a bootstrap element it fetches independently,
    rather than extending _score_one()'s return dict (which _explain_comparison
    already destructures by specific key set).

    None means genuinely absent; 0 is a real recorded value — the two must
    never be conflated.
    """
    position: str
    form: "float | None"
    total_points: "int | None"
    price_m: "float | None"
    ownership_percent: "float | None"
    goals: "int | None"
    assists: "int | None"
    xgi_per_90: "float | None"
    saves_per_90: "float | None"
    clean_sheets_per_90: "float | None"


@dataclass(frozen=True)
class StatCell:
    value: "float | int | None"
    display: str


@dataclass(frozen=True)
class StatRow:
    key: str
    label: str
    kind: RowKind
    value_a: StatCell
    value_b: StatCell
    better: "BetterSide | None"


@dataclass(frozen=True)
class StatComparisonMeta:
    rows: "tuple[StatRow, ...]"


# ---------------------------------------------------------------------------
# Numeric coercion — shared helper, metric-specific validation
# ---------------------------------------------------------------------------

def _finite_number(value: Any, *, allow_negative: bool) -> "float | None":
    """Best-effort numeric coercion that never raises.

    Accepts int, float, or numeric string (FPL's API returns some numeric
    fields — selected_by_percent, form — as strings). Rejects bool explicitly
    (isinstance(True, int) is True in Python — a real gotcha). Rejects
    NaN/inf. Rejects negative values unless allow_negative=True.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
    elif isinstance(value, str):
        try:
            num = float(value.strip())
        except (TypeError, ValueError):
            return None
    else:
        return None
    if not math.isfinite(num):
        return None
    if not allow_negative and num < 0:
        return None
    return num


def _finite_int(value: Any, *, allow_negative: bool) -> "int | None":
    num = _finite_number(value, allow_negative=allow_negative)
    if num is None:
        return None
    return int(round(num))


def _per_90(total: Any, minutes: Any) -> "float | None":
    """Derive a per-90 rate from a cumulative total and minutes played.
    None when either input is invalid or minutes <= 0 — never raises,
    never divides by zero."""
    total_v = _finite_number(total, allow_negative=False)
    minutes_v = _finite_number(minutes, allow_negative=False)
    if total_v is None or minutes_v is None or minutes_v <= 0:
        return None
    return total_v * 90.0 / minutes_v


# ---------------------------------------------------------------------------
# PlayerStatSource construction — called by comparison.py, from a bootstrap
# element it fetches independently (not via _score_one()'s return dict).
# ---------------------------------------------------------------------------

def build_player_stat_source(
    element: "dict[str, Any]",
    position: str,
) -> PlayerStatSource:
    """Build a PlayerStatSource from a raw bootstrap element dict.

    Reads every field fresh via element.get(key) — deliberately NOT reusing
    any already-computed score_inputs dict, which may already collapse
    missing-vs-zero for other purposes. Never raises.
    """
    now_cost = _finite_number(element.get("now_cost"), allow_negative=False)
    price_m = round(now_cost / 10.0, 1) if now_cost is not None else None

    minutes = element.get("minutes")

    xgi_raw = element.get("expected_goal_involvements")
    # Deliberately the SAME formula _derive_scoring_inputs uses — see module
    # docstring "xGI/90 note" for why this is not the enriched per-90 field.
    xgi_per_90 = _per_90(xgi_raw, minutes)

    saves_per_90 = _finite_number(element.get("saves_per_90"), allow_negative=False)
    if saves_per_90 is None:
        saves_per_90 = _per_90(element.get("saves"), minutes)

    clean_sheets_per_90 = _finite_number(element.get("clean_sheets_per_90"), allow_negative=False)
    if clean_sheets_per_90 is None:
        clean_sheets_per_90 = _per_90(element.get("clean_sheets"), minutes)

    return PlayerStatSource(
        position=str(position or "").strip().upper(),
        form=_finite_number(element.get("form"), allow_negative=True),
        total_points=_finite_int(element.get("total_points"), allow_negative=True),
        price_m=price_m,
        ownership_percent=_finite_number(element.get("selected_by_percent"), allow_negative=False),
        goals=_finite_int(element.get("goals_scored"), allow_negative=False),
        assists=_finite_int(element.get("assists"), allow_negative=False),
        xgi_per_90=xgi_per_90,
        saves_per_90=saves_per_90,
        clean_sheets_per_90=clean_sheets_per_90,
    )


# ---------------------------------------------------------------------------
# Row registry — key, label, kind, relevance predicate
# ---------------------------------------------------------------------------

def _is_gkp(position: str) -> bool:
    return position == _GKP


def _is_outfield(position: str) -> bool:
    return position in ("DEF", "MID", "FWD")


# Each entry: (key, label, kind, relevant(pos_a, pos_b) -> bool)
_ROW_REGISTRY: "tuple[tuple[str, str, RowKind, Any], ...]" = (
    ("form", "Forma", "performance", lambda a, b: True),
    ("total_points", "Puntos totales", "performance", lambda a, b: True),
    ("price_m", "Precio", "context", lambda a, b: True),
    ("ownership_percent", "Propiedad %", "context", lambda a, b: True),
    ("goals", "Goles", "performance", lambda a, b: _is_outfield(a) or _is_outfield(b)),
    ("assists", "Asistencias", "performance", lambda a, b: _is_outfield(a) or _is_outfield(b)),
    ("xgi_per_90", "xGI/90", "performance", lambda a, b: _is_outfield(a) or _is_outfield(b)),
    ("saves_per_90", "Atajadas/90", "performance", lambda a, b: _is_gkp(a) or _is_gkp(b)),
    ("clean_sheets_per_90", "Vallas invictas/90", "performance",
     lambda a, b: _is_gkp(a) or _is_gkp(b) or a == "DEF" or b == "DEF"),
)

_FORMATTERS: "dict[str, Any]" = {
    "price_m": lambda v: f"£{v:.1f}m",
    "ownership_percent": lambda v: f"{v:.1f}%",
    "form": lambda v: f"{v:.1f}",
    "saves_per_90": lambda v: f"{v:.2f}",
    "clean_sheets_per_90": lambda v: f"{v:.2f}",
    "xgi_per_90": lambda v: f"{v:.2f}",
    "total_points": lambda v: str(int(v)),
    "goals": lambda v: str(int(v)),
    "assists": lambda v: str(int(v)),
}


def _format(key: str, value: "float | int | None") -> str:
    if value is None:
        return "—"
    return _FORMATTERS[key](value)


def _make_cell(key: str, value: "float | int | None") -> StatCell:
    return StatCell(value=value, display=_format(key, value))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_stat_comparison(a: PlayerStatSource, b: PlayerStatSource) -> "dict[str, Any] | None":
    """Build the position-conditional stat table from two PlayerStatSource
    instances. Returns a PLAIN JSON-safe dict (see module docstring — tool-
    output boundary), or None if zero rows remain after the omission rules.
    Never raises.
    """
    # "Fundamentally mixed" pairing: exactly one player is a GKP — highlight
    # is suppressed on every non-universal (performance, position-specific)
    # row, though real values are still shown on both sides.
    mixed_pairing = _is_gkp(a.position) != _is_gkp(b.position)

    rows: "list[dict[str, Any]]" = []
    for key, label, kind, relevant in _ROW_REGISTRY:
        is_universal_row = key in ("form", "total_points", "price_m", "ownership_percent")
        if not is_universal_row and not relevant(a.position, b.position):
            continue

        value_a = getattr(a, key)
        value_b = getattr(b, key)

        if value_a is None and value_b is None:
            continue  # both missing -> omit the row entirely

        cell_a = _make_cell(key, value_a)
        cell_b = _make_cell(key, value_b)

        better: "BetterSide | None" = None
        if kind == "performance" and value_a is not None and value_b is not None:
            if not is_universal_row and mixed_pairing:
                better = None
            elif cell_a.display != cell_b.display:
                # Only compare/highlight when the two DISPLAYED values differ —
                # a highlight must be visually justified by what the user sees.
                if value_a > value_b:
                    better = "a"
                elif value_b > value_a:
                    better = "b"

        rows.append({
            "key": key,
            "label": label,
            "kind": kind,
            "value_a": {"value": cell_a.value, "display": cell_a.display},
            "value_b": {"value": cell_b.value, "display": cell_b.display},
            "better": better,
        })

    if not rows:
        return None
    return {"rows": rows}


def stat_comparison_from_dict(d: "dict[str, Any] | None") -> "StatComparisonMeta | None":
    """Reconstruct the typed dataclass from build_stat_comparison's plain-dict
    output. Called from final_response.py's _extract_comparison_meta.

    Per-row (not all-or-nothing) validation:
      - A row missing/malformed on key, label, value_a, or value_b is
        REJECTED — dropped, not defaulted.
      - better not exactly "a"/"b" -> coerced to None.
      - kind not exactly "performance"/"context" -> coerced to "context" AND
        better is force-set to None for that row (never default an invalid
        kind to "performance" — that could let an unjustified highlight
        through on data we don't trust).
      - If zero valid rows remain, returns None.
    Never raises.
    """
    if not isinstance(d, dict):
        return None
    raw_rows = d.get("rows")
    if not isinstance(raw_rows, list):
        return None

    rows: "list[StatRow]" = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        key = raw.get("key")
        label = raw.get("label")
        value_a_raw = raw.get("value_a")
        value_b_raw = raw.get("value_b")
        if (
            not isinstance(key, str) or not key
            or not isinstance(label, str) or not label
            or not isinstance(value_a_raw, dict)
            or not isinstance(value_b_raw, dict)
        ):
            continue

        kind = raw.get("kind")
        better = raw.get("better")
        if kind not in ("performance", "context"):
            kind = "context"
            better = None
        if better not in ("a", "b"):
            better = None

        try:
            value_a = StatCell(
                value=value_a_raw.get("value"),
                display=str(value_a_raw.get("display", "—")),
            )
            value_b = StatCell(
                value=value_b_raw.get("value"),
                display=str(value_b_raw.get("display", "—")),
            )
        except Exception:  # noqa: BLE001 — defensive, never let one bad row crash the whole table
            continue

        rows.append(StatRow(
            key=key,
            label=label,
            kind=kind,  # type: ignore[arg-type]
            value_a=value_a,
            value_b=value_b,
            better=better,  # type: ignore[arg-type]
        ))

    if not rows:
        return None
    return StatComparisonMeta(rows=tuple(rows))
