"""The reading line: what was computed, in plain words, written by code (query layer, Amendment 4 §4.1).

    render_reading(spec, lang, result=None, bootstrap=None, unsupported=()) -> the ``query.reading`` block
    {"parts": [{kind, label, value, editable, alternatives, braked}], "text": str, "lang": "es" | "en"}

The input is the strictly parsed ``QuerySpec`` and, once it has run, the engine's ``QueryResult``; never the
model's text or quotes. Every field that changes the answer is printed, defaults included, so two specs that
ask different things never read the same. Without a result (a selection-only reading) the line is the same
minus what only execution knows: gameweek ranges, resolved names, the minutes floor and the comparison's sets.

An alternative is ``{"label", "spec"}``: the whole typed spec a tap on it sends, nothing to be re-read as text.

All words are in :data:`WORDS` (metric names are the catalogue's). ``text`` carries no "Showing:" prefix:
the surface that writes it as a first line adds ``PREFIX[lang]``.

Nothing imports this module at runtime yet (query layer, PR 4).
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable, Mapping

from fpl_grounded_assistant import query_catalogue as cat
from fpl_grounded_assistant.query_engine import (COMPLETE, DATA_UNAVAILABLE, NEEDS_CLARIFICATION, UNSUPPORTED,
                                                 QueryResult)
from fpl_grounded_assistant.query_spec import (PLAYER_PREDICATES, WINDOW_PREDICATES, Filter, Predicate, QuerySpec,
                                               parse_date, unsupported_reasons)

LANGS = ("es", "en")
SEPARATOR = " · "
BRAKE_MARK = "⚠ "
PREFIX = {"es": "Muestro: ", "en": "Showing: "}

#: What a tap offers. Windows and ownership are Amendment 4 §4.1; price and minutes are steps around the value.
WINDOW_CHOICES = (3, 5, 10)
OWNERSHIP_CHOICES = (5, 10, 15)
PRICE_STEPS = (-1.0, -0.5, 0.5, 1.0)
MINUTES_CHOICES = (90, 180, 270, 450)

WORDS: dict[str, dict[str, Any]] = {
    "es": {
        "teams": "Equipos", "gw": "J", "and_gw": "J", "season": "Temporada", "today": "Hoy",
        "last": "Últimas {n}", "last_one": "Última", "since": "Desde {date}",
        "months": ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"),
        "provisional": "(provisional)",
        "with": "Con {player} ({club}≥ 60′)", "without": "Sin {player} ({club}0′)",
        "without_same": "Sin {player} (0′)", "home": "De local", "away": "De visitante",
        "mixed": "Mixtos fuera: {gws}",
        "club_metric": "{metric} de {club}", "lowest_first": "(menor primero)", "top": "Top {n}",
        "owned": "Propiedad hoy {cond}", "price": "Precio {cond}", "minutes": "Minutos {cond}",
        "percent": "{n} %", "floor": "Mín. {n}′",
        "positions": {"GKP": "Porteros", "DEF": "Defensas", "MID": "Medios", "FWD": "Delanteros"},
        "all_positions": "Todas las posiciones", "except_positions": "Excepto {names}",
        "club": "Club actual: {names}", "not_club": "Club actual: excepto {names}",
        "set_pieces": {"penalties": "penales", "direct_freekicks": "tiros libres directos", "corners": "córners"},
        "taker": "Primer lanzador de {names}", "not_taker": "No es primer lanzador de {names}",
        "or": " o ", "of": " o de ",
        "not_checked": "Sumas sin comprobar", "unavailable": "No disponible: {names}",
        "kinds": {
            "season_only_metric": "ese dato solo existe a día de hoy", "player_venue": "local o visitante por jugador",
            "opponent": "filtro por rival", "month": "meses", "calendar_phrase": "fechas del calendario",
            "result": "filtro por resultado", "started": "solo como titular", "several_players": "varios jugadores",
            "player_attribute": "atributos del jugador", "exclusion": "exclusiones", "single_value": "un solo dato",
            "difference_list": "lista de diferencias", "more_than_two_sets": "más de dos grupos de partidos",
            "ownership_then": "propiedad en ese momento", "future": "pronósticos", "flank_or_shots": "bandas y tiros",
            "past_season": "temporadas pasadas", "count_of_gws": "contar jornadas", "streak": "rachas",
            "vague_recent": "«últimamente» sin un número",
        },
    },
    "en": {
        "teams": "Teams", "gw": "GW", "and_gw": "", "season": "Season", "today": "Today",
        "last": "Last {n}", "last_one": "Last 1", "since": "Since {date}",
        "months": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        "provisional": "(provisional)",
        "with": "With {player} ({club}60′+)", "without": "Without {player} ({club}0′)",
        "without_same": "Without (0′)", "home": "Home", "away": "Away",
        "mixed": "Mixed left out: {gws}",
        "club_metric": "{club} {metric}", "lowest_first": "(lowest first)", "top": "Top {n}",
        "owned": "Owned now {cond}", "price": "Price {cond}", "minutes": "Minutes {cond}",
        "percent": "{n}%", "floor": "Min. {n}′",
        "positions": {"GKP": "Goalkeepers", "DEF": "Defenders", "MID": "Midfielders", "FWD": "Forwards"},
        "all_positions": "All positions", "except_positions": "Except {names}",
        "club": "Current club: {names}", "not_club": "Current club: except {names}",
        "set_pieces": {"penalties": "penalty", "direct_freekicks": "direct free kick", "corners": "corner"},
        "taker": "First {names} taker", "not_taker": "Not first {names} taker",
        "or": " or ", "of": " or ",
        "not_checked": "Totals not checked yet", "unavailable": "Not available: {names}",
        "kinds": {
            "season_only_metric": "that figure only exists as of today", "player_venue": "home or away by player",
            "opponent": "opponent filter", "month": "months", "calendar_phrase": "calendar phrases",
            "result": "result filter", "started": "starts only", "several_players": "several players",
            "player_attribute": "player attributes", "exclusion": "exclusions", "single_value": "a single figure",
            "difference_list": "a list of differences", "more_than_two_sets": "more than two sets of matches",
            "ownership_then": "ownership at the time", "future": "predictions", "flank_or_shots": "flanks and shots",
            "past_season": "past seasons", "count_of_gws": "counting gameweeks", "streak": "streaks",
            "vague_recent": "“lately” with no number",
        },
    },
}

_SIGNS = {"eq": "=", "lt": "<", "le": "≤", "gt": ">", "ge": "≥"}


# ------------------------------------------------------------------------------------------------------- numbers

def _number(value: float, decimals: int = 0) -> str:
    """Dot decimals, at least *decimals* of them, never rounding a digit away."""
    value = float(value)
    if round(value, decimals) == value:
        return f"{value:.{decimals}f}"
    return repr(value)


def value_text(value: float, value_range: tuple[float, float] | None = None, decimals: int = 2) -> str:
    """A computed value as any surface prints it. Where a range is set, the range is the answer (the engine's
    ``Row.value_range`` / ``Side.total_range``); ``value`` is then only the sort key and is not printed."""
    def one(v: float) -> str:
        return _number(round(v, decimals) + 0.0, decimals if round(v, decimals) != round(v) else 0)
    if value_range is not None:
        return f"{one(value_range[0])}–{one(value_range[1])}"
    return one(value)


def gameweeks_text(gameweeks: Iterable[int], lang: str) -> str:
    """``J7–J11`` / ``GW7–11``; gaps are kept: ``J1–J3, J5``."""
    words = WORDS[lang]
    runs: list[list[int]] = []
    for gw in sorted(set(gameweeks)):
        if runs and gw == runs[-1][1] + 1:
            runs[-1][1] = gw
        else:
            runs.append([gw, gw])
    return ", ".join(f"{words['gw']}{a}" if a == b else f"{words['gw']}{a}–{words['and_gw']}{b}" for a, b in runs)


def _capital(text: str) -> str:
    return text if text.startswith(("xG", "xA")) else text[:1].upper() + text[1:]


# --------------------------------------------------------------------------------------------------------- names

class _Names:
    """Resolved names when the engine resolved them, else the words of the spec."""

    def __init__(self, result: QueryResult | None, bootstrap: Mapping[str, Any] | None) -> None:
        self.result = result
        teams = (bootstrap or {}).get("teams") or []
        self.by_code = {str(t["short_name"]): str(t["name"]) for t in teams}

    def player(self, written: str) -> tuple[str, str]:
        """(name, club code or "")."""
        found = (self.result.players if self.result else {}).get(written)
        return (str(found["name"]), str(found["club"])) if found else (written, "")

    def club(self, written: str) -> str:
        code = (self.result.clubs if self.result else {}).get(written)
        return self.by_code.get(code, code) if code else written

    def club_by_code(self, code: str) -> str:
        return self.by_code.get(code, code)


# ---------------------------------------------------------------------------------------------------- the pieces

def metric_label(spec: QuerySpec, lang: str) -> str:
    """Direction + metric (+ operator). A plain ranking uses the catalogue's phrase for its direction; a rate
    or a compound is named without one when it runs high to low ("Goles por 90", "Goles − xG")."""
    row = cat.METRICS[spec.metric]
    operator = cat.OPERATORS[spec.operator]
    second = spec.second_metric
    if second is not None:
        text = _capital(row.name[lang] + operator["joiner"] + cat.METRICS[second].name[lang])
        return text if spec.order == "desc" else f"{text} {WORDS[lang]['lowest_first']}"
    suffix = operator["suffix"][lang]
    if not suffix:
        return (row.desc if spec.order == "desc" else row.asc)[lang]
    if spec.order == "desc":
        return f"{_capital(row.name[lang])} {suffix}"
    return f"{row.asc[lang]} {suffix}"


def _comparison_metric(spec: QuerySpec, lang: str, names: _Names) -> str:
    """A comparison ranks nothing: the metric, its operator and whose it is."""
    row = cat.METRICS[spec.metric]
    operator = cat.OPERATORS[spec.operator]
    text = row.name[lang]
    if spec.second_metric is not None:
        text += operator["joiner"] + cat.METRICS[spec.second_metric].name[lang]
    if operator["suffix"][lang]:
        text += " " + operator["suffix"][lang]
    result = names.result
    if result is not None and result.comparison is not None:
        club = names.club_by_code(result.comparison.club)
    else:
        club = next((names.club(f.value) for f in spec.filters
                     if f.field == "club" and f.op == "eq"), "")
        if not club:                                        # no sets to read it from: the named player's club
            codes = [names.player(p.value)[1] for p in spec.match_set + (spec.compare_to or ())
                     if p.pred in PLAYER_PREDICATES]
            club = next((names.club_by_code(c) for c in codes if c), "")
    if not club:
        return _capital(text)
    out = WORDS[lang]["club_metric"].format(metric=text, club=club)
    return _capital(out)


def _window(preds: tuple[Predicate, ...]) -> Predicate:
    return next((p for p in preds if p.pred in WINDOW_PREDICATES), Predicate("season", True))


def _window_words(window: Predicate, lang: str) -> tuple[str, bool]:
    """(the window in the user's own form, whether the gameweek range goes after it in brackets)."""
    words = WORDS[lang]
    if window.pred == "season":
        return words["season"], True
    if window.pred == "last_n":
        return (words["last_one"] if window.value == 1 else words["last"].format(n=window.value)), True
    if window.pred == "gw":
        return gameweeks_text([window.value], lang), False
    if window.pred == "gw_range":
        return gameweeks_text(range(window.value[0], window.value[1] + 1), lang), False
    year, month, day = parse_date(window.value)
    date = f"{day} {words['months'][month - 1]}" + (f" {year}" if year is not None else "")
    return words["since"].format(date=date), True


def _condition(pred: Predicate, lang: str, names: _Names, *, show_club: bool, same_as: str | None = None) -> str:
    words = WORDS[lang]
    if pred.pred == "venue":
        return words[pred.value]
    name, code = names.player(pred.value)
    club = f"{code}, " if show_club and code else ""
    if pred.pred == "player_played_60":
        return words["with"].format(player=name, club=club)
    if same_as == name:                                     # right after "With X": the name is already said
        return words["without_same"].format(player=name)
    return words["without"].format(player=name, club=club)


def _conditions(preds: tuple[Predicate, ...]) -> list[Predicate]:
    return [p for p in preds if p.pred not in WINDOW_PREDICATES]


def _values(f: Filter) -> tuple[Any, ...]:
    return f.value if isinstance(f.value, tuple) else (f.value,)


def _bound(f: Filter, decimals: int, unit: str = "{n}") -> str:
    if f.op == "between":
        return unit.format(n=f"{_number(f.value[0], decimals)}–{_number(f.value[1], decimals)}")
    return f"{_SIGNS[f.op]} {unit.format(n=_number(f.value, decimals))}"


def filter_label(f: Filter, lang: str, names: _Names) -> str:
    words = WORDS[lang]
    if f.field == "position":
        listed = ", ".join(words["positions"][v] for v in _values(f))
        return words["except_positions"].format(names=listed.lower()) if f.op == "not" else listed
    if f.field == "club":
        listed = words["or"].join(names.club(v) for v in _values(f))
        return words["not_club" if f.op == "not" else "club"].format(names=listed)
    if f.field == "set_piece":
        listed = words["of"].join(words["set_pieces"][v] for v in _values(f))
        return words["not_taker" if f.op == "not" else "taker"].format(names=listed)
    if f.field == "owned_now":
        return words["owned"].format(cond=_bound(f, 0, words["percent"]))
    if f.field == "price":
        return words["price"].format(cond=_bound(f, 1))
    return words["minutes"].format(cond=_bound(f, 0, "{n}′"))


# --------------------------------------------------------------------------------------------------- the choices

def _spec_with(spec: QuerySpec, *, match_set: tuple[Predicate, ...] | None = None,
               old: Filter | None = None, new: Filter | None = None) -> dict[str, Any]:
    """The typed spec after one edit, in its public form."""
    changed = spec
    if match_set is not None:
        changed = replace(changed, match_set=match_set)
    if old is not None or new is not None:
        kept = [f for f in changed.filters if f != old]
        if new is not None:
            kept.append(new)
        changed = replace(changed, filters=tuple(sorted(
            dict.fromkeys(kept), key=lambda f: (cat.FILTER_FIELDS.index(f.field), f.op, str(f.value)))))
    return changed.to_dict()


def _window_choices(spec: QuerySpec, lang: str) -> list[dict[str, Any]]:
    current = _window(spec.match_set)
    conditions = tuple(_conditions(spec.match_set))
    out = []
    for window in [Predicate("last_n", n) for n in WINDOW_CHOICES] + [Predicate("season", True)]:
        if window == current:
            continue
        preds = ((window,) if window.pred != "season" else ()) + conditions
        preds = tuple(sorted(preds, key=lambda p: (cat.PREDICATES.index(p.pred), str(p.value)))) or (window,)
        out.append({"label": _window_words(window, lang)[0], "spec": _spec_with(spec, match_set=preds)})
    return out


def _position_choices(spec: QuerySpec, lang: str) -> list[dict[str, Any]]:
    words = WORDS[lang]
    rest = tuple(f for f in spec.filters if f.field != "position")
    current = [f for f in spec.filters if f.field == "position"]
    base = replace(spec, filters=rest)
    out = [{"label": words["positions"][p], "spec": _spec_with(base, new=Filter("position", "eq", p))}
           for p in cat.POSITIONS
           if not (len(current) == 1 and current[0].op == "eq" and current[0].value == p)]
    if current:
        out.append({"label": words["all_positions"], "spec": base.to_dict()})
    return out


def _filter_choices(spec: QuerySpec, f: Filter, lang: str, names: _Names) -> list[dict[str, Any]]:
    if f.field == "owned_now":
        wanted = [Filter(f.field, "lt", float(n)) for n in OWNERSHIP_CHOICES]
    elif f.field == "price":
        if f.op == "between":
            wanted = []
        else:
            low, high = cat.FILTER_RANGES["price"]
            wanted = [Filter(f.field, f.op, round(f.value + step, 2)) for step in PRICE_STEPS
                      if low <= f.value + step <= high]
    elif f.field == "minutes_in_window":
        wanted = [Filter(f.field, "ge", n) for n in MINUTES_CHOICES]
    else:
        return []
    out = [{"label": filter_label(w, lang, names), "spec": _spec_with(spec, old=f, new=w)}
           for w in wanted if w != f]
    # Removing the filter is the "all" choice.
    out.append({"label": _all_label(f.field, lang), "spec": _spec_with(spec, old=f)})
    return out


def _all_label(field: str, lang: str) -> str:
    return {"es": {"owned_now": "Cualquier propiedad", "price": "Cualquier precio",
                   "minutes_in_window": "Cualquier cantidad de minutos"},
            "en": {"owned_now": "Any ownership", "price": "Any price",
                   "minutes_in_window": "Any minutes"}}[lang][field]


# ----------------------------------------------------------------------------------------------------- the line

def _part(kind: str, label: str, value: Any = None, alternatives: list | None = None) -> dict[str, Any]:
    return {"kind": kind, "label": label, "value": value, "editable": bool(alternatives),
            "alternatives": alternatives or [], "braked": False}


def _metric_value(spec: QuerySpec) -> dict[str, Any]:
    value = {"metric": spec.metric, "operator": spec.operator, "order": spec.order}
    if spec.metric_minus is not None:
        value["metric_minus"] = spec.metric_minus
    if spec.metric_plus is not None:
        value["metric_plus"] = spec.metric_plus
    return value


def _comparison_parts(spec: QuerySpec, lang: str, names: _Names, result: QueryResult | None) -> list[dict]:
    """One part per set of matches: its window (unless the whole season) and conditions, then the gameweeks it
    turned out to hold."""
    parts = []
    comparison = result.comparison if result is not None else None
    first_with: str | None = None
    for index, (kind, preds) in enumerate((("match_set", spec.match_set), ("compare_to", spec.compare_to or ()))):
        window = _window(preds)
        pieces = []
        if window.pred != "season":
            pieces.append(_window_words(window, lang)[0])
        for p in _conditions(preds):
            pieces.append(_condition(p, lang, names, show_club=False,
                                     same_as=first_with if p.pred == "player_absent" and len(pieces) == 0 else None))
            if index == 0 and p.pred == "player_played_60":
                first_with = names.player(p.value)[0]
        label = ", ".join(pieces) or WORDS[lang]["season"]
        if comparison is not None:
            label += f": {gameweeks_text(comparison.sides[index].gameweeks, lang)}"
        if result is not None and result.provisional:
            label += f" {WORDS[lang]['provisional']}"
        parts.append(_part(kind, label, [p.to_dict() for p in preds]))
    if comparison is not None and comparison.mixed:
        gws = gameweeks_text([gw for gw, _ in comparison.mixed], lang)
        parts.append(_part("mixed", WORDS[lang]["mixed"].format(gws=gws), [gw for gw, _ in comparison.mixed]))
    return parts


def _parts(spec: QuerySpec, lang: str, names: _Names, result: QueryResult | None) -> list[dict[str, Any]]:
    words = WORDS[lang]
    comparison = spec.shape == "comparison"
    snapshot = cat.METRICS[spec.metric].group == "snapshot"
    parts = []
    if spec.grain == "team":
        parts.append(_part("grain", words["teams"], "team"))
    parts.append(_part("metric", _comparison_metric(spec, lang, names) if comparison else metric_label(spec, lang),
                       _metric_value(spec)))
    if not comparison and spec.top_n != cat.DEFAULTS["top_n"]:
        parts.append(_part("top_n", words["top"].format(n=spec.top_n), spec.top_n))

    if comparison:
        parts += _comparison_parts(spec, lang, names, result)
    else:
        window = _window(spec.match_set)
        label, with_range = _window_words(window, lang)
        if snapshot and window.pred == "season":
            label, with_range = words["today"], False
        if with_range and result is not None and result.gameweeks:
            label += f" ({gameweeks_text(result.gameweeks, lang)})"
        if result is not None and result.provisional:
            label += f" {words['provisional']}"
        choices = [] if snapshot else _window_choices(spec, lang)
        parts.append(_part("window", label, window.to_dict(), choices))
        for p in _conditions(spec.match_set):
            parts.append(_part("condition", _condition(p, lang, names, show_club=True), p.to_dict()))

    by_field = {name: [f for f in spec.filters if f.field == name] for name in cat.FILTER_FIELDS}

    def add(kind: str, field: str) -> None:
        for f in by_field[field]:
            parts.append(_part(kind, filter_label(f, lang, names), f.to_dict(),
                               [] if comparison else _filter_choices(spec, f, lang, names)))

    add("ownership", "owned_now")
    # Position before price, as in Amendment 4's examples (its parts table lists them the other way round).
    if spec.grain == "player":
        choices = _position_choices(spec, lang)
        if by_field["position"]:
            for f in by_field["position"]:
                parts.append(_part("position", filter_label(f, lang, names), f.to_dict(), choices))
        else:
            parts.append(_part("position", words["all_positions"], None, choices))
    add("price", "price")
    for f in by_field["club"]:
        if comparison and f.op == "eq":                     # the metric part says whose it is
            continue
        parts.append(_part("club", filter_label(f, lang, names), f.to_dict()))
    add("set_piece", "set_piece")
    add("minutes", "minutes_in_window")
    if result is not None and result.min_minutes > 0:
        # Not editable: the floor is the engine's rule, and a spec can only ask for more minutes, never fewer.
        parts.append(_part("floor", words["floor"].format(n=result.min_minutes), result.min_minutes))
    if result is not None and result.sum_check == "not_checked":
        parts.append(_part("note", words["not_checked"], "not_checked"))
    return parts


# ---------------------------------------------------------------------------------------------------- the brakes

def _mark(parts: list[dict], kinds: Iterable[str], where=lambda part: True) -> bool:
    hit = [p for p in parts if p["kind"] in set(kinds) and where(p)]
    for p in hit:
        p["braked"] = True
    return bool(hit)


_SETS = ("window", "condition", "match_set", "compare_to")


def _mark_unsupported(parts: list[dict], kinds: Iterable[str], lang: str) -> None:
    """Marks the part that asks for the unsupported thing; what the spec cannot even hold gets a part of its own."""
    unnamed = []
    for kind in kinds:
        if kind == "season_only_metric":
            found = _mark(parts, _SETS)
        elif kind == "player_venue":
            found = _mark(parts, ("condition", "match_set", "compare_to"), lambda p: "venue" in str(p["value"]))
        elif kind == "several_players":
            found = _mark(parts, ("condition", "match_set", "compare_to"), lambda p: "player_" in str(p["value"]))
        elif kind == "difference_list":
            found = _mark(parts, ("compare_to",))
        elif kind == "opponent":
            found = _mark(parts, ("club",))
        else:
            found = False
        if not found:
            unnamed.append(kind)
    if unnamed:
        names = ", ".join(WORDS[lang]["kinds"][k] for k in unnamed)
        part = _part("unsupported", WORDS[lang]["unavailable"].format(names=names), unnamed)
        part["braked"] = True
        parts.append(part)


def _mark_clarify(parts: list[dict], clarify: Mapping[str, Any]) -> None:
    written = str(clarify.get("written") or "")

    def names_it(part: dict) -> bool:
        return bool(written) and written in str(part["value"])

    kind = clarify.get("kind")
    found = False
    if kind in ("player", "player_club"):
        found = _mark(parts, ("condition", "match_set", "compare_to"), names_it)
    if kind == "club":
        found = _mark(parts, ("club",), names_it)
    if kind == "player_club":
        _mark(parts, ("club",))
    if not found:                                           # the comparison's club lives in the metric part
        _mark(parts, ("metric",))


def _mark_result(parts: list[dict], result: QueryResult, lang: str) -> None:
    if result.state == UNSUPPORTED:
        _mark_unsupported(parts, result.unsupported, lang)
    elif result.state == NEEDS_CLARIFICATION:
        _mark_clarify(parts, result.clarify or {})
    elif result.state == DATA_UNAVAILABLE:
        if result.reason == "invariant_failed":
            _mark(parts, ("metric",))
        elif result.reason == "too_few_matches":
            _mark(parts, ("match_set", "compare_to"))
        else:
            _mark(parts, _SETS)


def render_reading(spec: QuerySpec, lang: str, result: QueryResult | None = None,
                   bootstrap: Mapping[str, Any] | None = None,
                   unsupported: Iterable[str] = ()) -> dict[str, Any]:
    """The ``query.reading`` block. *result* must be the run of *spec*. *unsupported* adds kinds found outside
    the spec (what the model or a brake reports as not expressible); they brake the line too."""
    if lang not in LANGS:
        raise ValueError(f"unknown language: {lang}")
    if result is not None and result.spec != spec:
        raise ValueError("the result is not the run of this spec")
    names = _Names(result, bootstrap)
    parts = _parts(spec, lang, names, result)
    extra = list(unsupported)
    if result is None:
        extra += unsupported_reasons(spec)
    elif result.state != COMPLETE:
        _mark_result(parts, result, lang)
        if result.state == UNSUPPORTED:
            extra = [k for k in extra if k not in result.unsupported]
    if extra:
        _mark_unsupported(parts, dict.fromkeys(extra), lang)
    text = SEPARATOR.join((BRAKE_MARK if p["braked"] else "") + p["label"] for p in parts)
    return {"parts": parts, "text": text, "lang": lang}
