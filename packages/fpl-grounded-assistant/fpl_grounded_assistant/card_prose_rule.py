"""A ranking card's prose must not print the card's rows again.

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
from typing import Any, Sequence

#: Audit enum: the rule fired and removed something.
REASON_ROWS_RESTATED = "rows_restated"

#: A list line without a marker only counts when it is short (a prose paragraph that
#: happens to name a player and a number is a sentence, handled by the sentence rule).
_SHORT_LINE = 90
#: A name and its value must sit this close in a sentence to be "beside" each other.
_BESIDE = 45
_MIN_ROWS = 3

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


@dataclass(frozen=True)
class Trim:
    text: str
    dropped_lines: int
    fired: bool


def trim_card_restatement(text: str, ranked: Sequence[dict[str, Any]], *, metric: str = "") -> Trim:
    """*text* without the blocks and sentences that reprint the card's rows.

    ``fired`` is False (and the text unchanged) when nothing matched. Never returns the
    rows' own values for a different player: a line must carry a player beside his own
    value to count.
    """
    rows = rows_from_ranked(ranked)
    if len(rows) < _MIN_ROWS or not text or not text.strip():
        return Trim(text, 0, False)
    strip_prices = metric not in ("now_cost", "price")

    lines = text.split("\n")
    n = len(lines)
    def _carries_a_value(line: str) -> bool:
        text = _fold(line)
        if strip_prices:
            text = _PRICE.sub(" ", text)
        return any(r.value.search(text) for r in rows)

    qualifies = [False] * n   # a card player beside his own value
    member = [False] * n      # qualifies, or a list-marked line that carries a card value (the prose spelled
    for idx, line in enumerate(lines):  # its player some other way: "Bruno Fernandes" for "B.Fernandes")
        if line.strip() and _is_listy(line):
            qualifies[idx] = bool(_hits(line, rows, strip_prices=strip_prices))
            member[idx] = qualifies[idx] or (
                bool(_LIST_MARK.match(line) or _TABLE_ROW.match(line)) and _carries_a_value(line)
            )

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
        players: set[int] = set()
        for i in run:
            players |= set(_hits(lines[i], rows, strip_prices=strip_prices))
        if len(run) < _MIN_ROWS or len(players) < _MIN_ROWS:
            continue
        for i in run:
            drop[i] = True
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
    out_lines: list[str] = []
    dropped = 0
    for idx, line in enumerate(lines):
        if drop[idx]:
            dropped += 1
            continue
        if not line.strip() or _LIST_MARK.match(line) or _TABLE_ROW.match(line):
            out_lines.append(line)
            continue
        kept: list[str] = []
        removed_any = False
        for sentence in _SENTENCE_SPLIT.split(line):
            hits = _hits(sentence, rows, strip_prices=strip_prices)
            folded = _PRICE.sub(" ", _fold(sentence)) if strip_prices else _fold(sentence)
            near = 0
            for i in hits:
                for npos in _name_positions(folded, rows[i]):
                    window = folded[max(0, npos - _BESIDE): npos + len(rows[i].name) + _BESIDE]
                    if rows[i].value.search(window):
                        near += 1
                        break
            if len(hits) >= _MIN_ROWS and near >= _MIN_ROWS:
                removed_any = True
                continue
            kept.append(sentence)
        if removed_any:
            dropped += 1
            if kept:
                out_lines.append(" ".join(kept))
        else:
            out_lines.append(line)

    if dropped == 0:
        return Trim(text, 0, False)
    result = "\n".join(out_lines)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return Trim(result, dropped, True)
