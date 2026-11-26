"""Query layer PR 4: the reading line.

Golden lines (Amendment 4 §4.1 and one per probe family), injectivity over the whole vocabulary, the four
states, and the ``query.reading`` fixture the card (PR 7) is built against
(``UPDATE_QUERY_FIXTURES=1 pytest tests/test_query_reading.py`` rewrites it). Names are illustrative; no
value comes from any store.
"""
from __future__ import annotations

import itertools
import json
import os
from pathlib import Path

import pytest

from fpl_grounded_assistant import query_catalogue as cat
from fpl_grounded_assistant.query_engine import (COMPLETE, DATA_UNAVAILABLE, NEEDS_CLARIFICATION, UNSUPPORTED,
                                                 Comparison, QueryResult, Side, run_query)
from fpl_grounded_assistant.query_reading import (BRAKE_MARK, LANGS, SEPARATOR, WORDS, gameweeks_text,
                                                  render_reading, value_text)
from fpl_grounded_assistant.query_spec import QuerySpecError, parse_spec

from test_query_engine import flt, pred, with_without, world

FIXTURE = Path(__file__).parent / "fixtures" / "query_reading_examples.json"
BOOTSTRAP = {"teams": [{"id": 1, "short_name": "BOU", "name": "Bournemouth"},
                       {"id": 2, "short_name": "EVE", "name": "Everton"}]}


def _side(gws):
    return Side(matches=(), gameweeks=tuple(gws), n=len(gws), home=0, away=0, mean_fdr=None, total=0.0,
                per_match=0.0, value=0.0, per_match_values=())


def _comparison(first, second, mixed=()):
    return Comparison(team_id=1, club="BOU", sides=(_side(first), _side(second)), mixed=tuple(mixed),
                      before_join=(), small_sample=False, ranges_overlap=True)


def _done(raw, state=COMPLETE, **extra):
    spec = parse_spec(raw)
    return spec, QueryResult(state, spec, **extra)


SEMENYO = {"metric": "team_expected_goals", "shape": "comparison",
           "match_set": [pred("player_played_60", "Semenyo")], "compare_to": [pred("player_absent", "Semenyo")]}
SEMENYO_RUN = {"players": {"Semenyo": {"id": 5, "name": "Semenyo", "team_id": 1, "club": "BOU"}},
               "comparison": _comparison(range(1, 7), range(8, 12), mixed=[(7, 13)])}

#: (name, raw spec, what the run knows, ES, EN) — the five examples of Amendment 4 §4.1, in its order.
AMENDMENT_4 = [
    ("low_ownership_last_5",
     {"metric": "total_points", "match_set": [pred("last_n", 5)], "filters": [flt("owned_now", "lt", 10)]},
     {"gameweeks": (7, 8, 9, 10, 11)},
     "Más puntos · Últimas 5 (J7–J11) · Propiedad hoy < 10 % · Todas las posiciones",
     "Most points · Last 5 (GW7–11) · Owned now < 10% · All positions"),
    ("cheap_forwards_per_90",
     {"metric": "goals_scored", "operator": "per_90", "match_set": [pred("since_date", "2026-10-10")],
      "filters": [flt("position", "eq", "FWD"), flt("price", "le", 7)]},
     {"gameweeks": (8, 9, 10, 11, 12), "min_minutes": 270},
     "Goles por 90 · Desde 10 oct 2026 (J8–J12) · Delanteros · Precio ≤ 7.0 · Mín. 270′",
     "Goals per 90 · Since 10 Oct 2026 (GW8–12) · Forwards · Price ≤ 7.0 · Min. 270′"),
    ("team_with_without", SEMENYO, SEMENYO_RUN,
     "Equipos · xG de Bournemouth · Con Semenyo (≥ 60′): J1–J6 · Sin Semenyo (0′): J8–J11 · Mixtos fuera: J7",
     "Teams · Bournemouth xG · With Semenyo (60′+): GW1–6 · Without (0′): GW8–11 · Mixed left out: GW7"),
    ("goals_above_xg",
     {"metric": "goals_scored", "operator": "minus", "metric_minus": "expected_goals"},
     {"gameweeks": tuple(range(1, 13))},
     "Goles − xG · Temporada (J1–J12) · Todas las posiciones",
     "Goals − xG · Season (GW1–12) · All positions"),
    ("fewest_conceded_at_home",
     {"metric": "team_goals_conceded", "order": "asc", "match_set": [pred("last_n", 6), pred("venue", "home")]},
     {"gameweeks": tuple(range(7, 13))},
     "Equipos · Menos goles recibidos · Últimas 6 (J7–J12) · De local",
     "Teams · Fewest goals conceded · Last 6 (GW7–12) · Home"),
]

#: One more line per probe family (constrained, legit, comparison, team, trap) and per remaining kind of word.
FAMILIES = [
    ("constrained",
     {"metric": "expected_goals", "match_set": [pred("gw_range", [6, 11])],
      "filters": [flt("position", "in", ["MID", "FWD"]), flt("price", "between", [5.5, 8]),
                  flt("club", "eq", "EVE"), flt("minutes_in_window", "ge", 180)], "top_n": 5},
     {"gameweeks": tuple(range(6, 12)), "clubs": {"EVE": "EVE"}},
     "Mayor xG · Top 5 · J6–J11 · Delanteros, Medios · Precio 5.5–8.0 · Club actual: Everton · Minutos ≥ 180′",
     "Highest xG · Top 5 · GW6–11 · Forwards, Midfielders · Price 5.5–8.0 · Current club: Everton · "
     "Minutes ≥ 180′"),
    ("legit_todays_value",
     {"metric": "penalties_order", "filters": [flt("set_piece", "eq", "penalties")]}, {},
     "Orden de penales · Hoy · Todas las posiciones · Primer lanzador de penales",
     "Penalty taker order · Today · All positions · First penalty taker"),
    ("legit_one_gameweek",
     {"metric": "total_points", "match_set": [pred("gw", 3)]}, {"gameweeks": (3,), "provisional": True},
     "Más puntos · J3 (provisional) · Todas las posiciones",
     "Most points · GW3 (provisional) · All positions"),
    ("comparison_home_away",
     {"metric": "team_goals", "operator": "per_match", "shape": "comparison", "grain": "team",
      "filters": [flt("club", "eq", "Bournemouth")], "match_set": [pred("venue", "home")],
      "compare_to": [pred("venue", "away")]},
     {"comparison": _comparison([1, 3, 5], [2, 4, 6])},
     "Equipos · Goles por partido de Bournemouth · De local: J1, J3, J5 · De visitante: J2, J4, J6",
     "Teams · Bournemouth goals per match · Home: GW1, GW3, GW5 · Away: GW2, GW4, GW6"),
    ("team_plus_asc",
     {"metric": "team_goals", "operator": "plus", "metric_plus": "team_clean_sheets", "order": "asc"},
     {"gameweeks": (1, 2)},
     "Equipos · Goles + porterías a cero (menor primero) · Temporada (J1–J2)",
     "Teams · Goals + clean sheets (lowest first) · Season (GW1–2)"),
    ("trap_player_list_with_club",
     {"metric": "assists", "operator": "per_million", "match_set": [pred("player_absent", "Semenyo")],
      "filters": [flt("position", "not", "GKP")]},
     {"gameweeks": (1, 2), "players": SEMENYO_RUN["players"]},
     "Asistencias por millón (precio actual) · Temporada (J1–J2) · Sin Semenyo (BOU, 0′) · Excepto porteros",
     "Assists per £m (current price) · Season (GW1–2) · Without Semenyo (BOU, 0′) · Except goalkeepers"),
]


def _line(raw, run, lang):
    spec, result = _done(raw, **run)
    return render_reading(spec, lang, result, BOOTSTRAP)["text"]


@pytest.mark.parametrize("name,raw,run,es,en", AMENDMENT_4 + FAMILIES, ids=[c[0] for c in AMENDMENT_4 + FAMILIES])
def test_golden_lines(name, raw, run, es, en):
    assert (_line(raw, run, "es"), _line(raw, run, "en")) == (es, en)


def test_dot_decimals_in_spanish():
    line = _line({"metric": "total_points", "filters": [flt("price", "lt", 7.5), flt("owned_now", "le", 2.5)]},
                 {}, "es")
    assert "Precio < 7.5" in line and "Propiedad hoy ≤ 2.5 %" in line and "7,5" not in line


def test_a_number_is_never_rounded_into_another():
    lines = {_line({"metric": "total_points", "filters": [flt("price", "lt", v)]}, {}, "es")
             for v in (7, 7.04, 7.05, 7.1)}
    assert len(lines) == 4


def test_every_comparison_sign_is_printed():
    for op, sign in (("eq", "="), ("lt", "<"), ("le", "≤"), ("gt", ">"), ("ge", "≥")):
        assert f"Precio {sign} 7.0" in _line({"metric": "total_points", "filters": [flt("price", op, 7)]}, {}, "es")


def test_a_date_still_without_a_year_prints_none():
    spec = parse_spec({"metric": "total_points", "match_set": [pred("since_date", "10-10")]})
    assert "Desde 10 oct ·" in render_reading(spec, "es")["text"]


def test_gameweek_gaps_are_kept():
    assert (gameweeks_text([5, 1, 2, 3], "es"), gameweeks_text([1, 2, 5], "en")) == ("J1–J3, J5", "GW1–2, GW5")


def test_a_range_is_printed_instead_of_the_value():
    assert value_text(11.77, (11.52, 11.77)) == "11.52–11.77"
    assert (value_text(11.77), value_text(3.0), value_text(-0.001)) == ("11.77", "3", "0")


def test_unchecked_sums_are_said_and_checked_ones_are_not():
    raw = {"metric": "total_points"}
    assert _line(raw, {"sum_check": "not_checked"}, "es").endswith("· Sumas sin comprobar")
    assert _line(raw, {"sum_check": "not_checked"}, "en").endswith("· Totals not checked yet")
    assert "comprobar" not in _line(raw, {"sum_check": "passed"}, "es")


def test_the_result_must_be_this_specs_run():
    _, other = _done({"metric": "assists"})
    with pytest.raises(ValueError):
        render_reading(parse_spec({"metric": "bonus"}), "es", other)


# ------------------------------------------------------------------------------------------------ injectivity

def _canonical(spec):
    """What a spec asks. Two specs with the same key may read the same: a one-item list is the item, a range
    from a gameweek to itself is that gameweek, and a comparison has no ranking, so its order and top_n change
    nothing."""
    out = spec.to_dict()
    for p in out["match_set"] + out.get("compare_to", []):
        if p["pred"] == "gw_range" and p["value"][0] == p["value"][1]:
            p.update(pred="gw", value=p["value"][0])
    filters = []
    for f in out["filters"]:
        value, op = f["value"], f["op"]
        if isinstance(value, list) and f["field"] in ("position", "club", "set_piece"):
            if len(value) == 1:
                value, op = value[0], "eq" if op == "in" else op
        filters.append(json.dumps([f["field"], op, value]))
    out["filters"] = sorted(filters)
    if spec.shape == "comparison":
        del out["order"], out["top_n"]
    return json.dumps(out, sort_keys=True)


def _vocabulary():
    """Every metric x operator x second metric x order, and every window, condition, filter and top_n on a
    base spec at both grains, alone and in pairs."""
    for metric, row in cat.METRICS.items():
        for operator in cat.operators_for(metric):
            key = cat.OPERATORS[operator]["second_metric"]
            seconds = [None]
            if key:
                seconds = [m for m, other in cat.METRICS.items()
                           if m != metric and other.group == row.group and operator in cat.operators_for(m)]
            for second, order in itertools.product(seconds, ("asc", "desc")):
                raw = {"metric": metric, "operator": operator, "order": order}
                if key:
                    raw[key] = second
                yield raw

    windows = [[]] + [[pred("last_n", n)] for n in (1, 3, 5, 10)] + [[pred("gw", n)] for n in (1, 3, 5, 10)]
    windows += [[pred("gw_range", r)] for r in ([1, 3], [3, 5], [3, 3], [1, 10])]
    windows += [[pred("since_date", d)] for d in ("10-10", "2026-10-10", "2025-10-10", "2026-01-10")]
    conditions = [[], [pred("player_played_60", "Alfa")], [pred("player_played_60", "Beta")],
                  [pred("player_absent", "Alfa")], [pred("player_absent", "Beta")],
                  [pred("venue", "home")], [pred("venue", "away")],
                  [pred("venue", "home"), pred("player_absent", "Alfa")],
                  [pred("player_played_60", "Alfa"), pred("player_absent", "Beta")]]
    sets = [w + c for w, c in itertools.product(windows, conditions)]
    for match_set in sets:
        for base in ({"metric": "total_points"}, {"metric": "team_goals"}):
            yield {**base, "match_set": match_set}

    filters = [flt("position", "eq", p) for p in cat.POSITIONS] + [flt("position", "not", p) for p in cat.POSITIONS]
    filters += [flt("position", "in", ["MID", "FWD"]), flt("position", "not", ["MID", "FWD"])]
    for field_, values in (("price", (5, 5.5, 7)), ("owned_now", (5, 10, 15)), ("minutes_in_window", (5, 90, 270))):
        filters += [flt(field_, op, v) for op in ("eq", "lt", "le", "gt", "ge") for v in values]
        filters += [flt(field_, "between", [5, 10]), flt(field_, "between", [5, 15])]
    filters += [flt("club", op, v) for op in ("eq", "not") for v in ("Arsenal", "Everton")]
    filters += [flt("club", "in", ["Arsenal", "Everton"])]
    filters += [flt("set_piece", op, v) for op in ("eq", "not") for v in cat.SET_PIECES]
    filters += [flt("set_piece", "in", ["penalties", "corners"])]
    yield from ({"metric": "total_points", "filters": [f]} for f in filters)
    yield from ({"metric": "total_points", "filters": list(pair)} for pair in itertools.combinations(filters, 2))
    yield from ({"metric": "team_goals", "filters": [f]} for f in filters if f["field"] == "club")
    for metric in ("total_points", "team_goals"):
        yield from ({"metric": metric, "top_n": n} for n in range(1, cat.LIMITS["top_n_max"] + 1))

    some = sets[::7]
    for metric, operator in (("team_goals", "sum"), ("team_goals", "per_match"), ("team_expected_goals", "sum"),
                             ("total_points", "sum")):
        for first, second in itertools.permutations(some, 2):
            for club in ([], [flt("club", "eq", "Arsenal")]):
                yield {"metric": metric, "operator": operator, "shape": "comparison", "match_set": first,
                       "compare_to": second, "filters": club}


@pytest.fixture(scope="module")
def vocabulary_specs():
    specs = {}
    for raw in _vocabulary():
        try:
            spec = parse_spec(raw)
        except QuerySpecError:                              # e.g. a player filter at team grain
            continue
        specs[_canonical(spec)] = spec
    return specs


@pytest.mark.parametrize("lang", LANGS)
def test_two_different_questions_never_read_the_same(vocabulary_specs, lang):
    assert len(vocabulary_specs) > 8000
    seen: dict[str, str] = {}
    clashes = []
    for key, spec in vocabulary_specs.items():
        text = render_reading(spec, lang)["text"]
        if seen.setdefault(text, key) != key:
            clashes.append((text, seen[text], key))
    assert not clashes, f"{len(clashes)} clashes, first: {clashes[0]}"


def test_the_generator_reaches_every_metric_predicate_and_filter(vocabulary_specs):
    specs = vocabulary_specs.values()
    assert {s.metric for s in specs} == set(cat.METRICS)
    assert {p.pred for s in specs for p in s.match_set} == set(cat.PREDICATES)
    assert {f.field for s in specs for f in s.filters} == set(cat.FILTER_FIELDS)
    assert {s.operator for s in specs} == set(cat.OPERATORS)


@pytest.mark.parametrize("lang", LANGS)
def test_every_unsupported_kind_has_its_own_words(lang):
    kinds = set(cat.UNSUPPORTED_KINDS) | {"season_only_metric"}
    assert set(WORDS[lang]["kinds"]) == kinds
    assert len(set(WORDS[lang]["kinds"].values())) == len(kinds)


# ------------------------------------------------------------------------------------------------ the choices

def test_every_alternative_is_a_whole_valid_spec_that_reads_differently(vocabulary_specs):
    checked = 0
    for spec in list(vocabulary_specs.values())[::17]:
        block = render_reading(spec, "es")
        for part in block["parts"]:
            assert part["editable"] == bool(part["alternatives"])
            for choice in part["alternatives"]:
                chosen = parse_spec(choice["spec"])
                assert chosen.to_dict() == choice["spec"] and _canonical(chosen) != _canonical(spec)
                assert (chosen.metric, chosen.operator, chosen.shape) == (spec.metric, spec.operator, spec.shape)
                checked += 1
    assert checked > 1000


def _part(block, kind):
    return next(p for p in block["parts"] if p["kind"] == kind)


def test_the_choices_are_the_amendments_and_change_one_thing():
    spec = parse_spec({"metric": "total_points", "match_set": [pred("last_n", 5), pred("player_absent", "Alfa")],
                       "filters": [flt("owned_now", "lt", 10), flt("position", "eq", "MID"),
                                   flt("price", "le", 7)]})
    block = render_reading(spec, "es")
    window = _part(block, "window")["alternatives"]
    assert [c["label"] for c in window] == ["Últimas 3", "Últimas 10", "Temporada"]
    assert all(pred("player_absent", "Alfa") in c["spec"]["match_set"] for c in window)
    assert window[-1]["spec"]["match_set"] == [pred("player_absent", "Alfa")]
    assert all(c["spec"]["filters"] == spec.to_dict()["filters"] for c in window)
    assert [c["label"] for c in _part(block, "ownership")["alternatives"]] == [
        "Propiedad hoy < 5 %", "Propiedad hoy < 15 %", "Cualquier propiedad"]
    assert [c["label"] for c in _part(block, "position")["alternatives"]] == [
        "Porteros", "Defensas", "Delanteros", "Todas las posiciones"]
    assert [c["label"] for c in _part(block, "price")["alternatives"]] == [
        "Precio ≤ 6.0", "Precio ≤ 6.5", "Precio ≤ 7.5", "Precio ≤ 8.0", "Cualquier precio"]
    assert not _part(block, "metric")["editable"]


def test_the_floor_and_a_comparison_are_not_editable():
    spec, result = _done({"metric": "goals_scored", "operator": "per_90"}, min_minutes=270)
    assert not _part(render_reading(spec, "es", result), "floor")["editable"]
    spec, result = _done(SEMENYO, **SEMENYO_RUN)
    assert not any(p["editable"] for p in render_reading(spec, "es", result, BOOTSTRAP)["parts"])


# --------------------------------------------------------------------------------------------- the four states

def _braked(block):
    return [p["kind"] for p in block["parts"] if p["braked"]]


STATES = [
    ("clarify_player", {"metric": "total_points", "match_set": [pred("player_absent", "Alfa")]},
     {"state": NEEDS_CLARIFICATION, "reason": "player_ambiguous",
      "clarify": {"kind": "player", "written": "Alfa", "candidates": ()}}, (), ["condition"]),
    ("clarify_club", {"metric": "total_points", "filters": [flt("club", "eq", "United")]},
     {"state": NEEDS_CLARIFICATION, "reason": "club_ambiguous",
      "clarify": {"kind": "club", "written": "United", "candidates": ()}}, (), ["club"]),
    ("unsupported_in_spec", {"metric": "total_points", "match_set": [pred("venue", "home")]},
     {"state": UNSUPPORTED, "reason": "player_venue", "unsupported": ("player_venue",)}, (), ["condition"]),
    ("unsupported_outside_spec", {"metric": "total_points", "filters": [flt("owned_now", "lt", 10)]},
     None, ("ownership_then",), ["unsupported"]),
    ("season_only", {"metric": "now_cost", "match_set": [pred("last_n", 5)]},
     {"state": UNSUPPORTED, "reason": "season_only_metric", "unsupported": ("season_only_metric",)}, (),
     ["window"]),
    ("missing_gameweek", {"metric": "total_points", "match_set": [pred("last_n", 5)]},
     {"state": DATA_UNAVAILABLE, "reason": "not_loaded", "missing_gameweeks": (9,),
      "gameweeks": (7, 8, 9, 10, 11)}, (), ["window"]),
    ("failed_sum_check", {"metric": "bonus"},
     {"state": DATA_UNAVAILABLE, "reason": "invariant_failed", "bad_metrics": ("bonus",)}, (), ["metric"]),
    ("too_few_matches", SEMENYO, {"state": DATA_UNAVAILABLE, "reason": "too_few_matches",
                                  "players": SEMENYO_RUN["players"]}, (), ["match_set", "compare_to"]),
]


def _state_block(raw, run, unsupported, lang):
    spec = parse_spec(raw)
    result = QueryResult(spec=spec, **run) if run else None
    return render_reading(spec, lang, result, BOOTSTRAP, unsupported=unsupported)


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("name,raw,run,unsupported,braked", STATES, ids=[s[0] for s in STATES])
def test_a_refusal_still_reads_and_marks_what_braked_it(name, raw, run, unsupported, braked, lang):
    block = _state_block(raw, run, unsupported, lang)
    assert _braked(block) == braked
    assert block["text"] == SEPARATOR.join((BRAKE_MARK if p["braked"] else "") + p["label"]
                                           for p in block["parts"])
    assert block["text"].count(BRAKE_MARK) == len(braked)


def test_a_comparison_with_no_sets_still_says_whose_it_is():
    block = _state_block(*STATES[-1][1:4], "es")
    assert _part(block, "metric")["label"] == "xG de Bournemouth"


def test_an_unsupported_kind_is_named():
    block = _state_block(*STATES[3][1:4], "es")
    assert block["text"].endswith("⚠ No disponible: propiedad en ese momento")


def test_a_kind_the_engine_already_marked_is_not_named_twice():
    block = _state_block(STATES[2][1], STATES[2][2], ("player_venue",), "es")
    assert _braked(block) == ["condition"]


def test_a_complete_answer_brakes_nothing():
    for case in AMENDMENT_4 + FAMILIES:
        spec, result = _done(case[1], **case[2])
        assert _braked(render_reading(spec, "es", result, BOOTSTRAP)) == []


# --------------------------------------------------------------------------------------- over the real engine

@pytest.mark.parametrize("raw", [
    {"metric": "total_points", "match_set": [pred("last_n", 3)]},
    {"metric": "expected_goals", "operator": "per_90"},
    with_without(),
])
def test_the_line_of_a_real_run_says_its_window_floor_and_sets(raw):
    bootstrap, batch = world()
    spec = parse_spec(raw)
    result = run_query(spec, bootstrap, batch)
    assert result.state == COMPLETE
    block = render_reading(spec, "en", result, bootstrap)
    if result.comparison is not None:
        club = next(t["name"] for t in bootstrap["teams"] if t["short_name"] == result.comparison.club)
        assert club in _part(block, "metric")["label"]
        for kind, side in zip(("match_set", "compare_to"), result.comparison.sides):
            assert _part(block, kind)["label"].endswith(gameweeks_text(side.gameweeks, "en"))
    else:
        assert gameweeks_text(result.gameweeks, "en") in _part(block, "window")["label"]
        floors = [p["value"] for p in block["parts"] if p["kind"] == "floor"]
        assert floors == ([result.min_minutes] if result.min_minutes else [])


# ------------------------------------------------------------------------------------------- the UI's fixture

def _examples():
    out = []
    for name, raw, run, _, _ in AMENDMENT_4 + FAMILIES:
        spec, result = _done(raw, **run)
        out.append({"name": name, "state": COMPLETE, "spec": spec.to_dict(),
                    "reading": {lang: render_reading(spec, lang, result, BOOTSTRAP) for lang in LANGS}})
    for name, raw, run, unsupported, _ in STATES:
        out.append({"name": name, "state": run["state"] if run else UNSUPPORTED,
                    "spec": parse_spec(raw).to_dict(),
                    "reading": {lang: _state_block(raw, run, unsupported, lang) for lang in LANGS}})
    return json.loads(json.dumps(out, ensure_ascii=False))


def test_the_ui_fixture_is_what_the_renderer_writes():
    examples = _examples()
    if os.environ.get("UPDATE_QUERY_FIXTURES"):
        FIXTURE.write_text(json.dumps(examples, indent=1, ensure_ascii=False) + "\n", encoding="utf-8",
                           newline="\n")
    assert FIXTURE.exists(), "run UPDATE_QUERY_FIXTURES=1"
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == examples
    assert {e["state"] for e in examples} == {COMPLETE, NEEDS_CLARIFICATION, UNSUPPORTED, DATA_UNAVAILABLE}
