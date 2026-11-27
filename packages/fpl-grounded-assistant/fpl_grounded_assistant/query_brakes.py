"""The three brakes and the year of a date, decided by code from the user's raw text (query layer, Amendment 4
§4.2).

    apply_brakes(spec, raw_text, bootstrap, today, lang, not_expressible=(), ambiguous=()) -> BrakeResult

``state`` is None when nothing brakes: ``spec`` (every ``since_date`` now with its year) can be run. Otherwise
the spec must not be run. *raw_text* is what the user typed, never a session or hint rewrite. *not_expressible*
and *ambiguous* are the model's own reports, as ``{"kind", "quote"}`` and ``{"quote"}``; a quote is a string or
a list of strings.

* **B1** a word for ownership *at that time* -> ``unsupported_constraint``; the nearest answer is today's.
* **B3** the spec asks for something not executable, or the model reports it -> ``unsupported_constraint``.
* **date** a year written in the text wins; with none, the latest such day on or before *today* inside the
  season. A past season is unsupported; a future or unplaceable date is asked about.
* **B2** a club or player named in the text and absent from the spec -> ``needs_clarification``, with chips
  that add it. A ``not_expressible`` quote that holds the name covers it ("contra el Arsenal" is B3's).

Nothing imports this module at runtime yet (query layer, PR 5).
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from football_intelligence.public_calendar import PL_CLUB_ALIASES
from fpl_player_registry import KNOWN_NICKNAMES, candidate_dicts, resolve_player_candidates

from fpl_grounded_assistant import query_catalogue as cat
from fpl_grounded_assistant.query_engine import NEEDS_CLARIFICATION, UNSUPPORTED, QueryResult
from fpl_grounded_assistant.query_spec import (PLAYER_PREDICATES, Filter, Predicate, QuerySpec, parse_date,
                                               unsupported_reasons)
from fpl_grounded_assistant.team_fixture_calendar import _TEAM_RESOLVE_ALIASES, _resolve_team_result

#: B1: ownership as it was then (Amendment 3). "then" / "entonces" used as "so" count too: a known cost.
THEN_WORDS = ("en ese momento", "en aquel momento", "por aquel entonces", "entonces", "cuando empezo",
              "at that time", "at the time", "back then", "then")

#: Short forms people type that neither alias table has, as in the probe.
_EXTRA_CLUB_ALIASES = {"city": "MCI", "forest": "NFO", "nottingham": "NFO", "hull": "HUL", "gunners": "ARS",
                       "toffees": "EVE", "cherries": "BOU", "magpies": "NEW"}
#: Three-letter codes that cannot be mistaken for words in any case. The others ("new", "sun", "che", "eve",
#: "liv", "lee") count only when typed in capitals inside a text that is not all capitals.
_SAFE_CODES = frozenset({"ars", "avl", "bha", "bou", "mci", "mun", "nfo"})
#: A bare word that names more than one club: no filter can settle it, so it is asked about.
_AMBIGUOUS_CLUB_WORDS = ("united",)

#: Words of ordinary Spanish or English that are also a player's name. Alone, each counts as a name only when
#: capitalised in the middle of a sentence. Taken from the single words the resolver matches on the public
#: bootstrap of 2026-27, plus common surnames of the same kind.
COMMON_WORDS = frozenset("""
al ao bi con de del el en la lo mas mi no por que si sin son su tu un van
barco bendito blanco bueno campos casa costa gozo leon marco mata mina ola paz rey rico rio santos sol sosa toro
angel bard bell best black brown burn burns button cash cole cook dane destiny divine fox frank gray green grey
gross hall heaven hill honest king little long lucky mark may mills mount noble page pope porter promise reed
rice rose shepherd slater smith steele stones tel timber walker ward white will wood woodman wright young
""".split())

_MAX_NAME_WORDS = 4
_TOKEN = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class BrakeResult:
    spec: QuerySpec                              # years assigned
    state: str | None = None                     # None | unsupported_constraint | needs_clarification
    brake: str | None = None                     # B1 | B2 | B3 | date | ambiguous
    reason: str | None = None                    # enum, safe to audit
    unsupported: tuple[str, ...] = ()
    clarify: Mapping[str, Any] | None = None     # {kind, written, candidates}
    chips: tuple[Mapping[str, Any], ...] = ()    # {label, spec}
    unused: tuple[str, ...] = ()                 # reported beside a comparison that runs anyway

    def as_query_result(self) -> QueryResult:
        """The refusal in the engine's shape, so the reading line and the contract read one type."""
        if self.state is None:
            raise ValueError("nothing braked: run the spec")
        return QueryResult(self.state, self.spec, reason=self.reason, unsupported=self.unsupported,
                           clarify=self.clarify)


# --------------------------------------------------------------------------------------------------------- text

def _fold_char(char: str) -> str:
    decomposed = unicodedata.normalize("NFD", char)
    return (decomposed[0] if decomposed else char).lower()[:1] or char


def _fold(text: str) -> str:
    """Accent- and case-folded, the same length as *text*, so that spans line up."""
    return "".join(_fold_char(c) for c in text)


@dataclass(frozen=True)
class _Word:
    text: str                                    # folded
    start: int
    end: int


def _words(text: str) -> list[_Word]:
    return [_Word(m.group(0), m.start(), m.end()) for m in _TOKEN.finditer(_fold(text))]


def _key(name: str) -> tuple[str, ...]:
    return tuple(w.text for w in _words(name))


def _find(words: list[_Word], wanted: tuple[str, ...]) -> list[int]:
    n = len(wanted)
    return [i for i in range(len(words) - n + 1) if tuple(w.text for w in words[i:i + n]) == wanted] if n else []


#: A quote may skip this many words of the text, as the probe allows; skipped words are not covered.
_QUOTE_GAP = 3


def _quoted_words(words: list[_Word], items: Iterable[Mapping[str, Any]]) -> set[int]:
    """The indexes of the text's words that a ``not_expressible`` quote repeats, in order."""
    covered: set[int] = set()
    for item in items:
        quotes = item.get("quote")
        for quote in quotes if isinstance(quotes, list) else [quotes]:
            wanted = _key(quote) if isinstance(quote, str) else ()
            for first in (i for i, w in enumerate(words) if wanted and w.text == wanted[0]):
                matched, k = [], 0
                for j in range(first, min(len(words), first + len(wanted) + _QUOTE_GAP)):
                    if k < len(wanted) and words[j].text == wanted[k]:
                        matched.append(j)
                        k += 1
                if k == len(wanted):
                    covered.update(matched)
                    break
    return covered


# -------------------------------------------------------------------------------------------------------- clubs

@dataclass(frozen=True)
class _Mention:
    kind: str                                    # club | club_ambiguous | player
    first: int                                   # word indexes, [first, last)
    last: int
    written: str
    ids: tuple[int, ...]                         # team ids or element ids
    candidates: tuple[Mapping[str, Any], ...] = ()


def _club_aliases(bootstrap: Mapping[str, Any]) -> dict[tuple[str, ...], int]:
    """Every way of writing one of the bootstrap's clubs -> its team id. Codes are handled apart."""
    teams = list(bootstrap.get("teams") or [])
    by_code = {str(t["short_name"]).upper(): int(t["id"]) for t in teams}
    out: dict[tuple[str, ...], int] = {_key(str(t["name"])): int(t["id"]) for t in teams}
    for alias, code in list(_TEAM_RESOLVE_ALIASES.items()):
        if code.upper() in by_code:
            out.setdefault(_key(alias), by_code[code.upper()])
    for code, names in PL_CLUB_ALIASES.items():
        if code in by_code:
            for name in names:
                out.setdefault(_key(name), by_code[code])
    for alias, code in _EXTRA_CLUB_ALIASES.items():
        if code in by_code:
            out.setdefault(_key(alias), by_code[code])
    return out


def _club_mentions(text: str, words: list[_Word], bootstrap: Mapping[str, Any]) -> list[_Mention]:
    aliases = _club_aliases(bootstrap)
    teams = {int(t["id"]): t for t in bootstrap.get("teams") or []}
    codes = {str(t["short_name"]).lower(): i for i, t in teams.items()}
    shouting = text == text.upper()
    found: list[_Mention] = []
    taken: set[int] = set()
    longest = max((len(k) for k in aliases), default=0)
    for size in range(longest, 0, -1):                      # longest first: "Leeds United" is not a bare "United"
        for i in range(len(words) - size + 1):
            span = range(i, i + size)
            if taken.intersection(span):
                continue
            key = tuple(words[j].text for j in span)
            surface = text[words[i].start:words[i + size - 1].end]
            team = aliases.get(key)
            if team is None and size == 1 and key[0] in codes:
                if key[0] in _SAFE_CODES or (surface.isupper() and not shouting):
                    team = codes[key[0]]
            if team is not None:
                found.append(_Mention("club", i, i + size, surface, (team,)))
                taken.update(span)
    for i, word in enumerate(words):
        if word.text in _AMBIGUOUS_CLUB_WORDS and i not in taken:
            ids = tuple(sorted({t for key, t in aliases.items() if word.text in key}))
            if ids:
                found.append(_Mention("club_ambiguous", i, i + 1, text[word.start:word.end], ids, tuple(
                    {"short_name": teams[t]["short_name"], "name": teams[t]["name"]} for t in ids)))
    return found


# ------------------------------------------------------------------------------------------------------ players

def _name_words(bootstrap: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    for element in bootstrap.get("elements") or []:
        for key in ("web_name", "first_name", "second_name"):
            out.update(_key(str(element.get(key) or "")))
    for aliases in KNOWN_NICKNAMES.values():
        for alias in aliases:
            out.update(_key(alias))
    return out


def _capitalised_mid_sentence(text: str, word: _Word) -> bool:
    before = text[:word.start].rstrip(" \"'«“(")
    return text[word.start].isupper() and bool(before) and before[-1] not in ".?!¿¡:\n"


def _resolve(written: str, bootstrap: Mapping[str, Any]) -> Any:
    """The deterministic player resolver, whole names and nicknames only: a prefix of an ordinary word is not
    a mention."""
    return resolve_player_candidates(written, list(bootstrap.get("elements") or []),
                                     list(bootstrap.get("teams") or []), allow_prefix=False,
                                     allow_substring=False)


def _player_mentions(text: str, words: list[_Word], bootstrap: Mapping[str, Any],
                     taken: set[int]) -> list[_Mention]:
    vocabulary = _name_words(bootstrap)
    taken = set(taken)
    found: list[_Mention] = []
    for size in range(_MAX_NAME_WORDS, 0, -1):
        for i in range(len(words) - size + 1):
            span = range(i, i + size)
            if taken.intersection(span) or any(
                    words[j].text not in vocabulary or words[j].text.isdigit() for j in span):
                continue
            if size == 1:
                word = words[i]
                if len(word.text) < 2 or (word.text in COMMON_WORDS and not _capitalised_mid_sentence(text, word)):
                    continue
            elif all(words[j].text in COMMON_WORDS for j in (i, i + size - 1)):
                continue
            written = text[words[i].start:words[i + size - 1].end]
            outcome = _resolve(written, bootstrap)
            if not outcome.matches:
                continue
            best = outcome.best_matches
            found.append(_Mention("player", i, i + size, written, tuple(m.record.id for m in best),
                                  tuple(candidate_dicts(best))))
            taken.update(span)
    return found


# --------------------------------------------------------------------------------------- what the spec covers

def _spec_players(spec: QuerySpec) -> list[str]:
    return [p.value for p in spec.match_set + (spec.compare_to or ()) if p.pred in PLAYER_PREDICATES]


def _spec_clubs(spec: QuerySpec) -> list[str]:
    out: list[str] = []
    for f in spec.filters:
        if f.field == "club":
            out += list(f.value) if isinstance(f.value, tuple) else [f.value]
    return out


def _covered(spec: QuerySpec, bootstrap: Mapping[str, Any]) -> tuple[set[int], set[int], set[tuple[str, ...]]]:
    """(team ids, element ids, names as written) the spec uses. A player predicate also covers his club: the
    engine reads only that club's matches."""
    team_of = {int(e["id"]): int(e["team"]) for e in bootstrap.get("elements") or []}
    teams: set[int] = set()
    for written in _spec_clubs(spec):
        outcome = _resolve_team_result(written, dict(bootstrap))
        if outcome["status"] == "ok":
            teams.add(int(outcome["team_data"]["id"]))
    players: set[int] = set()
    names: set[tuple[str, ...]] = set()
    for written in _spec_players(spec):
        names.add(_key(written))
        outcome = resolve_player_candidates(written, list(bootstrap.get("elements") or []),
                                            list(bootstrap.get("teams") or []), allow_substring=False)
        best = [m.record.id for m in outcome.best_matches]
        narrowed = [i for i in best if team_of.get(i) in teams] if teams else []
        players.update(narrowed or best)
        if len(narrowed or best) == 1:
            teams.add(team_of[(narrowed or best)[0]])
    return teams, players, names


# --------------------------------------------------------------------------------------------------------- chips

def _with_filter_club(spec: QuerySpec, short_name: str) -> dict[str, Any]:
    clubs = [f for f in spec.filters if f.field == "club" and f.op in ("eq", "in")]
    kept = [f for f in spec.filters if f not in clubs]
    named: list[str] = []
    for f in clubs:
        named += list(f.value) if isinstance(f.value, tuple) else [f.value]
    added = (Filter("club", "in", tuple(sorted(set(named + [short_name])))) if named
             else Filter("club", "eq", short_name))
    kept = sorted(kept + [added], key=lambda f: (cat.FILTER_FIELDS.index(f.field), f.op, str(f.value)))
    return replace(spec, filters=tuple(kept)).to_dict()


def _club_chips(spec: QuerySpec, mention: _Mention, bootstrap: Mapping[str, Any], lang: str) -> list[dict]:
    teams = {int(t["id"]): t for t in bootstrap.get("teams") or []}
    ask = {"es": "¿Solo del {club}?", "en": "Only {club}?"}[lang]
    return [{"label": ask.format(club=teams[i]["name"]), "spec": _with_filter_club(spec, teams[i]["short_name"])}
            for i in mention.ids]


def _player_chips(spec: QuerySpec, mention: _Mention, lang: str) -> list[dict]:
    """With / without him, when the spec can take one: one player condition, and a ranking over matches."""
    if (len(mention.ids) != 1 or spec.shape != "list" or _spec_players(spec)
            or cat.METRICS[spec.metric].group == "snapshot"):
        return []
    words = {"es": ("Con {name}", "Sin {name}"), "en": ("With {name}", "Without {name}")}[lang]
    out = []
    for label, pred in zip(words, ("player_played_60", "player_absent")):
        kept = tuple(p for p in spec.match_set if p.pred != "season")
        match_set = tuple(sorted(kept + (Predicate(pred, mention.written),),
                                 key=lambda p: (cat.PREDICATES.index(p.pred), str(p.value))))
        out.append({"label": label.format(name=mention.written),
                    "spec": replace(spec, match_set=match_set).to_dict()})
    return out


# ---------------------------------------------------------------------------------------------------------- year

#: "2026/27" and "2026-27" are season labels, not a year; "10/10/2025" holds one.
_YEAR = re.compile(r"(?<![0-9])20[0-9]{2}(?![0-9]|\s*[/-]\s*[0-9]{2}(?![0-9]|\s*[/-]))")


def season_start(bootstrap: Mapping[str, Any]) -> dt.date | None:
    """The day of the season's first deadline."""
    days = [str(e.get("deadline_time") or "")[:10] for e in bootstrap.get("events") or []]
    return min((dt.date.fromisoformat(d) for d in days if d), default=None)


def _date(year: int, month: int, day: int) -> dt.date | None:
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def _place(value: str, years: set[int], start: dt.date | None, today: dt.date) -> tuple[str, str | None]:
    """(``since_date`` value, problem). The model's year is used only if the text has it."""
    sent, month, day = parse_date(value)
    if years:
        if sent in years:
            year = sent
        elif len(years) == 1:
            year = next(iter(years))
        else:
            return value, "which_year"
        when = _date(year, month, day)
        if when is None:
            return value, "no_such_date"
        if start is not None and when < start:
            return when.isoformat(), "past_season"
        return when.isoformat(), "date_in_the_future" if when > today else None
    if start is not None:
        for year in (today.year, today.year - 1):
            when = _date(year, month, day)
            if when is not None and when <= today:
                return (when.isoformat(), None) if when >= start else (f"{month:02d}-{day:02d}",
                                                                       "date_outside_season")
    return f"{month:02d}-{day:02d}", "date_outside_season"


def assign_years(spec: QuerySpec, raw_text: str, bootstrap: Mapping[str, Any],
                 today: dt.date) -> tuple[QuerySpec, str | None]:
    """(the spec with its dates placed, the first problem or None)."""
    years = {int(y) for y in _YEAR.findall(raw_text)}
    start = season_start(bootstrap)
    problems: list[str] = []

    def placed(preds: tuple[Predicate, ...] | None) -> tuple[Predicate, ...] | None:
        if preds is None:
            return None
        out = []
        for p in preds:
            if p.pred == "since_date":
                value, problem = _place(p.value, years, start, today)
                if problem:
                    problems.append(problem)
                p = Predicate(p.pred, value)
            out.append(p)
        return tuple(out)

    done = replace(spec, match_set=placed(spec.match_set), compare_to=placed(spec.compare_to))
    return done, problems[0] if problems else None


# -------------------------------------------------------------------------------------------------------- brakes

#: Words that ask for the attack as a whole: no single statistic answers them.
GENERAL_WORDS = frozenset("ataque ofensiva ofensivo ofensivamente produccion rendimiento attack attacking offence "
                     "offense offensive output production perform performed performance xgi".split())
GOALS_WORDS = frozenset("gol goles goals goal scored score scoring".split())
XG_WORDS = frozenset({"xg"})
#: Words that state no constraint (accent-folded, as the brakes fold text).
FILLER_WORDS = frozenset("""
a al como cambia cambio cambiado compara comparar comparacion con de del el ella en entre equipo es esta estuvo
fue ha han hizo hace la las le les lo los me muestra mostrar que se sin su sus tal un una va ve y
and at change changed club compare comparison did do does for has have him his how in is it of on s show team the
their to was were when with without
""".split())


def _restricts_nothing(item: Mapping[str, Any]) -> bool:
    """Whether a report can sit unused beside a comparison without changing which matches or players it covers.
    Only ``single_value``, and ``player_attribute`` whose quote holds no word that could be a filter. Every other
    kind restricts the question, so the unrestricted comparison would answer another one."""
    if item["kind"] == "single_value":
        return True
    if item["kind"] != "player_attribute":
        return False
    quote = item.get("quote")
    text = " ".join(map(str, quote)) if isinstance(quote, list) else str(quote or "")
    said = {w.text for w in _words(text)}
    return bool(said) and said <= FILLER_WORDS | GENERAL_WORDS | GOALS_WORDS | XG_WORDS


def apply_brakes(spec: QuerySpec, raw_text: str, bootstrap: Mapping[str, Any], today: dt.date, lang: str,
                 not_expressible: Iterable[Mapping[str, Any]] = (),
                 ambiguous: Iterable[Mapping[str, Any]] = ()) -> BrakeResult:
    """An unsupported constraint wins over a question: asking could not make it answerable."""
    not_expressible, ambiguous = list(not_expressible), list(ambiguous)
    unknown = [i.get("kind") for i in not_expressible if i.get("kind") not in cat.UNSUPPORTED_KINDS]
    if unknown:
        raise ValueError("not_expressible has a kind outside the vocabulary")
    spec, date_problem = assign_years(spec, raw_text, bootstrap, today)
    # A comparison the engine can run is not cancelled by a report that restricts nothing: the reading line says
    # it was left unused. A kind with any restricting item brakes, as do code's own findings.
    unused: tuple[str, ...] = ()
    if spec.shape == "comparison" and not unsupported_reasons(spec):
        held = {str(i["kind"]) for i in not_expressible if not _restricts_nothing(i)}
        unused = tuple(dict.fromkeys(str(i["kind"]) for i in not_expressible if str(i["kind"]) not in held))
    words = _words(raw_text)

    then = any(_find(words, _key(w)) for w in THEN_WORDS)
    kinds = list(dict.fromkeys(
        (["ownership_then"] if then else []) + list(unsupported_reasons(spec))
        + [str(i["kind"]) for i in not_expressible if str(i["kind"]) not in unused]
        + (["past_season"] if date_problem == "past_season" else [])))
    if kinds:
        brake = "B1" if then else "date" if kinds == ["past_season"] and date_problem else "B3"
        chips: tuple = ()
        if then and kinds == ["ownership_then"] and any(f.field == "owned_now" for f in spec.filters):
            label = {"es": "Propiedad hoy (otra pregunta)", "en": "Ownership today (a different question)"}[lang]
            chips = ({"label": label, "spec": spec.to_dict()},)
        return BrakeResult(spec, UNSUPPORTED, brake, kinds[0], unsupported=tuple(kinds), chips=chips)

    if date_problem:
        return BrakeResult(spec, NEEDS_CLARIFICATION, "date", date_problem,
                           clarify={"kind": "date", "written": "", "candidates": ()})

    quoted = _quoted_words(words, not_expressible)
    clubs = _club_mentions(raw_text, words, bootstrap)
    taken = {i for m in clubs for i in range(m.first, m.last)}
    teams, players, names = _covered(spec, bootstrap)
    for m in sorted(clubs + _player_mentions(raw_text, words, bootstrap, taken), key=lambda m: m.first):
        if set(range(m.first, m.last)) <= quoted:
            continue
        if m.kind == "club" and teams.intersection(m.ids):
            continue
        if m.kind == "player":
            key = _key(m.written)
            if players.intersection(m.ids) or any(_find([_Word(w, 0, 0) for w in name], key) for name in names):
                continue
        chips = (_player_chips(spec, m, lang) if m.kind == "player" else _club_chips(spec, m, bootstrap, lang))
        kind = "missing_player" if m.kind == "player" else "missing_club"
        reason = "club_ambiguous" if m.kind == "club_ambiguous" else f"{kind}_in_spec"
        return BrakeResult(spec, NEEDS_CLARIFICATION, "B2", reason,
                           clarify={"kind": kind, "written": m.written, "candidates": m.candidates},
                           chips=tuple(chips))

    for item in ambiguous:
        quote = item.get("quote")
        written = " ".join(quote) if isinstance(quote, list) else str(quote or "")
        return BrakeResult(spec, NEEDS_CLARIFICATION, "ambiguous", "ambiguous_phrase",
                           clarify={"kind": "phrase", "written": written, "candidates": ()})
    return BrakeResult(spec, unused=unused)
