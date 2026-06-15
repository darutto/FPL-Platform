"""
fpl_grounded_assistant.reference_resolver
==========================================
Phase 4f: LLM-assisted reference resolution.
Phase 5f: LLM-assisted comparison follow-up resolution.

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
- Long-term memory beyond bounded session history
- LLM-generated FPL answers (the backend remains authoritative)

Phase 5f comparison resolver
-----------------------------
``resolve_comparison_followup_llm()`` handles Spanish and elliptical comparison
follow-ups that the Phase 5c deterministic resolver cannot catch::

    "¿Y Salah?"        → compare {last_a} and Salah
    "¿Y Saka?"         → compare {last_a} and Saka
    "vs Saka"          → compare {last_a} and Saka
    "Or Saka?"         → compare {last_a} and Saka

The LLM ONLY extracts the new player name.  The comparison anchor (last_a) and
all FPL scoring always come from the deterministic backend.

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
        # Phase 5f: comparison follow-up resolver
        resolve_comparison_followup_llm,
        build_comp_resolver_prompt,
        COMP_RESOLVER_SYSTEM_PROMPT,
        _parse_comp_resolver_response,
    )

``ReferenceResolution`` fields include ``fallback_reason`` (Phase 4g):
``"llm_unavailable"`` when LLM was not used due to missing client/error/parse
failure; ``"low_confidence"`` when LLM returned but confidence < threshold;
``None`` when LLM succeeded or no resolution was attempted.
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
from .llm_layer import DEFAULT_MODEL, _PROVIDER
from .provider_client import ProviderNotAvailableError, get_provider


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
    fallback_reason:
        Why the LLM resolver was not used (Phase 4g):
        ``"llm_unavailable"`` — no client, LLM error, or parse failure
        ``"low_confidence"``  — LLM returned but confidence < threshold
        ``None``              — LLM was used (no fallback) or no resolution needed
    """

    resolved_query:     str | None
    intent_guess:       str | None
    reference_source:   str
    confidence:         float
    language:           str
    rewritten_question: str
    fallback_reason:    str | None = None


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


def _strip_markdown_fences(text: str) -> str:
    """Strip markdown code fences that Gemini sometimes wraps JSON in."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        inner = [l for l in lines[1:] if not l.strip().startswith("```")]
        stripped = "\n".join(inner).strip()
    return stripped


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
        data = json.loads(_strip_markdown_fences(text))
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
    try:
        provider = get_provider(_PROVIDER, client=client)
    except ProviderNotAvailableError:
        return None

    prompt = build_resolver_prompt(question, state, history=history)
    result = provider.call(
        model=model,
        system_prompt=RESOLVER_SYSTEM_PROMPT,
        user_message=prompt,
        max_tokens=_RESOLVER_MAX_TOKENS,
    )
    if result.error_code is not None or result.text is None:
        return None

    parsed = _parse_resolver_response(result.text)
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
        # LLM succeeded — fallback_reason remains None
        return llm_result

    # Determine why LLM was not used (for audit / debug)
    if llm_result is None:
        fallback_reason: str | None = "llm_unavailable"
    else:
        # llm_result is not None but confidence < threshold
        fallback_reason = "low_confidence"

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
            fallback_reason=fallback_reason,
        )

    # --- Path 3: No resolution — original question unchanged ---
    return ReferenceResolution(
        resolved_query=None,
        intent_guess=None,
        reference_source="none",
        confidence=0.0,
        language="en",
        rewritten_question=question,
        fallback_reason=fallback_reason,
    )


# ---------------------------------------------------------------------------
# Comparison follow-up resolver  (Phase 5f)
# ---------------------------------------------------------------------------

COMP_RESOLVER_SYSTEM_PROMPT: str = (
    "You are a comparison follow-up resolver for an FPL (Fantasy Premier League) assistant.\n"
    "Your ONLY task: detect if the question is a comparison follow-up and extract the new player name.\n"
    "You do NOT answer FPL questions. You ONLY resolve which player is being referenced.\n"
    "\n"
    "Context: the user previously compared last_comparison_a vs last_comparison_b.\n"
    "They may now be asking to compare last_comparison_a with a different player.\n"
    "\n"
    "Output format — STRICT JSON only, no markdown, no explanation:\n"
    "{\n"
    '  "is_comparison_followup": <true|false>,\n'
    '  "new_player": "<player name string, or null>",\n'
    '  "confidence": <float 0.0..1.0>,\n'
    '  "language": "<en|es|unknown>"\n'
    "}\n"
    "\n"
    "Field rules:\n"
    "- is_comparison_followup: true only if this is a short follow-up introducing a new player\n"
    "  to compare against last_comparison_a. False for full questions, unrelated questions, etc.\n"
    "- new_player: the new player (not last_comparison_a or last_comparison_b). null if none.\n"
    "- confidence: 0.0=uncertain, 1.0=certain.\n"
    "- language: en/es/unknown.\n"
    "\n"
    "Examples:\n"
    '  {"current_question":"\\u00bfY Salah?","last_comparison_a":"Haaland","last_comparison_b":"Saka"}\n'
    '  → {"is_comparison_followup":true,"new_player":"Salah","confidence":0.95,"language":"es"}\n'
    "\n"
    '  {"current_question":"vs Saka","last_comparison_a":"Haaland","last_comparison_b":"Salah"}\n'
    '  → {"is_comparison_followup":true,"new_player":"Saka","confidence":0.9,"language":"en"}\n'
    "\n"
    '  {"current_question":"should I captain Haaland","last_comparison_a":"Haaland","last_comparison_b":"Salah"}\n'
    '  → {"is_comparison_followup":false,"new_player":null,"confidence":0.99,"language":"en"}\n'
)
"""System prompt for the Phase 5f LLM comparison follow-up resolver."""

_COMP_RESOLVER_MAX_TOKENS: int = 100
"""Maximum tokens for the comparison resolver LLM response."""


def build_comp_resolver_prompt(
    question: str,
    state: "ConversationState",
) -> str:
    """Build the JSON user-turn prompt for the LLM comparison follow-up resolver.

    Pure function — no side effects, no network access.

    Parameters
    ----------
    question:
        Raw user question (may be in any language).
    state:
        Current ``ConversationState`` — must have ``last_comparison`` set.

    Returns
    -------
    str
        JSON string encoding ``current_question``, ``last_comparison_a``,
        and ``last_comparison_b``.
    """
    last_a, last_b = state.last_comparison if state.last_comparison else ("", "")
    payload: dict[str, Any] = {
        "current_question": question,
        "last_comparison_a": last_a,
        "last_comparison_b": last_b,
    }
    return json.dumps(payload, ensure_ascii=False)


def _parse_comp_resolver_response(text: str) -> "dict[str, Any] | None":
    """Parse and validate JSON from LLM comparison resolver output.

    Returns ``None`` on any parse or validation failure.

    Validates:
    - Valid JSON object
    - All four required keys present
    - ``is_comparison_followup`` is boolean
    - ``new_player`` is string or null
    - ``confidence`` is numeric
    - ``language`` is in ``_VALID_LANGUAGES``
    """
    try:
        data = json.loads(_strip_markdown_fences(text))
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    required = {"is_comparison_followup", "new_player", "confidence", "language"}
    if not required.issubset(data.keys()):
        return None

    if not isinstance(data["is_comparison_followup"], bool):
        return None
    if data["new_player"] is not None and not isinstance(data["new_player"], str):
        return None
    if not isinstance(data["confidence"], (int, float)):
        return None
    if data["language"] not in _VALID_LANGUAGES:
        return None

    return data


def resolve_comparison_followup_llm(
    question: str,
    state: "ConversationState",
    *,
    client: Any = None,
    model: str = DEFAULT_MODEL,
) -> "ReferenceResolution | None":
    """Attempt LLM-based comparison follow-up resolution.

    Handles Spanish and elliptical comparison follow-ups that the Phase 5c
    deterministic resolver does not cover (e.g. ``"¿Y Salah?"``, ``"vs Saka"``).

    Returns ``None`` when:

    - ``state.last_comparison`` is ``None`` — no comparison context to extend.
    - No LLM client is available (missing API key or ``anthropic`` package).
    - The LLM call raises.
    - The LLM output cannot be parsed or fails validation.
    - ``is_comparison_followup`` is ``False`` in the LLM response.
    - ``new_player`` is null in the LLM response.

    Parameters
    ----------
    question:
        Raw user question (may be in any language).
    state:
        Current ``ConversationState``.  ``last_comparison`` must be set.
    client:
        Optional pre-built Anthropic client.  If ``None``, the function
        attempts to build one from ``ANTHROPIC_API_KEY``.
    model:
        Model identifier.  Defaults to ``DEFAULT_MODEL``.

    Returns
    -------
    ReferenceResolution | None
        On success: ``rewritten_question = "compare {last_a} and {new_player}"``,
        ``reference_source = "comparison_followup_llm"``.
        ``None`` on any failure (safe — caller always falls back).
    """
    if not state.last_comparison:
        return None

    try:
        provider = get_provider(_PROVIDER, client=client)
    except ProviderNotAvailableError:
        return None

    prompt = build_comp_resolver_prompt(question, state)
    result = provider.call(
        model=model,
        system_prompt=COMP_RESOLVER_SYSTEM_PROMPT,
        user_message=prompt,
        max_tokens=_COMP_RESOLVER_MAX_TOKENS,
    )
    if result.error_code is not None or result.text is None:
        return None

    parsed = _parse_comp_resolver_response(result.text)
    if parsed is None:
        return None

    if not parsed["is_comparison_followup"]:
        return None

    new_player: str | None = parsed["new_player"] or None
    if new_player is None:
        return None

    confidence: float = float(max(0.0, min(1.0, parsed["confidence"])))
    language: str = parsed["language"]
    last_a = state.last_comparison[0]
    rewritten = f"compare {last_a} and {new_player}"

    return ReferenceResolution(
        resolved_query=new_player,
        intent_guess=None,
        reference_source="comparison_followup_llm",
        confidence=confidence,
        language=language,
        rewritten_question=rewritten,
    )
