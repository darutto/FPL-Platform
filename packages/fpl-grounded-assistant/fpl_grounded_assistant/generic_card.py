"""
generic_card.py
===============
Additive, renderable ``generic_card`` structured payload (Track A).

Some supported intents answer today only as plain text.  This module composes
a **deterministic, renderable card payload** (``GenericCardMeta``) for a
curated subset of those intents so a UI can render a consistent card instead of
parsing free text.

Grounding invariant (non-negotiable)
------------------------------------
Every ``GenericCardMeta`` here is composed **only** from already-built
deterministic metadata (the frozen ``*Meta`` dataclasses produced by
``final_response._extract_structured_meta``) or the raw deterministic tool
output for intents that have no metadata dataclass (``current_gameweek``).
No value ever comes from LLM-generated text.  The ``llm_review`` parity gate is
never touched by this module.

Spanish-first
-------------
All titles / labels are Spanish micro-labels.  No buy/sell imperatives appear
anywhere; FDR is surfaced as neutral difficulty text (colours are UI-side).

Schema (as implemented — the UI builds against this)
----------------------------------------------------
``GenericCardMeta``
    accent   : str   — one of turquoise|cyan|coral|gold|purple|gray
    title    : str   — uppercase micro-label
    subtitle : str | None
    hero     : HeroStat | None
    pills    : tuple[Pill, ...]
    columns  : tuple[Column, ...]
    rows     : tuple[tuple[str, ...], ...]   — each row len == len(columns)
    footer   : str | None

``HeroStat``  {value: str, label: str, tone: str | None}
``Pill``      {label: str, tone: good|warn|bad|neutral}
``Column``    {header: str, align: left|right, kind: text|mono|badge}
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — type hints only; avoids a runtime import cycle
    from .final_response import (
        PlayerFormMeta,
        PriceChangesMeta,
        TeamFixtureCalendarMeta,
        TeamScheduleMeta,
        PositionFixtureRunMeta,
    )

# ---------------------------------------------------------------------------
# Accent / tone / kind vocabularies (documented constants; not enforced at
# runtime so composition never raises — the UI treats unknown values as gray).
# ---------------------------------------------------------------------------

ACCENTS: tuple[str, ...] = ("turquoise", "cyan", "coral", "gold", "purple", "gray")
PILL_TONES: tuple[str, ...] = ("good", "warn", "bad", "neutral")
COLUMN_ALIGNS: tuple[str, ...] = ("left", "right")
COLUMN_KINDS: tuple[str, ...] = ("text", "mono", "badge")


# ---------------------------------------------------------------------------
# Frozen payload dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HeroStat:
    """A single prominent stat rendered at the top of a card."""
    value: str
    label: str
    tone:  "str | None" = field(default=None)


@dataclass(frozen=True)
class Pill:
    """A small labelled chip.  ``tone`` is one of good|warn|bad|neutral."""
    label: str
    tone:  str = field(default="neutral")


@dataclass(frozen=True)
class Column:
    """A table column header.

    ``align`` is one of left|right.  ``kind`` is one of text|mono|badge and
    tells the UI how to render the cells in this column.
    """
    header: str
    align:  str = field(default="left")
    kind:   str = field(default="text")


@dataclass(frozen=True)
class GenericCardMeta:
    """A deterministic, renderable card payload.

    Composed only from already-built deterministic metadata — never from LLM
    text.  ``rows`` is a tuple of tuples of cell strings; every row has exactly
    ``len(columns)`` cells.
    """
    accent:   str
    title:    str
    subtitle: "str | None"
    hero:     "HeroStat | None"
    pills:    tuple[Pill, ...]
    columns:  tuple[Column, ...]
    rows:     tuple[tuple[str, ...], ...]
    footer:   "str | None" = field(default=None)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

#: Spanish, neutral FDR difficulty labels keyed by rounded FDR band (1..5).
#: Descriptive only — no colour, no imperative.  Colours are applied UI-side.
_FDR_LABELS_ES: dict[int, str] = {
    1: "Muy favorable",
    2: "Favorable",
    3: "Media",
    4: "Exigente",
    5: "Muy exigente",
}


def _fdr_label_es(value: "float | int | None") -> str:
    """Map an FDR value (int rating or float average) to a Spanish text label."""
    if value is None:
        return "-"
    try:
        band = int(round(float(value)))
    except (TypeError, ValueError):
        return "-"
    band = max(1, min(5, band))
    return _FDR_LABELS_ES[band]


def _venue_label_es(is_home: bool) -> str:
    """Spanish home/away label."""
    return "Casa" if is_home else "Fuera"


# ---------------------------------------------------------------------------
# Per-intent composers.  Each is pure and takes an already-built metadata
# dataclass (duck-typed) and returns a GenericCardMeta.
# ---------------------------------------------------------------------------

def compose_player_form(meta: "PlayerFormMeta") -> GenericCardMeta:
    """Compose a FORMA RECIENTE card.

    hero = total points over the window; one mono per-gameweek row.
    """
    history = tuple(meta.history)
    total_points = sum(int(e.total_points) for e in history)
    total_goals  = sum(int(e.goals_scored) for e in history)
    total_assists = sum(int(e.assists) for e in history)

    subtitle = " · ".join(
        p for p in (meta.web_name, meta.team_short, meta.position) if p
    ) or None

    hero = HeroStat(
        value=str(total_points),
        label=f"PUNTOS · {meta.n_games} JOR",
        tone="good" if total_points > 0 else "neutral",
    )

    pills = (
        Pill(label=f"{total_goals} G", tone="good" if total_goals else "neutral"),
        Pill(label=f"{total_assists} A", tone="good" if total_assists else "neutral"),
    )

    columns = (
        Column(header="JOR", align="left",  kind="text"),
        Column(header="MIN", align="right", kind="mono"),
        Column(header="G",   align="right", kind="mono"),
        Column(header="A",   align="right", kind="mono"),
        Column(header="BON", align="right", kind="mono"),
        Column(header="PTS", align="right", kind="mono"),
    )

    rows = tuple(
        (
            f"GW{int(e.gameweek)}",
            str(int(e.minutes)),
            str(int(e.goals_scored)),
            str(int(e.assists)),
            str(int(e.bonus)),
            str(int(e.total_points)),
        )
        for e in history
    )

    return GenericCardMeta(
        accent="turquoise",
        title="FORMA RECIENTE",
        subtitle=subtitle,
        hero=hero,
        pills=pills,
        columns=columns,
        rows=rows,
        footer=None,
    )


def compose_price_changes(meta: "PriceChangesMeta") -> GenericCardMeta:
    """Compose a CAMBIOS DE PRECIO card.

    Risers first then fallers; the CAMBIO column carries a signed delta, and
    riser/faller counts appear as good/bad tone pills.
    """
    risers  = tuple(meta.risers)
    fallers = tuple(meta.fallers)

    pills = (
        Pill(label=f"{len(risers)} SUBEN",  tone="good"),
        Pill(label=f"{len(fallers)} BAJAN", tone="bad"),
    )

    columns = (
        Column(header="JUGADOR", align="left",  kind="text"),
        Column(header="EQUIPO",  align="left",  kind="text"),
        Column(header="PRECIO",  align="right", kind="mono"),
        Column(header="CAMBIO",  align="right", kind="badge"),
    )

    def _row(e: Any) -> tuple[str, ...]:
        delta_tenths = int(e.cost_change_event)
        sign = "+" if delta_tenths > 0 else ("-" if delta_tenths < 0 else "")
        change = f"{sign}£{abs(delta_tenths) / 10:.1f}"
        return (
            e.web_name,
            e.team_short,
            f"£{float(e.now_cost_m):.1f}",
            change,
        )

    rows = tuple(_row(e) for e in (risers + fallers))

    return GenericCardMeta(
        accent="gold",
        title="CAMBIOS DE PRECIO",
        subtitle=None,
        hero=None,
        pills=pills,
        columns=columns,
        rows=rows,
        footer=None,
    )


#: Spanish mode labels for the ranked fixture-calendar intents.
_CALENDAR_MODE_ES: dict[str, str] = {
    "easiest": "Calendario más favorable",
    "hardest": "Calendario más exigente",
}


def _ranked_calendar_rows(teams: tuple[Any, ...]) -> tuple[tuple[str, ...], ...]:
    """Shared row builder for the ranked team-list calendar cards."""
    return tuple(
        (
            str(int(t.rank)),
            t.team_short,
            str(int(t.fixture_count)),
            f"{float(t.avg_fdr):.1f}",
            _fdr_label_es(t.avg_fdr),
        )
        for t in teams
    )


_RANKED_CALENDAR_COLUMNS: tuple[Column, ...] = (
    Column(header="#",          align="left",  kind="text"),
    Column(header="EQUIPO",     align="left",  kind="text"),
    Column(header="PARTIDOS",   align="right", kind="mono"),
    Column(header="FDR MEDIO",  align="right", kind="mono"),
    Column(header="DIFICULTAD", align="left",  kind="badge"),
)


def compose_team_fixture_calendar(meta: "TeamFixtureCalendarMeta") -> GenericCardMeta:
    """Compose a CALENDARIO card ranking teams by fixture difficulty."""
    subtitle = _CALENDAR_MODE_ES.get(meta.mode, None)
    pills = (Pill(label=f"{int(meta.horizon)} JORNADAS", tone="neutral"),)
    return GenericCardMeta(
        accent="cyan",
        title="CALENDARIO",
        subtitle=subtitle,
        hero=None,
        pills=pills,
        columns=_RANKED_CALENDAR_COLUMNS,
        rows=_ranked_calendar_rows(tuple(meta.teams)),
        footer=None,
    )


def compose_position_fixture_run(meta: "PositionFixtureRunMeta") -> GenericCardMeta:
    """Compose a CALENDARIO POR POSICIÓN card (position-filtered team ranking)."""
    mode_es = _CALENDAR_MODE_ES.get(meta.mode, "")
    label   = meta.position_label or meta.position
    subtitle = " · ".join(p for p in (label, mode_es) if p) or None
    pills = (Pill(label=f"{int(meta.horizon)} JORNADAS", tone="neutral"),)
    return GenericCardMeta(
        accent="purple",
        title="CALENDARIO POR POSICIÓN",
        subtitle=subtitle,
        hero=None,
        pills=pills,
        columns=_RANKED_CALENDAR_COLUMNS,
        rows=_ranked_calendar_rows(tuple(meta.teams)),
        footer=None,
    )


def compose_team_schedule(meta: "TeamScheduleMeta") -> GenericCardMeta:
    """Compose a single-team CALENDARIO card.

    hero = average FDR over the horizon; one fixture row per gameweek with the
    FDR surfaced as a neutral difficulty text label.
    """
    subtitle = meta.team_name or meta.team_short or None

    hero = HeroStat(
        value=f"{float(meta.avg_fdr):.1f}",
        label="FDR MEDIO",
        tone=None,
    )

    pills_list: list[Pill] = [
        Pill(label=f"{int(meta.fixture_count)} PARTIDOS", tone="neutral"),
    ]
    if getattr(meta, "has_dgw", False):
        pills_list.append(Pill(label="DOBLE JORNADA", tone="good"))
    if getattr(meta, "has_bgw", False):
        pills_list.append(Pill(label="JORNADA EN BLANCO", tone="warn"))

    columns = (
        Column(header="JOR",   align="left", kind="text"),
        Column(header="RIVAL", align="left", kind="text"),
        Column(header="SEDE",  align="left", kind="badge"),
        Column(header="FDR",   align="left", kind="badge"),
    )

    rows = tuple(
        (
            f"GW{int(fx.gameweek)}",
            fx.opponent_short,
            _venue_label_es(bool(fx.is_home)),
            _fdr_label_es(fx.difficulty),
        )
        for fx in meta.fixtures
    )

    return GenericCardMeta(
        accent="cyan",
        title="CALENDARIO",
        subtitle=subtitle,
        hero=hero,
        pills=tuple(pills_list),
        columns=columns,
        rows=rows,
        footer=None,
    )


def compose_current_gameweek(gameweek: int) -> GenericCardMeta:
    """Compose a JORNADA ACTUAL card.

    hero = the gameweek number.  This intent has no metadata dataclass and its
    deterministic tool output (``{status, gameweek}``) carries no deadline, so
    the deadline footer is intentionally omitted rather than sourced from LLM
    text (see module grounding invariant).
    """
    return GenericCardMeta(
        accent="coral",
        title="JORNADA ACTUAL",
        subtitle=None,
        hero=HeroStat(value=f"GW{int(gameweek)}", label="JORNADA EN CURSO", tone=None),
        pills=(),
        columns=(),
        rows=(),
        footer=None,
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
#
# Intents WITH a composer here (plain-text-today intents that gain a card):
#   player_form, price_changes, team_fixture_calendar, team_schedule,
#   position_fixture_run, current_gameweek
#
# Intents intentionally EXCLUDED (return None):
#   - injury_list          — UI reuses its dedicated injuries table
#   - transfer_suggestion  — bespoke card owned by another track
#   - every intent that already has a bespoke UI card: captain_score,
#     compare_players, rank_candidates, transfer_advice, chip_advice,
#     player_fixture_run, differential_picks, fixture_outlook, zonal_opportunity
# ---------------------------------------------------------------------------

def build_generic_card(
    intent: str,
    meta: "dict[str, Any]",
    raw_output: "dict[str, Any]",
    outcome: str,
) -> "GenericCardMeta | None":
    """Return a ``GenericCardMeta`` for composer-backed intents, else ``None``.

    Parameters
    ----------
    intent:
        The ``INTENT_*`` constant for the turn.
    meta:
        The dict returned by ``_extract_structured_meta`` (already-built
        deterministic metadata dataclasses keyed by ``FinalResponse`` field).
    raw_output:
        The raw deterministic tool output (used only for ``current_gameweek``,
        which has no metadata dataclass).
    outcome:
        The ``OUTCOME_*`` constant.  A card is only composed on ``"ok"``.

    Returns
    -------
    GenericCardMeta | None
        ``None`` for non-ok outcomes, excluded intents, or when the backing
        metadata is missing/malformed.  Never raises.
    """
    if outcome != "ok":
        return None

    try:
        # Deferred import of intent constants — dispatcher never imports this
        # module, so there is no cycle; kept inside the function to keep the
        # module import-light.
        from .dispatcher import (
            INTENT_PLAYER_FORM,
            INTENT_PRICE_CHANGES,
            INTENT_TEAM_FIXTURE_CALENDAR,
            INTENT_TEAM_SCHEDULE,
            INTENT_POSITION_FIXTURE_RUN,
            INTENT_CURRENT_GAMEWEEK,
        )

        if intent == INTENT_PLAYER_FORM:
            m = meta.get("player_form")
            return compose_player_form(m) if m is not None else None
        if intent == INTENT_PRICE_CHANGES:
            m = meta.get("price_changes")
            return compose_price_changes(m) if m is not None else None
        if intent == INTENT_TEAM_FIXTURE_CALENDAR:
            m = meta.get("team_calendar")
            return compose_team_fixture_calendar(m) if m is not None else None
        if intent == INTENT_TEAM_SCHEDULE:
            m = meta.get("team_schedule")
            return compose_team_schedule(m) if m is not None else None
        if intent == INTENT_POSITION_FIXTURE_RUN:
            m = meta.get("position_fixture_run")
            return compose_position_fixture_run(m) if m is not None else None
        if intent == INTENT_CURRENT_GAMEWEEK:
            gw = raw_output.get("gameweek")
            return compose_current_gameweek(int(gw)) if gw is not None else None
    except Exception:  # noqa: BLE001 — composition must never raise into the caller
        return None

    return None


def generic_card_to_dict(card: "GenericCardMeta | None") -> "dict[str, Any] | None":
    """Serialise a ``GenericCardMeta`` to a JSON-safe dict (or ``None``).

    Mirrors the per-meta serializer pattern in ``fpl_server.py``.  ``rows`` is
    emitted as a list of lists of strings; ``hero``/``pills``/``columns`` as
    plain dicts.
    """
    if card is None:
        return None
    return {
        "accent":   card.accent,
        "title":    card.title,
        "subtitle": card.subtitle,
        "hero": (
            None if card.hero is None
            else {
                "value": card.hero.value,
                "label": card.hero.label,
                "tone":  card.hero.tone,
            }
        ),
        "pills": [
            {"label": p.label, "tone": p.tone} for p in card.pills
        ],
        "columns": [
            {"header": c.header, "align": c.align, "kind": c.kind}
            for c in card.columns
        ],
        "rows": [list(r) for r in card.rows],
        "footer": card.footer,
    }
