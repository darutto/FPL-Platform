"""A card's prose must not print the card's rows again.

One engine (``trim_restatement``) and one row matcher per card (``CardRows``): the ranking
table here (``RankingRows``), the player zonal card in ``card_prose_zonal``. What follows
is written for the ranking card; the block, comment, intro and heading rules are the
engine's and hold for every card.

The card (``rank_players_by_metric``) shows every row. The prompt already says so
(``CARD_NO_RESTATE``), but a prompt line is advice: on «mejores defensas de menos de
6 millones por puntos» the model wrote a numbered list of the card's rows
(«1. **De Cuyper** — Brighton, £5.5m: **76 puntos**»), the evaluator approved it, and
nothing in code looked at it. This module is the code-side rule. It runs on the FINAL
text of a turn whose single result is a ranking card, where the rows are on screen.

What it removes
---------------
* A BLOCK: three or more lines (numbered, bulleted, markdown-table rows, or consecutive
  short lines) that each carry a card player beside HIS OWN card value, naming three or
  more different players. The block goes, with its intro line when that line only
  introduces it (it ends in ``:``) and, for a table, its header and rule rows.
* A single SENTENCE that names three or more card players each beside his own value.

A line that also carries judgement is never deleted
-----------------------------------------------------
After removing the list marker, the card players' names, club names and codes, position
words, prices, the rows' values and their units, a line (a list item, a table row with a
comment column, or a sentence) with six or more words left says something the card does
not, and stays. The pure rows of the same block still go; if fewer than three pure rows
(three different players) remain, nothing of that block is dropped. A table with any
commented row is left whole (dropping some rows would break it), and the intro line stays
whenever a line of its block stays.

A heading that only names what went goes with it
-------------------------------------------------
A markdown heading, a bold-only line, or a plain line that restates the card's title, whose
list, table or sentences were removed with nothing of them left, is removed too when it says
nothing of its own: fewer than six words after the same count, or only words of the card's
title. A heading over prose that stays, or over a list with a line that stays, is kept.

What it never touches
---------------------
* Sentences with judgement that name players with no value beside them («Haaland lidera
  con claridad, seguido por Barry e Isak»), or one or two players with a value.
* Anything on a turn that is not a ranking card (the caller gates on that; this module
  only sees the rows it is given).

Values are matched in the card's own formats (``76``, ``76.0``, ``76 puntos``,
``82.0 %``); for a metric that is not a price, a price token (``£5.5m``, ``5.5m``) is
removed from the line before looking, so a price is never taken for the metric value.

Pure: no I/O, never raises on a text (``trim_card_restatement`` catches nothing itself;
the caller wraps it and sends the original text if anything goes wrong).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

#: Audit enum: the rule fired and removed something.
REASON_ROWS_RESTATED = "rows_restated"

#: A list line without a marker only counts when it is short (a prose paragraph that
#: happens to name a player and a number is a sentence, handled by the sentence rule).
_SHORT_LINE = 90
#: A name and its value must sit this close in a sentence to be "beside" each other.
_BESIDE = 45
_MIN_ROWS = 3
#: This many words left after removing what the card already shows is judgement, not a row.
_JUDGEMENT_WORDS = 6

#: Words that only label a row: positions and the units of the card's values (ES + EN).
_ROW_WORDS: frozenset[str] = frozenset(
    "portero porteros arquero arqueros defensa defensas defensor defensores lateral laterales central "
    "centrales mediocampista mediocampistas centrocampista centrocampistas volante volantes delantero "
    "delanteros atacante atacantes extremo extremos gkp gk def mid fwd goalkeeper goalkeepers defender "
    "defenders midfielder midfielders forward forwards striker strikers "
    "punto puntos pts pt points point gol goles goal goals asistencia asistencias assist assists minuto "
    "minutos minute minutes tarjeta tarjetas parada paradas save saves xg xa xgi bonus bps total totales".split()
)

_HEADING = re.compile(r"^\s*#{1,6}\s+")
_BOLD_LINE = re.compile(r"^\s*\*\*[^*]+\*\*\s*:?\s*$")
#: Words a title adds around what it names; with the card title's own words they make a restatement.
_TITLE_FILLER: frozenset[str] = frozenset(
    "top ranking clasificacion lista tabla los las el la de del por en con y a the of by in for and "
    "jugador jugadores player players temporada season mejores mejor best".split()
)

_LIST_MARK = re.compile(r"^\s*(?:\d{1,2}[.)]|[-*•])\s+")
_TABLE_ROW = re.compile(r"^\s*\|")
_PRICE = re.compile(r"[£€$]\s*\d+(?:[.,]\d+)?\s*(?:m\b|M\b|millones|millions)?|\b\d+(?:[.,]\d+)?\s*(?:m|M)\b")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().replace("*", "").replace("_", " ").replace("-", " ")


@dataclass(frozen=True)
class Row:
    """One card row, ready to match: the folded names it may be written as and the regex of its value."""

    names: tuple[str, ...]
    value: "re.Pattern[str]"

    @property
    def name(self) -> str:  # the primary (card) spelling
        return self.names[0]


def _name_variants(web_name: str) -> tuple[str, ...]:
    """How the prose may write a card name: the card's own, hyphen-insensitive, and the surname of an initial-form name.

    The card shows FPL's ``web_name`` ("B.Fernandes", "Gibbs-White"); the model writes the player's name in
    full ("Bruno Fernandes", "Gibbs White"). A surname alone is only accepted for the initial form
    ("B.Fernandes" -> "fernandes"): a bare common word must not become a name.
    """
    base = " ".join(_fold(web_name).replace("-", " ").split())
    variants = [base]
    m = re.match(r"^[a-z]\.\s*(.+)$", base)
    if m and len(m.group(1)) >= 4:
        variants.append(m.group(1))
    return tuple(dict.fromkeys(variants))


def _value_forms(value: float) -> list[str]:
    forms: list[str] = []
    if float(value) == int(value) and abs(value) < 1e9:
        iv = int(value)
        forms += [str(iv), f"{iv}.0", f"{iv}.00"]
    else:
        for digits in (1, 2, 3):
            forms.append(f"{value:.{digits}f}")
        forms.append(repr(float(value)))
    seen: list[str] = []
    for f in forms:
        if f not in seen:
            seen.append(f)
    return seen


def rows_from_ranked(ranked: Sequence[dict[str, Any]]) -> list[Row]:
    """The matchable rows of a ``rank_players_by_metric`` output (``ranked`` list)."""
    rows: list[Row] = []
    for entry in ranked or ():
        name = str(entry.get("web_name") or "").strip()
        value = entry.get("metric_value")
        if not name or not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        alt = "|".join(re.escape(f) for f in sorted(_value_forms(float(value)), key=len, reverse=True))
        pattern = re.compile(rf"(?<![\d.,])(?:{alt})(?![\d]|[.,]\d)")
        rows.append(Row(names=_name_variants(name), value=pattern))
    return rows


def _name_positions(folded: str, row: Row) -> list[int]:
    out: list[int] = []
    for variant in row.names:
        for m in re.finditer(rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])", folded):
            out.append(m.start())
    return sorted(out)


def _hits(line: str, rows: Sequence[Row], *, strip_prices: bool) -> dict[int, tuple[int, int]]:
    """Rows whose name AND own value both appear in *line*: {row index: (name pos, value pos)}."""
    text = _fold(line)
    if strip_prices:
        text = _PRICE.sub(" ", text)
    found: dict[int, tuple[int, int]] = {}
    for i, row in enumerate(rows):
        names = _name_positions(text, row)
        if not names:
            continue
        m = row.value.search(text)
        if m is None:
            continue
        found[i] = (names[0], m.start())
    return found


def _is_listy(line: str) -> bool:
    return bool(_LIST_MARK.match(line) or _TABLE_ROW.match(line) or len(line.strip()) <= _SHORT_LINE)


def _residual_words(text: str, rows: Sequence[Row], extra_terms: Sequence[str]) -> int:
    """How many words *text* says beyond what a card row shows (see the module docstring)."""
    s = _fold(_LIST_MARK.sub("", text)).replace("|", " ")
    s = _PRICE.sub(" ", s)
    for row in rows:
        for variant in row.names:
            s = re.sub(rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])", " ", s)
    for row in rows:
        s = row.value.sub(" ", s)
    for term in sorted({" ".join(_fold(t).split()) for t in extra_terms if t and str(t).strip()}, key=len, reverse=True):
        s = re.sub(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", " ", s)
    return sum(1 for w in re.findall(r"[a-z0-9]+", s) if not w.isdigit() and w not in _ROW_WORDS)


def _restates_title(text: str, card_title: str) -> bool:
    """True when every word of *text* is a word of the card's title or a title filler / row word."""
    title = {w for w in re.findall(r"[a-z0-9]+", _fold(card_title))}
    words = [w for w in re.findall(r"[a-z0-9]+", _fold(_HEADING.sub("", text))) if not w.isdigit()]
    named = [w for w in words if w in title and w not in _TITLE_FILLER]
    return bool(words) and bool(named) and all(w in title or w in _TITLE_FILLER or w in _ROW_WORDS for w in words)


class CardRows(Protocol):
    """What the engine asks about one card's rows."""

    def __len__(self) -> int: ...

    def hits(self, line: str) -> "set[int]":
        """The card rows *line* restates."""
        ...

    def bridges(self, line: str) -> bool:
        """A list line that joins a block of restating lines without being a hit itself."""
        ...

    def residual_words(self, text: str) -> int:
        """How many words *text* says beyond what the card shows."""
        ...

    def sentence_restates(self, sentence: str) -> bool:
        """One prose sentence that on its own reprints the card's rows."""
        ...

    def restates_title(self, text: str) -> bool:
        """*text* only names what the card is."""
        ...


def _is_title_line(line: str, card: CardRows) -> bool:
    if _LIST_MARK.match(line) or _TABLE_ROW.match(line):
        return False
    if _HEADING.match(line) or _BOLD_LINE.match(line):
        return True
    return len(line.strip()) <= _SHORT_LINE and card.restates_title(line)


def _drop_emptied_titles(lines: list[str], out: "list[str | None]", card: CardRows) -> int:
    """Set to None each title line whose content was removed entirely and that says nothing of its own."""
    titles = [i for i, line in enumerate(lines) if line.strip() and _is_title_line(line, card)]
    removed = 0
    for i in reversed(titles):                       # innermost first: a title over a removed title goes too
        if out[i] is None:
            continue
        gone = survivor = False
        for j in range(i + 1, len(lines)):
            if not lines[j].strip():
                continue
            if out[j] is None:
                gone = True
                continue
            if j in titles:
                break                                # the next section starts here
            item = bool(_LIST_MARK.match(lines[j]) or _TABLE_ROW.match(lines[j]))
            if item or not gone:
                survivor = True                      # part of the named list, or prose it heads, stays
            break
        if not gone or survivor:
            continue
        text = _HEADING.sub("", lines[i])
        if card.residual_words(text) < _JUDGEMENT_WORDS or card.restates_title(text):
            out[i] = None
            removed += 1
    return removed


@dataclass(frozen=True)
class Trim:
    text: str
    dropped_lines: int
    fired: bool


class RankingRows:
    """The rows of a ``rank_players_by_metric`` card: a player beside HIS OWN value."""

    def __init__(
        self, ranked: Sequence[dict[str, Any]], *, metric: str = "", extra_terms: Sequence[str] = (),
        card_title: str = "",
    ) -> None:
        self.rows = rows_from_ranked(ranked)
        self.strip_prices = metric not in ("now_cost", "price")
        #: Club names / codes: what the caller knows, plus the codes on the card itself.
        self.terms = [*extra_terms, *(str(e.get("team_short") or "") for e in ranked or ())]
        self.card_title = card_title

    def __len__(self) -> int:
        return len(self.rows)

    def _folded(self, text: str) -> str:
        folded = _fold(text)
        return _PRICE.sub(" ", folded) if self.strip_prices else folded

    def hits(self, line: str) -> "set[int]":
        return set(_hits(line, self.rows, strip_prices=self.strip_prices))

    def bridges(self, line: str) -> bool:
        # A list line that carries a card value: the prose spelled its player some other way
        # ("Bruno Fernandes" for "B.Fernandes").
        if not (_LIST_MARK.match(line) or _TABLE_ROW.match(line)):
            return False
        folded = self._folded(line)
        return any(r.value.search(folded) for r in self.rows)

    def residual_words(self, text: str) -> int:
        return _residual_words(text, self.rows, self.terms)

    def sentence_restates(self, sentence: str) -> bool:
        hits = self.hits(sentence)
        folded = self._folded(sentence)
        near = 0
        for i in hits:
            for npos in _name_positions(folded, self.rows[i]):
                window = folded[max(0, npos - _BESIDE): npos + len(self.rows[i].name) + _BESIDE]
                if self.rows[i].value.search(window):
                    near += 1
                    break
        return len(hits) >= _MIN_ROWS and near >= _MIN_ROWS

    def restates_title(self, text: str) -> bool:
        return _restates_title(text, self.card_title)


def trim_card_restatement(
    text: str, ranked: Sequence[dict[str, Any]], *, metric: str = "", extra_terms: Sequence[str] = (),
    card_title: str = "",
) -> Trim:
    """*text* without the blocks and sentences that reprint the ranking card's rows.

    ``fired`` is False (and the text unchanged) when nothing matched. Never returns the
    rows' own values for a different player: a line must carry a player beside his own
    value to count.
    """
    return trim_restatement(
        text, RankingRows(ranked, metric=metric, extra_terms=extra_terms, card_title=card_title),
    )


def trim_restatement(text: str, card: CardRows) -> Trim:
    """*text* without what reprints *card*'s rows (blocks, sentences, and the titles left empty)."""
    if len(card) < _MIN_ROWS or not text or not text.strip():
        return Trim(text, 0, False)

    lines = text.split("\n")
    n = len(lines)
    member = [False] * n      # restates a card row, or joins a block of lines that do
    for idx, line in enumerate(lines):
        if line.strip() and _is_listy(line):
            member[idx] = bool(card.hits(line)) or card.bridges(line)

    drop = [False] * n

    # --- blocks: runs of qualifying lines (blank lines between items do not break a run) ---
    non_blank = [i for i, l in enumerate(lines) if l.strip()]
    run: list[int] = []
    runs: list[list[int]] = []
    for i in non_blank:
        if member[i]:
            run.append(i)
        else:
            if run:
                runs.append(run)
            run = []
    if run:
        runs.append(run)
    for run in runs:
        named: set[int] = set()
        for i in run:
            named |= card.hits(lines[i])
        if len(run) < _MIN_ROWS or len(named) < _MIN_ROWS:
            continue
        commented = {i for i in run if card.residual_words(lines[i]) >= _JUDGEMENT_WORDS}
        pure = [i for i in run if i not in commented]
        pure_named: set[int] = set()
        for i in pure:
            pure_named |= card.hits(lines[i])
        if len(pure) < _MIN_ROWS or len(pure_named) < _MIN_ROWS:
            continue                                            # too few pure rows left: touch nothing
        if commented and any(_TABLE_ROW.match(lines[i]) for i in run):
            continue                                            # a table with a comment column stays whole
        for i in pure:
            drop[i] = True
        if commented:
            continue                                            # lines remain, so their intro remains too
        first, last = run[0], run[-1]
        if _TABLE_ROW.match(lines[first]):                      # header + rule rows of the same table
            j = first - 1
            while j >= 0 and (not lines[j].strip() or _TABLE_ROW.match(lines[j])):
                if lines[j].strip():
                    drop[j] = True
                j -= 1
            j = last + 1
            while j < n and _TABLE_ROW.match(lines[j]):
                drop[j] = True
                j += 1
        prev = first - 1                                        # the intro line, only when it just introduces
        while prev >= 0 and not lines[prev].strip():
            prev -= 1
        if prev >= 0 and not drop[prev] and lines[prev].rstrip().rstrip("*_ ").endswith(":"):
            drop[prev] = True

    # --- sentences: one sentence naming 3+ card players each beside his value ---
    out_lines: "list[str | None]" = []          # one slot per source line; None = removed
    dropped = 0
    for idx, line in enumerate(lines):
        if drop[idx]:
            dropped += 1
            out_lines.append(None)
            continue
        if not line.strip() or _LIST_MARK.match(line) or _TABLE_ROW.match(line):
            out_lines.append(line)
            continue
        kept: list[str] = []
        removed_any = False
        for sentence in _SENTENCE_SPLIT.split(line):
            if card.sentence_restates(sentence) and card.residual_words(sentence) < _JUDGEMENT_WORDS:
                removed_any = True
                continue
            kept.append(sentence)
        if removed_any:
            dropped += 1
            out_lines.append(" ".join(kept) if kept else None)
        else:
            out_lines.append(line)

    if dropped == 0:
        return Trim(text, 0, False)
    dropped += _drop_emptied_titles(lines, out_lines, card)
    result = "\n".join(line for line in out_lines if line is not None)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return Trim(result, dropped, True)
