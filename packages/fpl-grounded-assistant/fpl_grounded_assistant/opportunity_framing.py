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
_ALLOWED_WORDS: frozenset[str] = frozenset({"transferencia", "transferencias"})

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
        idiom_spans = (
            {m.start(1) for m in _THREAT_IDIOM_RE.finditer(folded)} if stem == "peligr" else set()
        )
        for m in re.finditer(r"\b(" + re.escape(stem) + r"\w*)", folded):
            word = m.group(1)
            if word in _ALLOWED_WORDS:
                continue
            if m.start(1) in idiom_spans:
                continue
            hits.append(f"{stem}:{word}")
    return hits


def obeys_opportunity_framing(text: str) -> bool:
    """True when ``transaction_hits`` is empty."""
    return not transaction_hits(text)


__all__ = ["TRANSACTION_STEMS", "transaction_hits", "obeys_opportunity_framing"]
