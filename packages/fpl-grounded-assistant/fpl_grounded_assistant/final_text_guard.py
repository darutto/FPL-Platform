"""
fpl_grounded_assistant.final_text_guard
=======================================
i106: nothing the user cannot read reaches them as the answer.

Production turns (2026-09-19) shipped, as ``final_text``, the literal render
of a failed ``web_fetch`` ("Error (fetch_failed): URL can't contain control
characters ...") and 4 KB of a news site's HTML ("Obtenido https://... (N
bytes).\\n<!DOCTYPE html>..."). Four terminal sites in the orchestrator let a
``render()`` be the last word (evaluator retry, normal, partial, no-text) and
the LLM synthesis can quote HTML or an error back too, so the check lives at
the ONE place every ``OrchestratorResult`` passes through
(``orchestrator.ask_orchestrated``), never per branch.

What is raw, and what is not
----------------------------
``Error (code): message`` is the catalogue's render for EVERY tool error --
``not_found``, ``unknown_metric`` (with suggestions), ``missing_argument`` --
and those lines are the hint the user needs. Turning them into a generic
sentence is the "visible -> less informative" pattern this repo forbids. The
rule is therefore by CODE and by CONTENT, not by a list of readable codes:

* a transport/infra code (``TRANSPORT_CODES``) always fires;
* any code fires when the message carries what no user can act on: a URL,
  a traceback, control characters, HTML tags;
* an HTML document opener, or the ``web_fetch`` dump header, fires whatever
  the text is;
* everything else shaped ``Error (code): message`` passes intact.

``looks_like_raw_payload`` is a pure classifier: it returns a closed reason
string or ``None``. What to say instead, and where the blocked text is kept
(``guarded_raw_answer_text`` -> audit), is the caller's.
"""
from __future__ import annotations

import re

from .catalogue import t as _t

__all__ = [
    "REASON_TRANSPORT_ERROR",
    "REASON_UNREADABLE_ERROR",
    "REASON_HTML_DOCUMENT",
    "REASON_WEB_FETCH_RENDER",
    "REASON_HTML_DENSE",
    "GUARD_REASONS",
    "TRANSPORT_CODES",
    "looks_like_raw_payload",
]

#: "Error (<transport code>): ..." -- the failure is the network/infra, not
#: the question, and the message is an exception's text, not catalogue prose.
REASON_TRANSPORT_ERROR = "transport_error"
#: "Error (<any code>): ..." whose message carries a URL, a traceback, control
#: characters or HTML -- unreadable whatever the code says.
REASON_UNREADABLE_ERROR = "unreadable_error"
#: A document opener (``<!DOCTYPE`` / ``<html``) within the first 2 KB.
REASON_HTML_DOCUMENT = "html_document"
#: The ``web_fetch`` render header: "Obtenido http... (N bytes)" + excerpt.
REASON_WEB_FETCH_RENDER = "web_fetch_render"
#: A long text whose character mass is mostly HTML tags.
REASON_HTML_DENSE = "html_dense"

GUARD_REASONS: frozenset[str] = frozenset({
    REASON_TRANSPORT_ERROR, REASON_UNREADABLE_ERROR, REASON_HTML_DOCUMENT,
    REASON_WEB_FETCH_RENDER, REASON_HTML_DENSE,
})

# Transport/infra codes: the tool never got to reason about the question
# (socket, HTTP, timeout, an uncaught exception, a store that would not open),
# so the message is an exception's text, never catalogue prose. Enumerated
# from ``"code":`` literals in fpl_grounded_assistant/*.py on 2026-09-21;
# ``http_error``/``timeout`` are kept for the provider layer's vocabulary.
TRANSPORT_CODES: frozenset[str] = frozenset({
    "fetch_failed",
    "network_error",
    "http_error",
    "timeout",
    "tool_exception",
    "search_failed",
    "parquet_read_failed",
    "pandas_unavailable",
    "bootstrap_invalid",
    "no_bootstrap",
    "squad_fetch_failed",       # get_my_squad: the FPL picks endpoint did not answer
    "orchestrator_exception",   # harness: the orchestrator itself raised
})

_ERROR_LINE_RE = re.compile(r"^\s*Error(?: \((?P<code>[A-Za-z0-9_\-]+)\)|:)\s*(?P<message>.*)", re.DOTALL)
# The orchestrator's own wrappers around a render(): the partial route's
# "Respuesta incompleta (<reason>): " and the no-text route's i96 notice.
# Both are looked under, never classified: the payload is what follows.
_INCOMPLETE_PREFIX_RE = re.compile(r"^\s*Respuesta incompleta \([^)]*\):\s*")
_HTML_DOCUMENT_RE = re.compile(r"<!DOCTYPE|<html", re.IGNORECASE)
_WEB_FETCH_RENDER_RE = re.compile(r"^\s*Obtenido https?://")
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^<>]{0,200}>")
_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_TRACEBACK_RE = re.compile(r"Traceback")
# C0 controls except \t \n \r, plus DEL: what a shell or a parser choked on.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

#: Only the opening of the text is scanned for a document opener; an answer
#: that mentions ``<html>`` in passing far down is not an HTML page.
_DOCUMENT_SCAN_CHARS = 2048
#: Below this length the density rule does not apply: a short answer with a
#: couple of ``<b>`` tags is markup, not a payload.
_DENSE_MIN_CHARS = 400
#: At least this many tags AND this share of the characters inside tags.
_DENSE_MIN_TAGS = 8
_DENSE_MIN_RATIO = 0.15


def _message_is_unreadable(message: str) -> bool:
    """A URL, a traceback, a control character or an HTML tag in an error line."""
    return bool(
        _URL_RE.search(message)
        or _TRACEBACK_RE.search(message)
        or _CONTROL_CHAR_RE.search(message)
        or _HTML_TAG_RE.search(message)
    )


def _strip_orchestrator_wrappers(text: str) -> str:
    """Return the body under the orchestrator's known render wrappers."""
    body = text
    for locale in ("es", "en"):
        notice = _t("orchestrator.raw_render_notice", locale)
        if notice and body.lstrip().startswith(notice):
            body = body.lstrip()[len(notice):].lstrip()
            break
    return _INCOMPLETE_PREFIX_RE.sub("", body, count=1)


def looks_like_raw_payload(text: str | None) -> str | None:
    """Return the reason *text* is a raw payload, or ``None`` when it reads as prose.

    Reasons are the closed set ``GUARD_REASONS``; the first matching rule wins
    in the order document opener, web_fetch header, error line (transport
    code, then unreadable content), tag density. The orchestrator's own
    wrappers ("Respuesta incompleta (...): ", the i96 notice) are looked
    under first. A readable catalogue error ("Error (not_found): ...")
    returns ``None``. Empty/None text is not a payload (the caller has its
    own fallback for "nothing").
    """
    if not text:
        return None
    text = _strip_orchestrator_wrappers(text)
    if _HTML_DOCUMENT_RE.search(text[:_DOCUMENT_SCAN_CHARS]):
        return REASON_HTML_DOCUMENT
    if _WEB_FETCH_RENDER_RE.match(text):
        return REASON_WEB_FETCH_RENDER
    m = _ERROR_LINE_RE.match(text)
    if m:
        code = m.group("code")
        if code in TRANSPORT_CODES:
            return REASON_TRANSPORT_ERROR
        if _message_is_unreadable(m.group("message")):
            return REASON_UNREADABLE_ERROR
        return None
    if len(text) >= _DENSE_MIN_CHARS:
        tags = _HTML_TAG_RE.findall(text)
        if len(tags) >= _DENSE_MIN_TAGS:
            tag_chars = sum(len(t) for t in tags)
            if tag_chars / len(text) >= _DENSE_MIN_RATIO:
                return REASON_HTML_DENSE
    return None
