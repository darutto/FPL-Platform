"""
fpl_grounded_assistant.intent_classifier
=========================================
Phase 4k: LLM-Assisted Intent Classification.

Fires as a fallback ONLY when deterministic ``route()`` returns ``None``.
Produces a ``canonical_question`` that ``route()`` can re-parse
deterministically, preserving the full grounded backend pipeline.

Architecture
------------
::

    dispatch() tries route(question) first (always deterministic).
    If route() returns None AND a classifier_client is provided:
      1. classify_intent_llm(question, classifier_client) is called.
      2. If classification succeeds (confidence >= 0.7):
         a. canonical_question is fed back into route().
         b. If route(canonical_question) succeeds → use that route result.
         c. classification_source = "llm_classifier" on DispatchResult.
      3. On any failure (no client, parse error, low confidence, route miss):
         → fall through to OUTCOME_UNSUPPORTED_INTENT.

Key invariants
--------------
* The LLM classifies intent — it does NOT answer football questions.
* All player extraction still happens through ``_extract_player_query()`` in
  ``route()``.  The classifier only rewrites the question; it does not supply
  player data.
* Confidence threshold is 0.7 (stricter than reference resolver's 0.5 —
  classification errors cascade broader than resolution errors).
* Degrades silently: missing client, JSON parse errors, low confidence, or a
  canonical_question that still doesn't route all return ``None``.

Intentionally deferred
-----------------------
* Multi-intent classification ("Who is Salah and what gameweek is it?")
* Language-specific canonical templates beyond English
* Classifier fine-tuning or retrieval augmentation
"""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Confidence threshold
# ---------------------------------------------------------------------------

_CONFIDENCE_THRESHOLD: float = 0.7
"""Minimum confidence required to accept an LLM classification.

Below this threshold the classification is treated as unavailable and the
question is returned as unsupported via the normal deterministic path.
"""


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IntentClassification:
    """The output of a single ``classify_intent_llm()`` call.

    Attributes
    ----------
    intent:
        Predicted intent label — one of the six supported INTENT_* constants
        or ``"unsupported"`` when confidence is below threshold.
    canonical_question:
        A rephrased version of the original question in canonical English
        that ``route()`` can deterministically parse.  For example:
        ``"is Saka worth captaining?"`` → ``"should I captain Saka"``.
    confidence:
        Model-reported confidence (0.0–1.0).
    language:
        Detected ISO 639-1 language code of the original question
        (e.g. ``"en"``, ``"es"``).
    """
    intent:             str
    canonical_question: str
    confidence:         float
    language:           str


# ---------------------------------------------------------------------------
# Classifier system prompt
# ---------------------------------------------------------------------------

CLASSIFIER_SYSTEM_PROMPT: str = """\
You are an intent classifier for a Fantasy Premier League (FPL) assistant.

Your ONLY job is to map a natural-language user question to a supported intent
and produce a canonical English question that the deterministic router can
parse.  You must NOT answer the question, fetch data, or reason about football.
You ONLY rephrase and classify.

Supported intents and their canonical question templates
--------------------------------------------------------
captain_score:
  The user wants a captaincy score for a single named player.
  Canonical template: "should I captain {player_name}"
  Examples (English): "is Saka worth captaining?", "should Haaland be my captain?",
            "what's the captaincy outlook for De Bruyne?"
  Examples (Spanish): "¿debería capitar a Haaland?", "¿es buen capitán Salah esta semana?",
            "debería capitanear a Mbeumo"

rank_candidates:
  The user wants to rank a list of captaincy candidates (no specific player named).
  Canonical template: "top captains this week"
  Examples (English): "who looks best for captain?", "rank my captaincy options",
            "which of my players should captain this week?"
  Examples (Spanish): "¿a quién debería capitar esta semana?",
            "dame el ranking de capitanes para esta jornada",
            "¿quién debería ser mi capitán?", "¿quién debería capitanear?",
            "ranking de capitanes"

compare_players:
  The user wants a head-to-head comparison of exactly two named players.
  Canonical template: "compare {player_a} and {player_b}"
  Examples (English): "what's the score differential between Salah and Palmer?",
            "who has the better captain outlook, Haaland or Saka?",
            "Haaland or Salah for the armband?"
  Examples (Spanish): "compara a Haaland con Cherki en capitanía",
            "compara a Salah y Haaland"

player_summary:
  The user wants stats or an overview for a single named player.
  Canonical template: "tell me about {player_name}"
  Examples (English): "what's Palmer's form like?", "give me an overview of Haaland",
            "how is Saka doing this season?"
  Examples (Spanish): "dame un resumen de Salah", "¿cuántos puntos lleva Isak esta temporada?",
            "¿cómo está Mbeumo últimamente?", "información sobre Haaland",
            "precio de Palmer", "cual es el precio de Palmer"

player_resolve:
  The user wants to look up a player by name or alias.
  Canonical template: "who is {player_name}"
  Examples: "find the Liverpool number 11", "look up KDB"

transfer_advice:
  The user wants to know whether to sell one player and buy another.
  Canonical template: "should I sell {player_out} for {player_in}"
  Examples: "is Palmer worth bringing in for Saka?",
            "should I move Saka on for Palmer?",
            "would you swap Bruno for Foden this week?"

chip_advice:
  The user wants advice on whether to use an FPL chip this week.
  Chips: triple captain, wildcard, bench boost, free hit.
  Canonical template: "should I use {chip_name} this week"
    where chip_name is one of: triple captain, wildcard, bench boost, free hit.
  Examples (English): "is this a good week for triple captain?",
            "would you play the wildcard now?",
            "bench boost worth it this gameweek?",
            "should I activate my free hit?"
  Examples (Spanish — timing): "¿debería usar el wildcard antes o después de la doble jornada?",
            "¿cuándo debería usar el wildcard?",
            "¿cuándo debería activar el triple capitán?"
  Examples (Spanish — conditional): "¿tiene sentido activar el bench boost con 10 jugadores disponibles?",
            "¿vale la pena usar el bench boost ahora o guardarlo?",
            "¿me conviene activar el wildcard esta semana?"
  Examples (Spanish — spent-chip sequencing): "ya usé el wildcard, ¿qué chip me queda más rentable?",
            "ya gasté el wildcard, ¿cuándo uso el bench boost?",
            "no he usado ningún chip todavía, ¿cuál uso primero?"

current_gameweek:
  The user wants to know the current FPL gameweek number.
  Canonical template: "what gameweek is it"
  Examples: "what week are we on?", "which gw is this?", "what week in the season?"

player_fixture_run:
  The user wants to see a named player's upcoming fixture schedule.
  Canonical template: "{player_name} fixtures"
  Examples: "what are Haaland's upcoming games?", "how is Salah's schedule?",
            "does Palmer have easy fixtures coming up?",
            "what does De Bruyne's run look like?"

player_form:
  The user wants a player's recent match history or points over the last N gameweeks.
  Canonical template: "{player_name} last {N} games" or "historial de {player_name}"
  Examples (English): "how has Salah been in his last 3 games?",
            "what are Palmer's last 4 gameweek points?",
            "show me Haaland's recent stats"
  Examples (Spanish): "cómo ha estado Salah en los últimos 3 partidos",
            "cuántos puntos ha sacado Palmer en las últimas 4 jornadas",
            "dame las stats de los últimos 5 partidos de Cherki",
            "historial de puntos de Mbeumo"

injury_list:
  The user wants to know which players are injured or doubtful for the current GW.
  Canonical template: "injury list this week"
  Examples (English): "who is injured this week?", "which players are doubtful?",
            "injury doubts for this gameweek"
  Examples (Spanish): "hay dudas para esta jornada", "jugadores en duda esta semana",
            "quién está lesionado esta semana", "lista de bajas"

price_changes:
  The user wants to know which players' prices have risen or fallen in the current GW.
  Canonical template: "price risers this week"
  Examples (English): "who has gone up in price?", "price changes this week",
            "who has fallen in price?"
  Examples (Spanish): "quién está subiendo de precio esta semana",
            "quién ha bajado de precio últimamente",
            "jugadores que suben de precio"

team_fixture_calendar:
  The user wants a ranking of teams by upcoming fixture difficulty (easiest or hardest).
  Not about a single player's schedule — about all teams' schedules.
  Canonical template (easiest): "teams easiest fixtures next {N} gameweeks"
  Canonical template (hardest): "teams hardest fixtures next {N} gameweeks"
  Examples (English): "which teams have the best fixtures next 5 gameweeks?",
            "worst fixture run for teams this GW", "easiest fixture schedule ranking"
  Examples (Spanish): "que equipos tienen el mejor calendario las proximas 5 jornadas",
            "equipos con el peor calendario esta semana",
            "mejor calendario proximas 4 jornadas",
            "peores fixtures proximas 3 jornadas"

transfer_suggestion:
  The user wants ranked transfer targets for a specific position, optionally with a price ceiling.
  NOT about selling a player (transfer_advice). NOT about differentials. NOT about fixtures.
  Canonical template: "best {position} to buy [under {price}m]"
  Examples (English): "best midfielders to buy", "cheap forwards under 7.5",
            "who should I buy", "best defenders to transfer in under 6 million"
  Examples (Spanish): "mejores delanteros para fichar", "a quién fichar para el mediocampo",
            "mejores centrocampistas para comprar bajo 8 millones"

team_schedule:
  The user wants the upcoming fixtures for ONE specific club (not a ranking of all teams).
  Canonical template: "{team_name} fixtures next {N} gameweeks"
  Examples (English): "Arsenal fixtures next 5", "Liverpool schedule",
            "Chelsea upcoming fixtures next 3 gameweeks",
            "Spurs schedule next 3 gameweeks"
  Examples (Spanish): "calendario del Arsenal proximas 4 jornadas",
            "partidos del Liverpool proximas 5 jornadas",
            "fixtures del Chelsea proximas 3 jornadas"

unsupported:
  The question is outside the supported scope, or confidence in any supported
  intent is below 0.7.
  Canonical template: (use the original question unchanged)

Output format
-------------
Respond ONLY with a single JSON object. No prose, no markdown, no explanation.
{
  "intent": "<one of the intent names above>",
  "canonical_question": "<rephrased canonical English question>",
  "confidence": <float between 0.0 and 1.0>,
  "language": "<ISO 639-1 language code of the original question, e.g. 'en', 'es'>"
}

Rules
-----
1. If confidence < 0.7, set intent to "unsupported" and canonical_question
   to the original question unchanged.
2. The canonical_question must use the template form above so the deterministic
   router can parse it — include real player names extracted from the question.
3. Never hallucinate player names — only use names present in the original question.
4. Never add data, scores, or football knowledge — classification only.
5. For compare_players, both player names must appear in canonical_question.
"""


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_classifier_prompt(question: str) -> str:
    """Build the user-turn prompt for the LLM classifier.

    Pure function — no side effects, fully testable without API access.

    Parameters
    ----------
    question:
        The original unrouted user question.

    Returns
    -------
    str
        User-turn prompt ready to send to the LLM.
    """
    return f"Classify this FPL question:\n\n{question}"


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def _parse_classifier_response(text: str) -> IntentClassification | None:
    """Parse JSON from the classifier LLM response.

    Returns ``None`` on any parse or validation error.

    Parameters
    ----------
    text:
        Raw text returned by the LLM classifier.

    Returns
    -------
    IntentClassification | None
    """
    try:
        data = json.loads(text)
        return IntentClassification(
            intent=str(data["intent"]),
            canonical_question=str(data["canonical_question"]),
            confidence=float(data["confidence"]),
            language=str(data.get("language", "en")),
        )
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Gemini adapter — presents a messages.create() interface so classify_intent_llm
# works unchanged regardless of which LLM provider is active.
# ---------------------------------------------------------------------------

class GeminiClassifierAdapter:
    """Wraps google.generativeai to expose an Anthropic-compatible
    ``messages.create()`` interface used by ``classify_intent_llm()``.

    The passed ``model`` argument in ``create()`` is intentionally ignored;
    the Gemini model name supplied at construction time is always used.
    This keeps the caller (``classify_intent_llm``) unaware of the provider.
    """

    def __init__(self, genai_module: Any, api_key: str, model: str = "gemini-2.5-flash"):
        self._genai = genai_module
        self._api_key = api_key
        self._model_name = model
        self.messages = self   # client.messages.create(...) → self.create(...)

    def create(
        self,
        *,
        model: str,           # ignored — Gemini model set at construction
        max_tokens: int,
        system: str,
        messages: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> Any:
        user_content = messages[-1]["content"]
        # Use a higher token budget than what Anthropic needs: Gemini adds
        # markdown fences that consume tokens before the JSON payload starts.
        gemini_max_tokens = max(max_tokens * 2, 256)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._genai.configure(api_key=self._api_key)
            model_obj = self._genai.GenerativeModel(
                model_name=self._model_name,
                system_instruction=system,
                generation_config={"max_output_tokens": gemini_max_tokens},
            )
            response = model_obj.generate_content(user_content)

        # Strip markdown code fences that Gemini sometimes wraps JSON in.
        text = response.text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            # Drop the opening fence line and any closing fence
            inner = [l for l in lines[1:] if not l.strip().startswith("```")]
            text = "\n".join(inner).strip()

        class _Content:
            def __init__(self, t: str) -> None:
                self.text = t

        class _Message:
            def __init__(self, t: str) -> None:
                self.content = [_Content(t)]

        return _Message(text)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def classify_intent_llm(
    question: str,
    client: Any,
    *,
    model: str = "claude-haiku-4-5-20251001",
) -> IntentClassification | None:
    """Call the LLM to classify intent and produce a canonical question.

    Returns ``None`` when:

    * The client call raises any exception.
    * The LLM response cannot be parsed as valid JSON with required fields.
    * The parsed confidence is below ``_CONFIDENCE_THRESHOLD`` (0.7).

    Parameters
    ----------
    question:
        The original user question that ``route()`` could not handle.
    client:
        An Anthropic-compatible client with a ``.messages.create()`` method.
    model:
        Anthropic model identifier.  Defaults to ``claude-haiku-4-5-20251001``.

    Returns
    -------
    IntentClassification | None
        The classification result, or ``None`` if unavailable or low-confidence.

    Notes
    -----
    Callers should NOT call this function when ``route()`` already succeeds —
    it is exclusively a fallback for unrouted questions.
    """
    try:
        message = client.messages.create(
            model=model,
            max_tokens=128,
            system=CLASSIFIER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_classifier_prompt(question)}],
        )
        text = message.content[0].text.strip()
    except Exception:  # noqa: BLE001
        return None

    classification = _parse_classifier_response(text)
    if classification is None:
        return None

    if classification.confidence < _CONFIDENCE_THRESHOLD:
        return None

    return classification
