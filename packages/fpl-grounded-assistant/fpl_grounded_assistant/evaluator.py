"""evaluator.py — second-layer quality judge for orchestrator responses.

Pure judge: returns approve/retry decisions; never rewrites primary output.
Always uses the cheapest model variant of the same provider as the primary
reasoner (per evaluator-provider mapping). Capped at 1 retry per turn.
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Any

from fpl_grounded_assistant.off_topic import is_off_topic_response

_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cheapest-model mapping per provider
# ---------------------------------------------------------------------------

_EVALUATOR_MODELS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai":    "gpt-4o-mini",
    "gemini":    "gemini-flash-latest",
    "deepseek":  "deepseek-chat",
}


# ---------------------------------------------------------------------------
# EvaluatorVerdict dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvaluatorVerdict:
    """Result of a single evaluator judge call.

    Attributes
    ----------
    approved:
        True when all axes pass (or when fail-open is triggered).
    grounded:
        Every factual claim cites a tool result. None when fail-open.
    complete:
        Answer addresses the user question fully. None when fail-open.
    safe:
        No off-topic content; player recommendations include status checks.
        None when fail-open.
    off_topic_score:
        Heuristic off-topic score from Layer D (0.0–1.0). 0.0 = fully on-topic;
        1.0 = fully off-topic. Populated even on fail-open (always 0.0 by default).
        The LLM SAFE axis is primary; this is the fail-safe tie-breaker.
    retry_feedback:
        One-sentence guidance for the primary LLM to fix the response.
        Populated only when approved=False.
    tokens_used:
        Total tokens consumed by the evaluator call (input + output).
        Zero on fail-open or when tokens cannot be extracted.
    """

    approved:        bool
    grounded:        bool | None = None
    complete:        bool | None = None
    safe:            bool | None = None
    retry_feedback:  str | None  = None
    tokens_used:     int         = 0
    off_topic_score: float       = 0.0


# ---------------------------------------------------------------------------
# Fail-open sentinel
# ---------------------------------------------------------------------------

_FAIL_OPEN = EvaluatorVerdict(
    approved=True,
    grounded=None,
    complete=None,
    safe=None,
    retry_feedback=None,
    tokens_used=0,
)


# ---------------------------------------------------------------------------
# Evaluator system prompt (agent-friendly, compressed, ≤250 tokens)
# ---------------------------------------------------------------------------

_EVALUATOR_SYSTEM_PROMPT: str = (
    "ROLE: FPL response quality judge. PRIORITY: catch ungrounded / incomplete / unsafe answers.\n"
    "\n"
    "EVALUATE on 3 axes (yes/no each):\n"
    "  GROUNDED  every factual claim cites a tool result (player stats, fixtures, news, etc.)\n"
    "  COMPLETE  answer addresses what the user asked (no missing parts)\n"
    "  SAFE      no off-topic content; no player recommendations missing minutes_played_season + status check; no OFF_TOPIC info\n"
    "            *** OFF-TOPIC RULE (strict): if the primary response contains content unrelated to\n"
    "            Fantasy Premier League or English football — recipes, math problems, weather,\n"
    "            general knowledge, programming help, politics, crypto, movies, music, homework —\n"
    "            flag SAFE=false with retry_feedback='Response strayed off-topic. Refuse politely\n"
    "            in user_lang and offer to help with FPL.' ***\n"
    "            Examples of off-topic content to flag: recipes (ingredients, cooking steps),\n"
    "            math problems (calculations, square roots, equations), weather forecasts,\n"
    "            general knowledge questions (history, science, geography), programming help,\n"
    "            anything not directly about FPL / English football / players / fixtures / chips /\n"
    "            transfers / gameweeks / team management.\n"
    "\n"
    "OUTPUT FORMAT (JSON, no prose):\n"
    '  {"grounded": true|false, "complete": true|false, "safe": true|false,\n'
    '   "retry_feedback": "<one-sentence specific guidance>" | null}\n'
    "\n"
    "RULES:\n"
    "  - If all 3 axes pass → retry_feedback = null\n"
    "  - If any axis fails → retry_feedback = ONE sentence telling primary what to fix\n"
    "  - Be strict on GROUNDED: claims like \"player X has good form\" without a tool call citing form data → not grounded\n"
    "  - Be strict on SAFE: a player recommendation without verified minutes_played_season > 0 → not safe\n"
    "  - Be strict on SAFE (off-topic): any response that answers or partially answers a non-FPL question → not safe\n"
    "  - Don't rewrite the answer. Only judge + feedback."
)


# ---------------------------------------------------------------------------
# User message builder
# ---------------------------------------------------------------------------

def _build_evaluator_user_message(
    question: str,
    primary_response: str,
    tool_calls: list[dict],
) -> str:
    """Build the user-turn message for the evaluator LLM call."""
    if tool_calls:
        lines = []
        for tc in tool_calls:
            name = tc.get("name", "unknown")
            args = tc.get("args", {})
            output = tc.get("output", {})
            status = output.get("status", "?") if isinstance(output, dict) else "?"
            # Brief args summary: first 60 chars of JSON repr
            args_brief = json.dumps(args)
            if len(args_brief) > 60:
                args_brief = args_brief[:57] + "..."
            lines.append(f"{name}({args_brief}) → {status}")
        tool_summary = "\n".join(lines)
    else:
        tool_summary = "(no tool calls)"

    return (
        f"USER ASKED: {question}\n"
        f"\n"
        f"PRIMARY ANSWERED: {primary_response}\n"
        f"\n"
        f"TOOL CALLS MADE:\n"
        f"{tool_summary}\n"
        f"\n"
        f"Judge. Output JSON only."
    )


# ---------------------------------------------------------------------------
# Provider-specific evaluation call
# ---------------------------------------------------------------------------

def _call_evaluator_anthropic(
    client: Any,
    model: str,
    user_message: str,
) -> tuple[str | None, int]:
    """Call Anthropic client.messages.create() and return (raw_text, tokens_used)."""
    try:
        response = client.messages.create(
            model=model,
            max_tokens=256,
            system=_EVALUATOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw_text: str | None = None
        for block in getattr(response, "content", []):
            if getattr(block, "type", None) == "text":
                raw_text = getattr(block, "text", None)
                break
        usage = getattr(response, "usage", None)
        tokens = 0
        if usage is not None:
            tokens = (getattr(usage, "input_tokens", 0) or 0) + (getattr(usage, "output_tokens", 0) or 0)
        return raw_text, tokens
    except Exception as exc:  # noqa: BLE001
        print(f"[evaluator] Anthropic call failed: {exc}", file=sys.stderr)
        return None, 0


def _call_evaluator_openai(
    client: Any,
    model: str,
    user_message: str,
) -> tuple[str | None, int]:
    """Call OpenAI client.chat.completions.create() and return (raw_text, tokens_used)."""
    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=256,
            messages=[
                {"role": "system", "content": _EVALUATOR_SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
        )
        choices = getattr(response, "choices", []) or []
        raw_text: str | None = None
        if choices:
            msg = choices[0].message
            raw_text = getattr(msg, "content", None)
        usage = getattr(response, "usage", None)
        tokens = 0
        if usage is not None:
            tokens = getattr(usage, "total_tokens", 0) or 0
        return raw_text, tokens
    except Exception as exc:  # noqa: BLE001
        print(f"[evaluator] OpenAI call failed: {exc}", file=sys.stderr)
        return None, 0


def _call_evaluator_gemini(
    client: Any,
    model: str,
    user_message: str,
) -> tuple[str | None, int]:
    """Call Gemini client.models.generate_content() and return (raw_text, tokens_used)."""
    try:
        full_prompt = _EVALUATOR_SYSTEM_PROMPT + "\n\n" + user_message
        response = client.models.generate_content(
            model=model,
            contents=full_prompt,
        )
        raw_text: str | None = None
        candidates = getattr(response, "candidates", []) or []
        if candidates:
            content = getattr(candidates[0], "content", None)
            parts = getattr(content, "parts", []) or []
            for part in parts:
                t = getattr(part, "text", None)
                if t:
                    raw_text = t
                    break
        if raw_text is None:
            raw_text = getattr(response, "text", None)
        usage = getattr(response, "usage_metadata", None)
        tokens = 0
        if usage is not None:
            tokens = (getattr(usage, "prompt_token_count", 0) or 0) + (getattr(usage, "candidates_token_count", 0) or 0)
        return raw_text, tokens
    except Exception as exc:  # noqa: BLE001
        print(f"[evaluator] Gemini call failed: {exc}", file=sys.stderr)
        return None, 0


def _call_evaluator_deepseek(
    client: Any,
    model: str,
    user_message: str,
) -> tuple[str | None, int]:
    """Call DeepSeek (OpenAI-compat) client and return (raw_text, tokens_used)."""
    # DeepSeek uses OpenAI-compatible API
    return _call_evaluator_openai(client, model, user_message)


# ---------------------------------------------------------------------------
# JSON parse → EvaluatorVerdict
# ---------------------------------------------------------------------------

def _parse_verdict(raw_text: str | None, tokens_used: int) -> EvaluatorVerdict | None:
    """Parse the LLM's JSON output into an EvaluatorVerdict.

    Returns None on failure (caller falls back to fail-open).
    """
    if not raw_text:
        return None
    text = raw_text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove first and last fence lines
        inner = []
        for i, line in enumerate(lines):
            if i == 0 and line.startswith("```"):
                continue
            if i == len(lines) - 1 and line.strip() == "```":
                continue
            inner.append(line)
        text = "\n".join(inner).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    grounded = data.get("grounded")
    complete = data.get("complete")
    safe     = data.get("safe")
    feedback = data.get("retry_feedback")

    # Coerce to bool safely
    def _to_bool(v: Any) -> bool | None:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "yes", "1")
        return None

    g = _to_bool(grounded)
    c = _to_bool(complete)
    s = _to_bool(safe)

    # If any coercion failed to produce a bool, return None for fail-open
    if g is None or c is None or s is None:
        return None

    all_pass = g and c and s
    retry_feedback = None if all_pass else (feedback if isinstance(feedback, str) and feedback else "Review grounding, completeness, and safety of the response.")

    return EvaluatorVerdict(
        approved=all_pass,
        grounded=g,
        complete=c,
        safe=s,
        retry_feedback=retry_feedback,
        tokens_used=tokens_used,
        off_topic_score=0.0,  # populated by evaluate_response after heuristic check
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_response(
    *,
    question: str,
    primary_response: str,
    tool_calls: list[dict],   # [{"name": str, "args": dict, "output": dict}, ...]
    provider: str,            # "anthropic" | "openai" | "gemini" | "deepseek"
    client: Any | None = None,
) -> EvaluatorVerdict:
    """Judge a primary response. Returns approve OR retry-with-feedback verdict.

    Pure mapping/judge. No state. No I/O beyond the LLM call.

    If ``client`` is None or evaluator-model invocation fails, returns
    APPROVED (fail-open). This preserves UX: a failing evaluator must
    NOT block a primary response from reaching the user.

    Parameters
    ----------
    question:
        The original user question.
    primary_response:
        The primary LLM's answer text to judge.
    tool_calls:
        List of dicts with keys: name, args, output.
    provider:
        Provider string: "anthropic", "openai", "gemini", or "deepseek".
    client:
        Optional LLM client. If None, returns fail-open verdict immediately.

    Returns
    -------
    EvaluatorVerdict
        approved=True if all axes pass (or fail-open).
        approved=False with retry_feedback if any axis fails.
    """
    if client is None:
        return _FAIL_OPEN

    model = _EVALUATOR_MODELS.get(provider, "claude-haiku-4-5-20251001")
    user_message = _build_evaluator_user_message(question, primary_response, tool_calls)

    try:
        if provider == "openai":
            raw_text, tokens = _call_evaluator_openai(client, model, user_message)
        elif provider == "gemini":
            raw_text, tokens = _call_evaluator_gemini(client, model, user_message)
        elif provider == "deepseek":
            raw_text, tokens = _call_evaluator_deepseek(client, model, user_message)
        else:
            # Default: anthropic
            raw_text, tokens = _call_evaluator_anthropic(client, model, user_message)
    except Exception as exc:  # noqa: BLE001
        print(f"[evaluator] unexpected error during provider call: {exc}", file=sys.stderr)
        return _FAIL_OPEN

    verdict = _parse_verdict(raw_text, tokens)
    if verdict is None:
        if raw_text is not None:
            print(f"[evaluator] could not parse JSON verdict from: {raw_text!r}", file=sys.stderr)
        return _FAIL_OPEN

    # ------------------------------------------------------------------
    # Layer D: heuristic off-topic tie-breaker (safety net only).
    # The LLM SAFE axis is primary. The heuristic fires only when the LLM
    # approved the response (SAFE=true) but the keyword ratio strongly
    # signals off-topic content (score > 0.7).
    # ------------------------------------------------------------------
    try:
        ot_flagged, ot_score, _ot_diag = is_off_topic_response(primary_response)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("[evaluator] heuristic off-topic check failed: %s", exc)
        ot_flagged, ot_score = False, 0.0

    _HIGH_CONFIDENCE_THRESHOLD = 0.7

    if verdict.safe is True and ot_score > _HIGH_CONFIDENCE_THRESHOLD:
        # LLM said safe but heuristic strongly disagrees — override.
        _LOG.debug(
            "[evaluator] heuristic overrides SAFE=true → SAFE=false (off_topic_score=%.2f)",
            ot_score,
        )
        verdict = EvaluatorVerdict(
            approved=False,
            grounded=verdict.grounded,
            complete=verdict.complete,
            safe=False,
            retry_feedback=(
                "Heuristic flagged off-topic content. Refuse off-topic; stay within FPL/football."
            ),
            tokens_used=verdict.tokens_used,
            off_topic_score=ot_score,
        )
    else:
        # No override — just populate off_topic_score.
        verdict = EvaluatorVerdict(
            approved=verdict.approved,
            grounded=verdict.grounded,
            complete=verdict.complete,
            safe=verdict.safe,
            retry_feedback=verdict.retry_feedback,
            tokens_used=verdict.tokens_used,
            off_topic_score=ot_score,
        )

    return verdict
