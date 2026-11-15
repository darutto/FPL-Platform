"""
fpl_grounded_assistant.question_lang
====================================
i18n S0 (D1 = B): which language the user wrote the QUESTION in, and how often
that disagrees with the selected locale.

Why it exists. The es orchestrator prompt is kept byte-identical (it still says
``respond_lang = user_lang``), so with the ES locale an English question can
still get English prose above Spanish cards. That is a documented exception,
not a fix; this module is how we find out how often it happens after launch.
If it is frequent, the decision moves to option A (force the locale in both
directions, with a Spanish regression run).

Deterministic on purpose -- a stopword-marker ratio, no model call, no Jev. Jev
is not used as a language classifier now; revisit only if an auto-switch is
built or option A is taken.

The counter is process-global and resets on restart, like ``telemetry``. The
audit log is the per-turn record, but it is ephemeral without a Railway volume,
so ``/healthz`` carries the running counts.
"""
from __future__ import annotations

import re
import threading
import unicodedata
from typing import Final, Literal

QuestionLang = Literal["es", "en", "unknown"]

#: Words that are frequent in one language and (nearly) absent in the other.
#: Short and closed: the question is a handful of words, so every marker has to
#: be unambiguous. Football proper nouns and English loanwords Spanish users
#: type (gameweek, captain, differential...) are deliberately NOT markers.
_ES_MARKERS: Final[frozenset[str]] = frozenset({
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "que", "qué",
    "y", "en", "es", "son", "por", "para", "con", "sin", "mi", "mis", "tu", "tus", "su",
    "se", "me", "te", "lo", "al", "como", "cómo", "cual", "cuál", "cuales", "cuáles",
    "quien", "quién", "quienes", "cuando", "cuándo", "donde", "dónde", "cuanto", "cuánto",
    "mejor", "mejores", "jornada", "jornadas", "debo", "debería", "deberia", "puedo",
    "quiero", "tengo", "hay", "más", "mas", "muy", "pero", "está", "esta", "este", "esto",
    "dame", "dime", "ponme", "cuántos", "cuantos", "ya", "sobre", "contra", "partido",
    "partidos", "jugador", "jugadores", "equipo", "plantilla", "capitán", "capitan",
    "fichar", "vender", "comprar", "cambiar", "mejorar", "ahora", "próxima", "proxima",
    "siguiente", "siguientes", "últimos", "ultimos", "hoy", "semana", "lesionados",
    "puntos", "tiene", "tienen", "precio", "goles", "asistencias", "delanteros", "defensas",
    "porteros", "baratos", "barato", "cuesta", "vale", "juega", "jugar", "tendrá", "tendra",
})
_EN_MARKERS: Final[frozenset[str]] = frozenset({
    "the", "an", "of", "is", "are", "was", "were", "be", "been", "to", "in", "on",
    "for", "with", "and", "or", "my", "your", "his", "her", "their", "this", "that",
    "these", "those", "who", "what", "which", "when", "where", "why", "how", "should",
    "can", "could", "would", "will", "do", "does", "did", "i", "me", "we", "you",
    "she", "they", "it", "has", "have", "had", "best", "better", "next", "last",
    "give", "show", "tell", "against", "about", "from", "any", "some",
    "get", "pick", "bring", "sell", "buy", "play", "worth", "good", "bad", "much",
    "many", "more", "most", "than", "if", "not", "yes", "please", "tonight",
    "price", "points", "goals", "assists", "cheap", "cheapest", "forwards", "defenders",
    "midfielders", "goalkeepers",
})

#: Below this many marker hits the sample is too small to call.
_MIN_HITS: Final[int] = 2
#: The winning side must hold at least this share of all marker hits.
_MIN_SHARE: Final[float] = 0.7

_WORD_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?", re.UNICODE)


def _strip_accents(word: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", word) if not unicodedata.combining(ch)
    )


_ES_FOLDED: Final[frozenset[str]] = frozenset(_strip_accents(w) for w in _ES_MARKERS)
#: Markers that exist in both languages once accents are folded ("a", "me", "no",
#: "mas"... ) would vote for both sides; drop them from the Spanish side so an
#: English "me"/"no" is not counted as Spanish.
_SHARED: Final[frozenset[str]] = _ES_FOLDED & frozenset(_EN_MARKERS)


def detect_question_lang(text: str | None) -> QuestionLang:
    """``"es"``, ``"en"`` or ``"unknown"`` for a question.

    ``unknown`` when there are too few marker words to call (a bare player name,
    ``/capitan Haaland``, ``@injuries``) or when neither side clearly wins.
    Slash-command and @resource tokens are ignored: they route, they say nothing
    about the language the user is thinking in.
    """
    if not text:
        return "unknown"
    es_hits = en_hits = 0
    for raw in _WORD_RE.findall(text.lower()):
        # Command/resource tokens: a leading '/' or '@' sits outside the regex.
        folded = _strip_accents(raw)
        if folded in _SHARED:
            continue
        if raw in _ES_MARKERS or folded in _ES_FOLDED:
            es_hits += 1
        elif raw in _EN_MARKERS:
            en_hits += 1
    total = es_hits + en_hits
    if total < _MIN_HITS:
        return "unknown"
    if es_hits / total >= _MIN_SHARE:
        return "es"
    if en_hits / total >= _MIN_SHARE:
        return "en"
    return "unknown"


class _LocaleMismatchCounter:
    """Process-global counts of (locale, question_lang) per turn."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}

    def record(self, locale: str, question_lang: QuestionLang) -> None:
        key = f"{locale}:{question_lang}"
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + 1

    def snapshot(self) -> dict[str, object]:
        """Counts by ``"<locale>:<question_lang>"`` plus the mismatch share.

        ``mismatch`` counts turns where the question language is KNOWN and
        differs from the locale; ``unknown`` turns are excluded from both the
        numerator and the denominator of ``mismatch_rate``.
        """
        with self._lock:
            counts = dict(self._counts)
        known = sum(n for k, n in counts.items() if not k.endswith(":unknown"))
        mismatch = sum(
            n for k, n in counts.items()
            if not k.endswith(":unknown") and k.split(":")[0] != k.split(":")[1]
        )
        return {
            "counts": counts,
            "known_turns": known,
            "mismatch": mismatch,
            "mismatch_rate": round(mismatch / known, 4) if known else None,
        }

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()


#: The one process-global instance, read by ``/healthz``.
locale_mismatch = _LocaleMismatchCounter()
