"""off_topic.py — heuristic off-topic detector for evaluator + audit.

Layer D in the off-topic defense stack:
- Layer A: web_fetch URL allowlist (P2.7)
- Layer B: SOURCE_SELECTION_PROMPT classifies OFF_TOPIC (P1.b)
- Layer C: TOOL_OUTPUT_TRUST framing (P1.f.1)
- Layer D: THIS module + evaluator SAFE-axis tightening (P4)

Pure functions. No LLM call, no I/O. Used by:
- evaluator.py — as a tie-breaker when LLM-judged SAFE is ambiguous.
- audit.py — as a post-hoc tag on audit entries for off-topic refusals.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Keyword sets
# ---------------------------------------------------------------------------

# Topic keywords that indicate the response IS about FPL/football.
# Pure positive signal: if these appear, the response is on-topic.
_FPL_TOPIC_KEYWORDS: frozenset[str] = frozenset({
    "fpl", "fantasy", "premier league", "premier", "gameweek", "gw",
    "captain", "transfer", "chip", "bench boost", "wildcard", "free hit",
    "triple captain", "differential", "ownership", "player", "team",
    "fixture", "fdr", "form", "xgi", "xg", "xa", "ict", "minutes",
    "goals", "assists", "clean sheet", "save", "bonus", "bps",
    "jornada", "jugador", "equipo", "partido", "calendario", "puntos",
    "rival", "alineación", "alineacion", "banca", "banquillo",
})

# Hard-negative signals — strong indication of off-topic content.
_OFF_TOPIC_KEYWORDS: frozenset[str] = frozenset({
    "recipe", "recipes", "cake", "cooking", "ingredients",
    "weather", "temperature", "forecast",
    "math", "matemática", "matematica", "calcula", "raíz cuadrada", "raiz cuadrada",
    "tarea", "homework",
    "election", "elección", "eleccion", "vote", "voto",
    "stock", "stocks", "crypto", "bitcoin",
    "movie", "película", "pelicula", "music", "música", "musica",
})

# Refusal signal phrases — indicate the response is refusing something.
_REFUSAL_PHRASES: tuple[str, ...] = (
    "no puedo ayudarte",
    "no puedo responder",
    "i can't help",
    "i cannot help",
    "i won't help",
    "no voy a",
    "no estoy",
    "out of scope",
    "off-topic",
    "fuera de mi ámbito",
    "fuera de mi ambito",
    "no es mi especialidad",
    "no es mi área",
    "no es mi area",
)

# Patterns that suggest the response is providing an answer (not just refusing).
_ANSWER_PATTERNS: tuple[str, ...] = (
    "the answer is",
    "la respuesta es",
    "el resultado es",
    "= ",
    "son ",
    "equals ",
    "resultado:",
    "answer:",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_off_topic_response(
    text: str,
    *,
    threshold: float = 0.5,
) -> tuple[bool, float, dict[str, int]]:
    """Heuristic: is the response text predominantly off-topic?

    Returns (is_off_topic, off_topic_score, diagnostic_counts).
    off_topic_score = off_topic_hits / (off_topic_hits + fpl_topic_hits + 1).
    Threshold default 0.5 — if more than half the topic signal is off-topic,
    classify as off-topic.

    NB: this is a coarse safety net, not the primary classifier. The LLM's
    SOURCE_SELECTION (Layer B) is primary. This catches LLM slippage.
    """
    if not text:
        return False, 0.0, {"fpl_hits": 0, "off_topic_hits": 0}

    lowered = text.lower()

    # Count keyword hits (each keyword counted at most once regardless of
    # how many times it appears — prevents one repeated word dominating the ratio).
    fpl_hits = sum(1 for kw in _FPL_TOPIC_KEYWORDS if kw in lowered)
    off_topic_hits = sum(1 for kw in _OFF_TOPIC_KEYWORDS if kw in lowered)

    diagnostic = {"fpl_hits": fpl_hits, "off_topic_hits": off_topic_hits}

    # Score: proportion of topic signal that is off-topic.
    # +1 denominator prevents division by zero and biases toward on-topic
    # when signal is weak (empty response with no keywords → score 0.0).
    score = off_topic_hits / (off_topic_hits + fpl_hits + 1)

    return score >= threshold, score, diagnostic


def contains_off_topic_solution(text: str) -> bool:
    """Stricter: does the response actually ANSWER an off-topic question?

    Catches the failure mode where the LLM correctly REFUSES the off-topic
    part but then ALSO answers it (e.g. "I won't help with math homework
    but the answer is 5"). True if both refusal language AND off-topic
    keywords + a likely answer pattern (numeric, list, etc.) are present.
    """
    if not text:
        return False

    lowered = text.lower()

    # Must have at least one refusal phrase.
    has_refusal = any(phrase in lowered for phrase in _REFUSAL_PHRASES)
    if not has_refusal:
        return False

    # Must have at least one off-topic keyword (the topic being refused).
    has_off_topic_kw = any(kw in lowered for kw in _OFF_TOPIC_KEYWORDS)
    if not has_off_topic_kw:
        return False

    # Must have an answer pattern suggesting the LLM provided the answer anyway.
    has_answer_pattern = any(pat in lowered for pat in _ANSWER_PATTERNS)
    return has_answer_pattern
