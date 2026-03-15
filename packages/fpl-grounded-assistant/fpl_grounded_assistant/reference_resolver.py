"""
fpl_grounded_assistant.reference_resolver
==========================================
Phase 4f: LLM-assisted reference resolution.

Provides a minimal LLM-based resolver that interprets follow-up questions —
including Spanish-language pronouns and elliptical references — and rewrites
them as canonical English questions for the deterministic backend.

Architecture
------------
::

    resolve_reference()
      ├── resolve_reference_llm()   ← LLM path (structured JSON extraction)
      │     └── LLM call → ReferenceResolution
      └── resolve_pronouns()        ← Phase 4e deterministic fallback
            └── regex substitution → resolved question

Design principles
-----------------
- The LLM **only** resolves references — it never answers FPL questions.
- All FPL facts (scores, rankings, player data) still come from the
  deterministic backend after reference resolution.
- Fallback is always safe: when the LLM is unavailable, fails, or returns
  low-confidence output, Phase 4e deterministic pronoun resolution is used.
- The resolution output is always inspectable (frozen dataclass).
- The resolver speaks to a dedicated system prompt kept separate from the
  presentation-layer ``SYSTEM_PROMPT`` in ``llm_layer.py``.

Resolution priority
-------------------
1. LLM resolution (when client available AND confidence ≥ threshold).
2. Deterministic pronoun substitution (Phase 4e ``resolve_pronouns()``).
3. Original question unchanged.

Follow-up patterns newly supported beyond Phase 4e
---------------------------------------------------
English::

    "And Salah?"               → explicit player + intent from context
    "What about him?"          → pronoun + intent from context
    "And him?"                 → pronoun + intent from context

Spanish::

    "¿Y él?"                   → pronoun (él = he) + intent from context
    "¿Y como capitán?"         → ellipsis + captain_score intent
    "¿Y Salah?"                → explicit player + intent from context
    "¿Lo comprarías?"          → unsupported (not an FPL tool)
    "¿Y el otro?"              → ambiguous → low confidence → deterministic fallback

Intentionally deferred
-----------------------
- Multi-player references ("him or Salah")
- Comparison intents ("who is better?")
- Long-term memory beyond bounded session history
- LLM-generated FPL answers (the backend remains authoritative)

Public API
----------
::

    from fpl_grounded_assistant import (
        ReferenceResolution,
        resolve_reference,
        resolve_reference_llm,
        build_resolver_prompt,
        RESOLVER_SYSTEM_PROMPT,
        _CONFIDENCE_THRESHOLD,
    )
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .conversation_state import ConversationState, resolve_pronouns
from .dispatcher import (
    INTENT_CAPTAIN_SCORE,
    INTENT_CURRENT_GAMEWEEK,
    INTENT_PLAYER_RESOLVE,
    INTENT_PLAYER_SUMMARY,
    INTENT_RANK_CANDIDATES,
)
from .llm_layer import DEFAULT_MODEL, _get_anthropic_client


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CONFIDENCE_THRESHOLD: float = 0.5
"""Minimum confidence for LLM resolution to take precedence over deterministic."""

_RESOLVER_MAX_TOKENS: int = 200
"""Maximum tokens for the resolver LLM response (JSON is compact)."""

_VALID_INTENTS: frozenset[str] = frozenset(
    {
        INTENT_CAPTAIN_SCORE,
        INTENT_PLAYER_SUMMARY,
        INTENT_PLAYER_RESOLVE,
        INTENT_RANK_CANDIDATES,
        INTENT_CURRENT_GAMEWEEK,
        "unsupported",
    }
)

_VALID_REFERENCE_SOURCES: frozenset[str] = frozenset(
    {"pronoun", "ellipsis", "explicit", "none"}
)

_VALID_LANGUAGES: frozenset[str] = frozenset({"en", "es", "unknown"})

# Maps intent constant → canonical English question template.
# Templates are chosen to match the deterministic router's prefix tables
# so they always route correctly without any special-casing.
_INTENT_TO_CANONICAL: dict[str, str] = {
    INTENT_CAPTAIN_SCORE:    "should I captain {player}",
    INTENT_PLAYER_SUMMARY:   "tell me about {player}",
    INTENT_PLAYER_RESOLVE:   "who is {player}",
    INTENT_RANK_CANDIDATES:  "top captains this week",
    INTENT_CURRENT_GAMEWEEK: "what is the current gameweek",
}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

RESOLVER_SYSTEM_PROMPT: str = (
    "You are a reference resolver for an FPL (Fantasy Premier League) assistant.\n"
    "Your ONLY task: analyze a follow-up question and output a structured JSON object.\n"
    "You do NOT answer FPL questions. You ONLY resolve references and detect intent.\n"
    "\n"
    "Output format — STRICT JSON only, no markdown, no explanation, no trailing text:\n"
    "{\n"
    '  "resolved_query": "<player name string, or null>",\n'
    '  "intent_guess": "<captain_score|player_summary|player_resolve|rank_candidates|current_gameweek|unsupported|null>",\n'
    '  "reference_source": "<pronoun|ellipsis|explicit|none>",\n'
    '  "confidence": <float 0.0..1.0>,\n'
    '  "language": "<en|es|unknown>"\n'
    "}\n"
    "\n"
    "Field rules:\n"
    "- resolved_query: player name being referenced (use context if needed). null if no player.\n"
    "- intent_guess: the FPL operation the user wants.\n"
    "  captain_score — captaincy or captain pick decision\n"
    "  player_summary — stats, form, or details about a player\n"
    "  player_resolve — who is this player? identity lookup\n"
    "  rank_candidates — list or rank multiple captain candidates\n"
    "  current_gameweek — which gameweek is it?\n"
    "  unsupported — not an FPL question (fitness, transfer, injury, etc.)\n"
    "  null — cannot determine intent\n"
    "- reference_source:\n"
    "  pronoun — he/him/his/her/they/él/ella/lo/le/etc used to refer to a player\n"
    "  ellipsis — player implied by context without being stated\n"
    "  explicit — player stated directly in the question\n"
    "  none — no player reference needed (gameweek, rank, etc.)\n"
    "- confidence: 0.0 = total uncertainty, 1.0 = certain\n"
    "- language: primary language of current_question (en/es/unknown)\n"
)


# ---------------------------------------------------------------------------
# ReferenceResolution dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReferenceResolution:
    """The output of a single reference resolution attempt.

    Attributes
    ----------
    resolved_query:
        The player name / entity extracted from the follow-up question,
        using conversation context if needed.  ``None`` if no player is
        referenced (e.g. gameweek or ranking questions).
    intent_guess:
        One of the ``INTENT_*`` constants, ``"unsupported"``, or ``None``
        if the intent could not be determined.
    reference_source:
        How the reference was resolved:

        ``"pronoun"``       — via pronoun (he/him/él/lo/etc)
        ``"ellipsis"``      — implied by context, not stated explicitly
        ``"explicit"``      — player stated directly in the question
        ``"none"``          — no player reference present
        ``"deterministic"`` — resolved by Phase 4e regex (fallback path)
    confidence:
        Float 0.0–1.0 indicating resolver confidence.
        ``1.0`` for deterministic regex matches; LLM-provided value otherwise.
    language:
        Detected language of the input question (``"en"``, ``"es"``,
        or ``"unknown"``).
    rewritten_question:
        Canonical English question ready for the deterministic backend.
        Equals the original question when no rewriting was performed.
    """

    resolved_query:     str | None
    intent_guess:       str | None
    reference_source:   str
    confidence:         float
    language:           str
    rewritten_question: str


# ---------------------------------------------------------------------------
# Pure helpers — fully testable without API
# ---------------------------------------------------------------------------

def build_resolver_prompt(
    question: str,
    state: ConversationState,
    history: list[tuple[str, str]] | None = None,
) -> str:
    """Build the JSON user-turn prompt for the LLM reference resolver.

    Pure function — no side effects, fully deterministic, no network access.

    Parameters
    ----------
    question:
        The raw user question (may be in any language).
    state:
        Current ``ConversationState``.
    history:
        Optional bounded recent history as ``(question_text, intent)`` pairs.
        At most the last 3 entries are included.

    Returns
    -------
    str
        JSON string suitable as the user message to the LLM resolver.

    Examples
    --------
    >>> s = ConversationState()
    >>> s.last_player_query = "Haaland"
    >>> build_resolver_prompt("should I captain him?", s)
    '{"current_question": "should I captain him?", "last_player": "Haaland"}'
    """
    payload: dict[str, Any] = {
        "current_question": question,
        "last_player": state.last_player_query,
    }
    if history:
        payload["recent_history"] = [
            {"question": q, "intent": intent}
            for q, intent in history[-3:]
        ]
    return json.dumps(payload, ensure_ascii=False)


def _parse_resolver_response(text: str) -> dict[str, Any] | None:
    """Parse and validate JSON from LLM resolver output.

    Returns ``None`` on any parse or validation failure — does not raise.

    Validates:
    - Valid JSON object
    - All five required keys present
    - ``intent_guess`` is within ``_VALID_INTENTS`` or ``None``
    - ``reference_source`` is within ``_VALID_REFERENCE_SOURCES``
    - ``confidence`` is numeric
    - ``language`` is within ``_VALID_LANGUAGES``
    """
    try:
        data = json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    required = {"resolved_query", "intent_guess", "reference_source", "confidence", "language"}
    if not required.issubset(data.keys()):
        return None

    if data["resolved_query"] is not None and not isinstance(data["resolved_query"], str):
        return None
    if data["intent_guess"] is not None and data["intent_guess"] not in _VALID_INTENTS:
        return None
    if data["reference_source"] not in _VALID_REFERENCE_SOURCES:
        return None
    if not isinstance(data["confidence"], (int, float)):
        return None
    if data["language"] not in _VALID_LANGUAGES:
        return None

    return data


def _build_canonical_question(
    resolved_query: str | None,
    intent_guess: str | None,
    original: str,
) -> str:
    """Construct a canonical English question from resolver output.

    Uses ``_INTENT_TO_CANONICAL`` templates where possible.  Falls back
    to ``"tell me about {player}"`` when intent is unknown but a player
    is available.  Returns *original* unchanged when no rewriting is
    possible.

    Parameters
    ----------
    resolved_query:
        Player name extracted by the resolver.  ``None`` if no player.
    intent_guess:
        ``INTENT_*`` constant, ``"unsupported"``, or ``None``.
    original:
        The original (possibly non-English) question — used as last resort.

    Returns
    -------
    str
        Canonical question ready for the deterministic router.

    Examples
    --------
    >>> _build_canonical_question("Haaland", "captain_score", "¿Y él?")
    'should I captain Haaland'
    >>> _build_canonical_question("Salah", None, "And Salah?")
    'tell me about Salah'
    >>> _build_canonical_question(None, "current_gameweek", "¿En qué jornada estamos?")
    'what is the current gameweek'
    """
    # No-player intents: canonical form needs no {player} placeholder
    if intent_guess in (INTENT_RANK_CANDIDATES, INTENT_CURRENT_GAMEWEEK):
        return _INTENT_TO_CANONICAL[intent_guess]

    # Player intents: construct canonical question from template
    if resolved_query:
        template = _INTENT_TO_CANONICAL.get(intent_guess or "", "")
        if template:
            return template.format(player=resolved_query)
        # Player known but intent unclear → summary is the safe default
        return f"tell me about {resolved_query}"

    # No player, no clear canonical form → return original unchanged
    return original


# ---------------------------------------------------------------------------
# LLM resolver
# ---------------------------------------------------------------------------

def resolve_reference_llm(
    question: str,
    state: ConversationState,
    *,
    client: Any = None,
    model: str = DEFAULT_MODEL,
    history: list[tuple[str, str]] | None = None,
) -> ReferenceResolution | None:
    """Attempt LLM-based reference resolution.

    Returns ``None`` when:

    - No LLM client is available (missing API key or ``anthropic`` package).
    - The LLM call raises.
    - The LLM output cannot be parsed or fails validation.

    Parameters
    ----------
    question:
        Raw user question (may be in any language).
    state:
        Current ``ConversationState``.
    client:
        Optional pre-built Anthropic client.  If ``None``, the function
        attempts to build one from ``ANTHROPIC_API_KEY``.
    model:
        Model identifier.  Defaults to ``DEFAULT_MODEL``.
    history:
        Bounded recent history as ``(question_text, intent)`` pairs.

    Returns
    -------
    ReferenceResolution | None
        ``None`` on any failure (safe — caller always falls back).
    """
    resolved_client = client or _get_anthropic_client()
    if resolved_client is None:
        return None

    prompt = build_resolver_prompt(question, state, history=history)
    try:
        message = resolved_client.messages.create(
            model=model,
            max_tokens=_RESOLVER_MAX_TOKENS,
            system=RESOLVER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = message.content[0].text.strip()
    except Exception:  # noqa: BLE001
        return None

    parsed = _parse_resolver_response(raw_text)
    if parsed is None:
        return None

    resolved_query: str | None = parsed["resolved_query"] or None
    intent_guess:   str | None = parsed["intent_guess"] or None
    confidence: float = float(max(0.0, min(1.0, parsed["confidence"])))
    language:   str   = parsed["language"]
    reference_source: str = parsed["reference_source"]

    rewritten = _build_canonical_question(resolved_query, intent_guess, question)

    return ReferenceResolution(
        resolved_query=resolved_query,
        intent_guess=intent_guess,
        reference_source=reference_source,
        confidence=confidence,
        language=language,
        rewritten_question=rewritten,
    )


# ---------------------------------------------------------------------------
# Unified resolver — LLM with deterministic fallback
# ---------------------------------------------------------------------------

def resolve_reference(
    question: str,
    state: ConversationState,
    *,
    client: Any = None,
    model: str = DEFAULT_MODEL,
    history: list[tuple[str, str]] | None = None,
) -> ReferenceResolution:
    """Unified reference resolver: LLM-first with Phase 4e deterministic fallback.

    Resolution priority
    -------------------
    1. LLM resolution — when a client is available AND ``confidence ≥ 0.5``.
    2. Deterministic pronoun substitution — Phase 4e ``resolve_pronouns()``.
    3. Original question unchanged.

    Always returns a ``ReferenceResolution`` — never raises.

    Parameters
    ----------
    question:
        Raw user question (may be in any language).
    state:
        Current ``ConversationState``.
    client:
        Optional Anthropic client.  If ``None``, the function attempts to
        build one from ``ANTHROPIC_API_KEY``.
    model:
        Model identifier.  Defaults to ``DEFAULT_MODEL``.
    history:
        Bounded recent history as ``(question_text, intent)`` pairs.

    Returns
    -------
    ReferenceResolution
        Always populated.  ``reference_source == "none"`` and
        ``rewritten_question == question`` when no resolution was performed.
    """
    # --- Path 1: LLM resolution ---
    llm_result = resolve_reference_llm(
        question, state, client=client, model=model, history=history
    )
    if llm_result is not None and llm_result.confidence >= _CONFIDENCE_THRESHOLD:
        return llm_result

    # --- Path 2: Deterministic pronoun resolution (Phase 4e fallback) ---
    resolved = resolve_pronouns(question, state)
    if resolved != question:
        return ReferenceResolution(
            resolved_query=state.last_player_query,
            intent_guess=None,
            reference_source="deterministic",
            confidence=1.0,
            language="en",
            rewritten_question=resolved,
        )

    # --- Path 3: No resolution — original question unchanged ---
    return ReferenceResolution(
        resolved_query=None,
        intent_guess=None,
        reference_source="none",
        confidence=0.0,
        language="en",
        rewritten_question=question,
    )
