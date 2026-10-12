"""
news_es.py -- Spanish for the FPL ``news`` free text on the cards (i151c).

FPL's ``news`` is free English text, but in practice it is generated from a
handful of fixed templates. Leo's decision (option A): translate exactly the
known templates, and leave anything else in English, untouched.

All-or-nothing: a template that matches but contains a part we cannot render
(an unseen body part, an unknown month) is NOT translated -- the whole note
stays in English. A half-translated sentence is worse than a clean English one.

Presentation boundary only: the ``news`` field of the tool output / payload is
never changed; callers show ``translate_news(news) or news``.

Club names are proper nouns and are kept exactly as FPL writes them.
"""
from __future__ import annotations

import re

#: Body-part word as FPL writes it before " injury" -> the full Spanish noun
#: phrase (the preposition differs per entry, so the phrase is stored whole).
_INJURY_PHRASE: dict[str, str] = {
    "knee":        "Lesión de rodilla",
    "hamstring":   "Lesión de isquiotibiales",
    "unspecified": "Lesión sin especificar",
    "ankle":       "Lesión de tobillo",
    "thigh":       "Lesión de muslo",
    "back":        "Lesión de espalda",
    "calf":        "Lesión de gemelo",
    "foot":        "Lesión de pie",
    "leg":         "Lesión de pierna",
    "groin":       "Lesión de ingle",
    "shoulder":    "Lesión de hombro",
    "arm":         "Lesión de brazo",
    "achilles":    "Lesión del tendón de Aquiles",
    "shin":        "Lesión de espinilla",
    "muscular":    "Lesión muscular",
}

_MONTH_ABBR: dict[str, str] = {
    "jan": "ene", "feb": "feb", "mar": "mar", "apr": "abr", "may": "may",
    "jun": "jun", "jul": "jul", "aug": "ago", "sep": "sep", "oct": "oct",
    "nov": "nov", "dec": "dic",
}

_MONTH_FULL: dict[str, str] = {
    "january": "enero", "february": "febrero", "march": "marzo",
    "april": "abril", "may": "mayo", "june": "junio", "july": "julio",
    "august": "agosto", "september": "septiembre", "october": "octubre",
    "november": "noviembre", "december": "diciembre",
}

_INJURY = r"(?P<part>[A-Za-z]+) injury - "
_DATE = r"(?P<day>\d{1,2}) (?P<mon>[A-Za-z]{3})"
_CLUB = r"(?P<club>\S.*?)"

# (compiled pattern, renderer) -- first match wins; a renderer returning None
# means "matched the shape but not renderable" -> stay English.
_I = re.IGNORECASE


def _injury_head(m: "re.Match[str]") -> "str | None":
    return _INJURY_PHRASE.get(m.group("part").lower())


def _date_es(m: "re.Match[str]") -> "str | None":
    mon = _MONTH_ABBR.get(m.group("mon").lower())
    return f"{int(m.group('day'))} {mon}" if mon else None


def _r_chance(m):
    head = _injury_head(m)
    return f"{head} - {m.group('pct')}% de probabilidad de jugar" if head else None


def _r_unknown(m):
    head = _injury_head(m)
    return f"{head} - Fecha de regreso desconocida" if head else None


def _r_expected(m):
    head, date = _injury_head(m), _date_es(m)
    return f"{head} - Regreso previsto {date}" if head and date else None


def _club(m: "re.Match[str]") -> str:
    return re.sub(r"\s+", " ", m.group("club")).strip()


def _r_loan_season(m):
    return f"Cedido a {_club(m)} hasta final de temporada"


def _r_loan_until(m):
    mon = _MONTH_FULL.get(m.group("mon").lower())
    return f"Cedido a {_club(m)} hasta {mon}" if mon else None


def _r_permanent(m):
    return f"Ha fichado por {_club(m)} de forma permanente"


def _r_suspended(m):
    date = _date_es(m)
    return f"Suspendido hasta {date}" if date else None


_TEMPLATES = (
    (re.compile(rf"^{_INJURY}(?P<pct>\d{{1,3}})% chance of playing$", _I), _r_chance),
    (re.compile(rf"^{_INJURY}Unknown return date$", _I), _r_unknown),
    (re.compile(rf"^{_INJURY}Expected back {_DATE}$", _I), _r_expected),
    # "seaon" is a typo FPL ships in some loan notes; the trailing period too.
    (re.compile(rf"^has joined\s+{_CLUB} on loan for the rest of the sea(?:son|on)\.?$", _I),
     _r_loan_season),
    (re.compile(rf"^has joined\s+{_CLUB} on loan until (?P<mon>[A-Za-z]+)\.?$", _I),
     _r_loan_until),
    (re.compile(rf"^has joined\s+{_CLUB} permanently\.?$", _I), _r_permanent),
    (re.compile(rf"^Suspended until {_DATE}$", _I), _r_suspended),
)


def translate_news(news: "str | None") -> "str | None":
    """Return the Spanish text for a known FPL news template, else ``None``.

    ``None`` means "show the original, unchanged" (no template matched, or it
    matched but had a part we cannot render).
    """
    if not news:
        return None
    text = news.strip()
    for pattern, render in _TEMPLATES:
        m = pattern.match(text)
        if m is not None:
            return render(m)
    return None


def news_label(news: "str | None") -> str:
    """The text to show: the Spanish translation, or the original news."""
    return translate_news(news) or (news or "")
