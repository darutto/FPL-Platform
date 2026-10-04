"""
fpl_grounded_assistant.opportunity_framing
==========================================
The product rule "opportunity signal only -- never buy/sell advice", as a
function the tests and the measurements can run over a REAL answer text.

Until i93 the rule lived only in tool descriptions and in the system prompt
(``get_zonal_opportunity``: "Opportunity signal only — never buy/sell
advice."). An instruction is not evidence: nothing checked that the text the
user actually received obeyed it. This module is the check. It is used by

* ``tests/test_i93_fixture_cell_composed_analysis.py`` -- a synthesis text
  that uses the forbidden vocabulary on purpose must be caught;
* ``scripts/measure_i93_composed_content.py`` -- every measured answer_text is
  scanned and the count of hits is a reported number (the target is zero).

The list is CLOSED and small on purpose: transaction verbs (buy / sell /
transfer in-out) and urgency-or-danger framing, in Spanish and English, with
the inflections a Spanish synthesis actually produces. It is a denylist, so a
new phrasing goes unnoticed until someone adds it -- that is the accepted
trade-off for a rule that must never flag ordinary football prose
("tiene ventaja", "buen cruce"). Keep it a denylist; do not grow it into a
style checker.
"""
from __future__ import annotations

import re
import unicodedata

#: Stems of the forbidden vocabulary. Each is matched as a WHOLE-WORD PREFIX
#: (``\b<stem>\w*``) after accent stripping, so ``ficha`` catches "ficha",
#: "fichar", "fichalo", "fichaje", "fichajes" and ``vend`` catches "vende",
#: "vender", "véndelo". Kept as data so the measurement can report which
#: stem fired, not just that one did.
TRANSACTION_STEMS: tuple[str, ...] = (
    # Spanish: buy / sell / sign / transfer. Deliberately NOT "compr" / "fich"
    # / "compro": those prefix ordinary words (comprobar, comprender,
    # comprometido, fichero) and the rule must never flag honest prose.
    "compra", "compre", "vend", "ficha", "fiche", "traspas", "transfer",
    # Spanish: urgency / danger framing (the "peligro" rule of
    # feedback_opportunity_positive_framing)
    "urgent", "peligr",
    # English
    "buy", "sell", "sign him", "bring in", "get rid",
)

#: Whole words that are NOT hits even though a stem above would prefix them.
#: ``transferencia(s)`` is the noun for the FPL free-transfer mechanic itself
#: and appears legitimately in squad/chip answers; the composed match answer
#: must not name it either, but it is the squad tools' word and blocking it
#: globally would flag their honest output.
_ALLOWED_WORDS: frozenset[str] = frozenset({
    "transferencia", "transferencias",
    # i119: future/conditional of VENIR ("to come"), not VENDER ("to sell") --
    # vender's are venderia/vendera. The ``vend`` stem prefixes them. Measured
    # 2026-10-03 (i111 E3): "el beneficio principal vendría de Ndiaye" was
    # reported as a transaction. Folded forms; the list is the one decided in
    # review, nothing wider.
    "vendria", "vendrias", "vendriamos", "vendrian",
    "vendra", "vendras", "vendran", "vendre",
})

#: Football idiom, not danger framing: "generar/crear peligro" is the
#: Spanish for producing attacking threat -- the opposite of a warning.
#: Measured 2026-09-15 (i93 content run): the synthesis wrote "puede generar
#: peligro" for an attacking read 4 times in 60; flagging it would report a
#: positive-framing answer as a violation. Only these verb forms directly
#: before the word are exempt; "Peligro:", "es un peligro", "en peligro"
#: stay hits.
_THREAT_IDIOM_RE = re.compile(
    r"\b(?:gener(?:a|ar|an|e|en|ando|ado|aria|arian)|cre(?:a|ar|an|e|en|ando|ado|aria|arian))\s+"
    r"(?:mucho\s+|poco\s+|bastante\s+|mas\s+|menos\s+)?(peligr\w*)"
)

#: The noun "ficha" (a player's record card: "en su ficha", "la ficha de
#: Haaland") is not the verb "fichar" (to sign). Measured 2026-09-16 (i93-b
#: content run): 1 of 72 answers wrote "goles esperados concedidos
#: registrados en su ficha" and was reported as a transaction. Only the bare
#: noun form directly after a determiner/possessive/preposition is exempt;
#: "ficha a X" (verb), "fichar", "fichaje(s)", "fichan" stay hits.
_RECORD_CARD_RE = re.compile(
    r"\b(?:su|sus|la|las|una|esta|esa|de|en)\s+(fichas?)\b(?!\s+a\b)"
)


def _fold(text: str) -> str:
    """Lower-case, accent-stripped copy of *text* (é -> e, ñ -> n)."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def transaction_hits(text: str) -> list[str]:
    """Every forbidden term found in *text*, as ``stem:word`` pairs, in order.

    Empty list means the text obeys the rule. Matching is whole-word-prefix
    on the accent-folded text so it is robust to "véndelo" / "Fichaje" and
    never fires inside another word ("descompra" is not a word; "compras"
    is). Two-word stems ("bring in") are matched as a phrase.
    """
    folded = _fold(text or "")
    hits: list[str] = []
    for stem in TRANSACTION_STEMS:
        if " " in stem:
            if re.search(r"\b" + re.escape(stem) + r"\b", folded):
                hits.append(f"{stem}:{stem}")
            continue
        idiom_spans: set[int] = set()
        if stem == "peligr":
            idiom_spans = {m.start(1) for m in _THREAT_IDIOM_RE.finditer(folded)}
        elif stem == "ficha":
            idiom_spans = {m.start(1) for m in _RECORD_CARD_RE.finditer(folded)}
        for m in re.finditer(r"\b(" + re.escape(stem) + r"\w*)", folded):
            word = m.group(1)
            if word in _ALLOWED_WORDS:
                continue
            if m.start(1) in idiom_spans:
                continue
            hits.append(f"{stem}:{word}")
    return hits


#: i119 (decided by Leo, option C): an answer to a question that IS about
#: transfers -- a clarification for ad-05 «¿hago un transfer o guardo el
#: chip?» -- may name the mechanic neutrally («transfer», «¿qué jugador
#: venderías?»). What it may not do is push: urgency or danger. This is the
#: closed list that gate measures; ``transaction_hits`` stays the rule for the
#: composed chip / match answers. Matched on the folded text.
_URGENCY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("urgent", re.compile(r"\burgent\w*")),
    ("peligr", re.compile(r"\bpeligr\w*")),
    # a transaction verb pushed to "now": «vende ya», «véndelo cuanto antes»
    ("ya", re.compile(
        r"\b(?:vend|compra|ficha|traspas|saca|sacal|quita|deshaz)\w*\s+"
        r"(?:ya|ahora mismo|cuanto antes|de inmediato|inmediatamente|sin esperar)\b")),
    # obligation to get rid of / bring in: «hay que sacarlo», «tienes que venderlo»
    ("hay_que", re.compile(
        r"\b(?:hay que|tienes que|debes)\s+(?:vender|sacar|quitar|deshacerte|fichar|comprar)\w*")),
    ("en", re.compile(r"\b(?:sell|buy)\s+(?:him\s+|them\s+)?now\b|\bget rid\b|\bmust (?:sell|buy)\b")),
)


def urgency_hits(text: str) -> list[str]:
    """Urgency / danger framing in *text*, as ``label:match`` pairs, in order.

    The football idiom «generar/crear peligro» (attacking threat) is not a
    hit, as in ``transaction_hits``. Neutral transfer vocabulary is not a hit.
    """
    folded = _fold(text or "")
    idiom = {m.start(1) for m in _THREAT_IDIOM_RE.finditer(folded)}
    hits: list[tuple[int, str]] = []
    for label, pattern in _URGENCY_PATTERNS:
        for m in pattern.finditer(folded):
            if label == "peligr" and m.start() in idiom:
                continue
            hits.append((m.start(), f"{label}:{m.group(0)}"))
    return [h for _, h in sorted(hits)]


def obeys_opportunity_framing(text: str) -> bool:
    """True when ``transaction_hits`` is empty."""
    return not transaction_hits(text)


__all__ = ["TRANSACTION_STEMS", "transaction_hits", "urgency_hits", "obeys_opportunity_framing"]
