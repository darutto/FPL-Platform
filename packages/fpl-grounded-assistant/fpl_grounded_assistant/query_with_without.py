"""The default answer to "how did <club>'s attack do with and without <player>": goals AND xG per match.

Code recognises the question from the user's raw text, so the answer does not depend on what the model does with
it (ask back, report a constraint, send a player metric at team grain). It is deliberately narrow: **every**
word besides the club and the player must be in :data:`_FILLER` or name the attack. One other word (another
statistic, a venue, an opponent, a window, a number) and this module stays out of the way.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from fpl_grounded_assistant import query_contract as contract
from fpl_grounded_assistant.query_brakes import _club_mentions, _player_mentions, _words
from fpl_grounded_assistant.query_engine import COMPLETE
from fpl_grounded_assistant.query_spec import parse_spec
from fpl_grounded_assistant.query_tool import run_spec

#: Words that ask for the attack as a whole: no single statistic answers them.
_GENERAL = frozenset("ataque ofensiva ofensivo ofensivamente produccion rendimiento attack attacking offence "
                     "offense offensive output production perform performed performance xgi".split())
_GOALS = frozenset("gol goles goals goal scored score scoring".split())
_XG = frozenset({"xg"})
#: Words that state no constraint (accent-folded, as the brakes fold text).
_FILLER = frozenset("""
a al como cambia cambio cambiado compara comparar comparacion con de del el ella en entre equipo es esta estuvo
fue ha han hizo hace la las le les lo los me muestra mostrar que se sin su sus tal un una va ve y
and at change changed club compare comparison did do does for has have him his how in is it of on s show team the
their to was were when with without
""".split())


@dataclass(frozen=True)
class Detected:
    club: str                        # short code
    player: str                      # as written
    asked: frozenset[str]            # of {"general", "goals", "xg", "xgi"}


def detect(raw_text: str, bootstrap: Mapping[str, Any]) -> Detected | None:
    words = _words(raw_text)
    folded = [w.text for w in words]
    if not ({"con", "sin"} <= set(folded) or {"with", "without"} <= set(folded)):
        return None
    clubs = _club_mentions(raw_text, words, bootstrap)
    if any(m.kind != "club" for m in clubs) or len({i for m in clubs for i in m.ids}) > 1:
        return None
    used = {i for m in clubs for i in range(m.first, m.last)}
    # Only a name right after "con / sin / with / without" is the subject; any other leftover word stops us.
    players = [m for m in _player_mentions(raw_text, words, bootstrap, used)
               if m.first and folded[m.first - 1] in ("con", "sin", "with", "without")]
    if not players:
        return None
    team_of = {int(e["id"]): int(e["team"]) for e in bootstrap.get("elements") or []}
    wanted_team = clubs[0].ids[0] if clubs else None
    subjects: set[int] = set()
    for m in players:
        ids = [i for i in m.ids if wanted_team is None or team_of.get(i) == wanted_team]
        if len(ids) != 1:
            return None
        subjects.add(ids[0])
        used.update(range(m.first, m.last))
    if len(subjects) != 1:
        return None
    rest = {w for i, w in enumerate(folded) if i not in used}
    if rest - _FILLER - _GENERAL - _GOALS - _XG:
        return None
    asked = {kind for kind, vocabulary in (("general", _GENERAL), ("goals", _GOALS), ("xg", _XG)) if rest & vocabulary}
    if "xgi" in rest:
        asked.add("xgi")
    team = team_of[next(iter(subjects))]
    code = next(str(t["short_name"]) for t in bootstrap.get("teams") or [] if int(t["id"]) == team)
    return Detected(code, players[0].written, frozenset(asked))


def keeps(found: Detected, block: Mapping[str, Any]) -> bool:
    """Whether the model's own complete comparison already answers: only when the user asked for exactly one of
    goals or xG and that is what ran, over this player's with and without sets."""
    if block.get("state") != COMPLETE or found.asked not in ({"goals"}, {"xg"}):
        return False
    spec = block.get("spec") or {}
    metric = "team_goals" if found.asked == {"goals"} else "team_expected_goals"
    sets = (spec.get("match_set") or []) + (spec.get("compare_to") or [])
    return (spec.get("metric") == metric and spec.get("shape") == "comparison"
            and sorted(p["pred"] for p in sets) == ["player_absent", "player_played_60"])


_WORDS = {
    "es": {"metric": "Goles y xG por partido de {club}", "line": "xG por partido: {a} y {b}.",
           "xg_missing": "No puedo medir el xG de estos partidos; muestro solo los goles.",
           "xgi": "xGI es un dato de jugador: para el equipo muestro goles y xG"},
    "en": {"metric": "{club} goals and xG per match", "line": "xG per match: {a} and {b}.",
           "xg_missing": "I can't measure xG for these matches; I show goals only.",
           "xgi": "xGI is a player figure: for the team I show goals and xG"},
}


def _spec(metric: str, found: Detected) -> Any:
    return parse_spec({"shape": "comparison", "grain": "team", "metric": metric, "operator": "per_match",
                       "filters": [{"field": "club", "op": "eq", "value": found.club}],
                       "match_set": [{"pred": "player_played_60", "value": found.player}],
                       "compare_to": [{"pred": "player_absent", "value": found.player}]})


def answer(found: Detected, bootstrap: dict[str, Any], lang: str) -> dict[str, Any]:
    """The tool output of the default card: the goals comparison, with xG per match as its first note. A goals
    run that cannot complete (too few matches, no data) is served as it is: a data answer, never a question."""
    out = run_spec(_spec("team_goals", found), bootstrap, lang)
    block = out["query"]
    out["query_audit"]["detail"] = "default_with_without"
    if block["state"] != COMPLETE:
        return out
    words = _WORDS[lang]
    reading = block["reading"]
    part = next(p for p in reading["parts"] if p["kind"] == "metric")
    name = next((str(t["name"]) for t in bootstrap.get("teams") or [] if t["short_name"] == found.club), found.club)
    old = part["label"]
    part["label"] = words["metric"].format(club=name)
    reading["text"] = reading["text"].replace(old, part["label"], 1)
    block["comparison"]["metric_header"] = part["label"]
    if "xgi" in found.asked:
        reading["parts"].append({"kind": "note", "label": words["xgi"], "value": "xgi", "editable": False,
                                 "alternatives": [], "braked": False})
        reading["text"] += " · " + words["xgi"]
    xg = run_spec(_spec("team_expected_goals", found), bootstrap, lang)["query"]
    if xg["state"] == COMPLETE:
        a, b = (f"{side['label']} → {side['per_match_text']}" for side in xg["comparison"]["sides"])
        notes = [words["line"].format(a=a, b=b)]
        notes += [n for n in xg["notes"] if n == contract.TEXT[lang]["range"]]
    else:
        notes = [words["xg_missing"]]
    block["notes"] = notes + block["notes"]
    return out


__all__ = ["Detected", "answer", "detect", "keeps"]
