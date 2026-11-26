"""The player zonal card's rows, for the card prose rule (card_prose_rule).

The card (``get_player_zonal_outlook``) lists every pending match with its zonal status.
A line restates a row only when it names that match's gameweek AND its opponent AND its
OWN status («**J12 vs Everton:** cruce favorable»). A line with another status, or without
one, is not a restatement here and stays.

What counts as "beyond the card" is the engine's six-word rule, after removing only what
the card shows: the gameweek, the opponent, the status wording, home/away, the zone names,
the share of his xG in them, the player and the clubs. Every other word counts.

Only blocks go (three or more rows); a single prose sentence is never removed here.
Pure: no I/O.
"""
from __future__ import annotations

import re
from typing import Any, Sequence

from .card_prose_rule import (
    _LIST_MARK, _TITLE_FILLER, Trim, _fold, _restates_title, trim_restatement,
)
from .zonal_weakness_tool import _SHORT_TO_UNDERSTAT

#: Other ways the prose writes a club, by FPL code.
_CLUB_ALIASES: dict[str, tuple[str, ...]] = {
    "MCI": ("man city",),
    "MUN": ("man utd", "man united"),
    "NFO": ("nottm forest", "nott m forest", "nottingham"),
    "TOT": ("spurs", "tottenham hotspur"),
    "NEW": ("newcastle",),
    "WOL": ("wolves",),
    "BHA": ("brighton and hove albion",),
    "WHU": ("west ham united",),
    "LEE": ("leeds united",),
}

# Status wording, on folded text. Order matters: "sin cruce favorable" is neutral, so the
# no-data and neutral phrases are taken out before looking for the favourable ones.
_LEAD = r"(?:(?:es|tiene|hay|un|una|a|an|is|has)\s+)*"
_MATCHUP = r"(?:cruce|matchup|emparejamiento)(?:\s+zonal)?"
_STATUS_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("no_data", re.compile(
        r"(?<![a-z])(?:sin datos(?:\s+zonales)?(?:\s+(?:del|sobre el)\s+rival)?|no hay datos(?:\s+del rival)?"
        r"|no(?:\s+zonal)?\s+data(?:\s+on the opponent)?)(?![a-z])")),
    ("neutral", re.compile(
        rf"(?<![a-z]){_LEAD}(?:(?:sin|no)\s+(?:hay\s+)?(?:un\s+)?(?:{_MATCHUP}\s+)?(?:claramente\s+)?"
        rf"(?:favorable|destacado|claro)|(?:{_MATCHUP}\s+)?(?:neutral|neutro|no destacado|poco favorable)"
        rf"|sin ventaja(?:\s+clara)?|nada destacado|no standout(?:\s+matchup)?|no(?:t)?\s+favou?rable(?:\s+matchup)?)"
        rf"(?![a-z])")),
    ("favorable", re.compile(
        rf"(?<![a-z]){_LEAD}(?:(?:{_MATCHUP}\s+)?(?:muy\s+)?(?:favorable|a favor)(?:\s+matchup)?"
        rf"|favou?rable(?:\s+matchup)?)(?![a-z])")),
)

_ZONE = (
    r"(?:(?:el|la|los|las|the)\s+)?(?:zona\s+)?(?:"
    r"(?:centro|central|carril central|lado izquierdo|lado derecho|banda izquierda|banda derecha|izquierda|derecha)"
    r"\s+(?:del|de la)\s+(?:area|frontal)(?:\s+del area)?"
    r"|(?:area|frontal)(?:\s+del area)?\s+(?:centro|central|izq(?:uierda|uierdo)?|der(?:echa|echo)?)"
    r"|(?:centre|center|left|right)\s+of\s+the\s+(?:box|area)"
    r"|(?:box|edge)\s+(?:centre|center|left|right)"
    r"|in box\s*/?\s*(?:central|left|right)|edge of box\s*/?\s*(?:central|left|right))"
)
#: "en el centro del área, donde genera el 89 % de su xG sin penalti"
_CARD_PHRASES: tuple["re.Pattern[str]", ...] = tuple(re.compile(p) for p in (
    r"(?<![a-z])(?:donde\s+)?(?:(?:el\s+)?(?:jugador\s+)?(?:genera|concentra|acumula|produce)\s+)?"
    r"(?:(?:con|el|un)\s+)*\d+(?:[.,]\d+)?\s*%\s*(?:de\s+su\s+xg(?:\s+sin\s+penalti)?)?",
    r"(?<![a-z])(?:where he (?:generates|gets) )?\d+(?:[.,]\d+)?\s*%\s*(?:of his (?:non penalty )?xg)?",
    rf"(?<![a-z])(?:(?:en|por|in|through|at)\s+)?{_ZONE}(?![a-z])",
    r"(?<![a-z])(?:(?:juega\s+)?(?:en\s+casa|fuera(?:\s+de\s+casa)?|como\s+(?:local|visitante)|de\s+(?:local|visitante))"
    r"|casa|local|visitante|at home|home|away)(?![a-z])",
    r"(?<![a-z])(?:vs\.?|contra|ante|frente a|against|v)(?![a-z])",
))
#: Title words of this card, besides the player's name.
_CARD_TITLE = "zonas zonal zonales cruce cruces proximos rivales partidos calendario jornadas zones matchups upcoming fixtures"


def _phrase(term: str) -> "re.Pattern[str]":
    return re.compile(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])")


def _gameweek(gw: int) -> "re.Pattern[str]":
    return re.compile(rf"(?<![a-z0-9])(?:jornada|fecha|gameweek|gw|j)\s*\.?\s*{gw}(?![0-9])")


def _clean(term: str) -> str:
    return " ".join(_fold(term).replace("'", "").split())


class ZonalRows:
    """One row per pending match on the card."""

    def __init__(
        self, card: Any, *, store_name: str = "", club_terms: Sequence[str] = (),
    ) -> None:
        self.fixtures = list(card.zonal.fixtures)
        self._opponents: list[tuple[list["re.Pattern[str]"], "re.Pattern[str] | None"]] = []
        for fx in self.fixtures:
            code = str(fx.opponent_short or "").upper()
            names = {_clean(fx.opponent), _clean(_SHORT_TO_UNDERSTAT.get(code, ""))}
            names |= set(_CLUB_ALIASES.get(code, ()))
            # The code is matched as written (upper case): "new" or "che" in prose is not a club.
            self._opponents.append((
                [_phrase(n) for n in names if n],
                re.compile(rf"(?<![A-Za-z]){re.escape(code)}(?![A-Za-z])") if code else None,
            ))
        player = {_clean(card.web_name), _clean(store_name), *(_clean(store_name).split()[-1:])}
        own = {_clean(card.team_short), _clean(_SHORT_TO_UNDERSTAT.get(str(card.team_short).upper(), ""))}
        aliases = {a for group in _CLUB_ALIASES.values() for a in group}
        terms = {t for t in (*player, *own, *aliases, *(_clean(t) for t in club_terms),
                             *(_clean(v) for v in _SHORT_TO_UNDERSTAT.values())) if t}
        self._terms = [_phrase(t) for t in sorted(terms, key=len, reverse=True)]
        self._title = f"{_CARD_TITLE} {_clean(card.web_name)} {_clean(store_name)}"

    def __len__(self) -> int:
        return len(self.fixtures)

    @staticmethod
    def _statuses(folded: str) -> "tuple[set[str], str]":
        """The statuses *folded* states, and *folded* without their wording."""
        found: set[str] = set()
        for status, pattern in _STATUS_PATTERNS:
            folded, n = pattern.subn(" ", folded)
            if n:
                found.add(status)
        return found, folded

    def hits(self, line: str) -> "set[int]":
        folded = _clean(line)
        statuses, _ = self._statuses(folded)
        found: set[int] = set()
        for i, fx in enumerate(self.fixtures):
            names, code = self._opponents[i]
            if (
                fx.status in statuses
                and _gameweek(fx.gameweek).search(folded)
                and (any(p.search(folded) for p in names) or (code is not None and code.search(line)))
            ):
                found.add(i)
        return found

    def bridges(self, line: str) -> bool:
        return False

    def residual_words(self, text: str) -> int:
        s = _clean(_LIST_MARK.sub("", text)).replace("|", " ")
        _, s = self._statuses(s)
        for fx in self.fixtures:
            s = _gameweek(fx.gameweek).sub(" ", s)
        for term in self._terms:
            s = term.sub(" ", s)
        for pattern in _CARD_PHRASES:
            s = pattern.sub(" ", s)
        return sum(1 for w in re.findall(r"[a-z0-9]+", s) if not w.isdigit() and w not in ("cruce", "zonal"))

    def sentence_restates(self, sentence: str) -> bool:
        return False

    def restates_title(self, text: str) -> bool:
        words = [w for w in re.findall(r"[a-z0-9]+", _fold(text)) if w not in _TITLE_FILLER]
        return bool(words) and _restates_title(text, self._title)


def trim_zonal_restatement(
    text: str, card: Any, *, store_name: str = "", club_terms: Sequence[str] = (),
) -> Trim:
    """*text* without a block that reprints the zonal card's match rows. *card* is the
    ``PlayerZonalCardMeta`` on screen."""
    return trim_restatement(text, ZonalRows(card, store_name=store_name, club_terms=club_terms))
