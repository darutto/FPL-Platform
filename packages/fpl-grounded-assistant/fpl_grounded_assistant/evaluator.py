"""evaluator.py — second-layer quality judge for orchestrator responses.

Pure judge: returns approve/retry decisions; never rewrites primary output.
Always uses the cheapest model variant of the same provider as the primary
reasoner (per evaluator-provider mapping). Capped at 1 retry per turn.
"""
from __future__ import annotations

import json
import logging
import os
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
    "openai":    "gpt-5.6-luna",
    "gemini":    "gemini-3.5-flash",
    "deepseek":  "deepseek-chat",
}

#: Env var to override the evaluator model for ANY provider (e.g. when a model
#: is deprecated).  Empty/absent → per-provider default in _EVALUATOR_MODELS.
_EVAL_MODEL_ENV: str = "FPL_EVAL_MODEL"

#: i124: output-token budget per evaluator model. The verdict is a short JSON
#: object, so 256 was plenty for a model that writes straight away -- but the
#: gpt-5.6 family reasons first, and reasoning tokens are billed out of
#: ``max_output_tokens``. At 256 the JSON came back cut mid-string and the
#: turn fail-opened as approved: 5/10 prod verdicts on 2026-10-02, 10/45
#: locally, ~25% in the replay (field-notes/2026-10-03-i124-evaluator-replay.md).
#: Same lesson as the classifier's OPENAI_CLASSIFIER_MIN_OUTPUT_TOKENS.
#: Models not listed keep the historical 256.
_EVALUATOR_MAX_OUTPUT_TOKENS: dict[str, int] = {
    "gpt-5.6-luna":  1024,
    "gpt-5.6-terra": 1024,
    "gpt-5.6-sol":   1024,
}
_EVALUATOR_DEFAULT_MAX_OUTPUT_TOKENS: int = 256

#: Env var to override the evaluator's output budget for ANY model (e.g. a new
#: reasoning model before it has a table entry). Empty/absent/invalid → table.
_EVAL_MAX_OUTPUT_TOKENS_ENV: str = "FPL_EVAL_MAX_OUTPUT_TOKENS"


def _evaluator_max_output_tokens(model: str) -> int:
    """The output budget the evaluator call gets for *model*."""
    raw = os.environ.get(_EVAL_MAX_OUTPUT_TOKENS_ENV, "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return _EVALUATOR_MAX_OUTPUT_TOKENS.get(model, _EVALUATOR_DEFAULT_MAX_OUTPUT_TOKENS)


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
        Zero when tokens cannot be extracted. A fail-open after a call that
        ran keeps the tokens it spent (they were billed).
    fail_open_reason:
        i124: None on a real verdict. On a fail-open (approved=True with no
        judgment) one of FAIL_OPEN_REASONS, so "approved" is never read as a
        judgment it was not.
    """

    approved:        bool
    grounded:        bool | None = None
    complete:        bool | None = None
    safe:            bool | None = None
    retry_feedback:  str | None  = None
    tokens_used:     int         = 0
    off_topic_score: float       = 0.0
    fail_open_reason: str | None = None


# ---------------------------------------------------------------------------
# Fail-open sentinel
# ---------------------------------------------------------------------------

#: i124: why a verdict is a fail-open. Read off what came back, per call.
FAIL_OPEN_NO_CLIENT: str = "no_client"            # no evaluator client: nothing was called
FAIL_OPEN_PROVIDER_ERROR: str = "provider_error"  # the call raised / returned nothing, no tokens
FAIL_OPEN_EMPTY_OUTPUT: str = "empty_output"      # tokens were spent but no text came back
FAIL_OPEN_TRUNCATED_JSON: str = "truncated_json"  # a JSON object was started and cut off
FAIL_OPEN_UNPARSEABLE: str = "unparseable"        # complete text, but not a usable verdict
FAIL_OPEN_REASONS: frozenset[str] = frozenset({
    FAIL_OPEN_NO_CLIENT, FAIL_OPEN_PROVIDER_ERROR, FAIL_OPEN_EMPTY_OUTPUT,
    FAIL_OPEN_TRUNCATED_JSON, FAIL_OPEN_UNPARSEABLE,
})


def _fail_open(reason: str, tokens_used: int = 0) -> EvaluatorVerdict:
    """An approved verdict that judged nothing, saying why."""
    return EvaluatorVerdict(
        approved=True,
        grounded=None,
        complete=None,
        safe=None,
        retry_feedback=None,
        tokens_used=tokens_used,
        fail_open_reason=reason,
    )


#: Kept for importers; the reason-less sentinel of before i124.
_FAIL_OPEN = _fail_open(FAIL_OPEN_NO_CLIENT)


def _parse_failure_reason(raw_text: str | None, tokens_used: int) -> str:
    """Classify a reply ``_parse_verdict`` could not use."""
    text = (raw_text or "").strip()
    if not text:
        return FAIL_OPEN_EMPTY_OUTPUT if tokens_used > 0 else FAIL_OPEN_PROVIDER_ERROR
    body = text.strip("`").strip()
    if body.startswith("json"):
        body = body[4:].strip()
    if body.startswith("{") and not body.rstrip().endswith("}"):
        return FAIL_OPEN_TRUNCATED_JSON
    return FAIL_OPEN_UNPARSEABLE


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

#: i124 (C): key under which the orchestrator hands each tool call's MODEL
#: VIEW -- the payload the primary actually read (``orchestrator.
#: _truncate_tool_output``: lists capped, ``_MODEL_HIDDEN_FIELDS`` dropped).
#: Built there, not here: this module cannot import the orchestrator.
MODEL_VIEW_KEY: str = "model_view"


def _build_evaluator_user_message(
    question: str,
    primary_response: str,
    tool_calls: list[dict],
) -> str:
    """Build the user-turn message for the evaluator LLM call.

    i124 (C): the evaluator is told to be strict on GROUNDED ("every factual
    claim cites a tool result") but used to see only ``tool(args) -> status``
    -- it could verify nothing, rejected grounded answers asking to "cite",
    and the retry re-ran the same tool. Each call that carries a
    ``model_view`` now adds that payload under TOOL DATA, the same data the
    primary saw, so claims are checked against it. Measured offline first
    (field-notes/2026-10-03-i124-evaluator-replay.md): rejections 54% -> 32%
    of parsed verdicts, real defects still caught, one more caught.
    """
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

    data_lines = [
        f"{tc.get('name', 'unknown')} DATA: {json.dumps(tc[MODEL_VIEW_KEY], ensure_ascii=False, default=str)}"
        for tc in tool_calls or []
        if isinstance(tc.get(MODEL_VIEW_KEY), dict)
    ]
    data_block = (
        f"TOOL DATA (what the primary saw):\n" + "\n".join(data_lines) + "\n\n"
        if data_lines else ""
    )

    return (
        f"USER ASKED: {question}\n"
        f"\n"
        f"PRIMARY ANSWERED: {primary_response}\n"
        f"\n"
        f"TOOL CALLS MADE:\n"
        f"{tool_summary}\n"
        f"\n"
        f"{data_block}"
        f"Judge. Output JSON only."
    )


# ---------------------------------------------------------------------------
# Provider-specific evaluation call
# ---------------------------------------------------------------------------

def _call_evaluator_anthropic(
    client: Any,
    model: str,
    user_message: str,
    max_output_tokens: int = _EVALUATOR_DEFAULT_MAX_OUTPUT_TOKENS,
) -> tuple[str | None, int]:
    """Call Anthropic client.messages.create() and return (raw_text, tokens_used)."""
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_output_tokens,
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
    max_output_tokens: int = _EVALUATOR_DEFAULT_MAX_OUTPUT_TOKENS,
) -> tuple[str | None, int]:
    """Call OpenAI ``responses.create()`` and return (raw_text, tokens_used).

    The orchestrator's OpenAI branch already speaks the Responses API, so the
    evaluator uses it too: one observation then exercises a single endpoint for
    both halves rather than mixing wire shapes (and their differing token-field
    names) inside one measurement.

    DeepSeek is OpenAI-*compatible* on Chat Completions only, so it keeps its
    own path in ``_call_evaluator_openai_chat_completions``.
    """
    try:
        response = client.responses.create(
            model=model,
            max_output_tokens=max_output_tokens,
            instructions=_EVALUATOR_SYSTEM_PROMPT,
            input=[{"role": "user", "content": user_message}],
        )
        raw_text = getattr(response, "output_text", None) or None
        if raw_text is None:
            texts: list[str] = []
            for item in getattr(response, "output", None) or []:
                if getattr(item, "type", None) != "message":
                    continue
                for content in getattr(item, "content", None) or []:
                    if getattr(content, "type", None) == "output_text":
                        text = getattr(content, "text", None)
                        if isinstance(text, str):
                            texts.append(text)
            raw_text = "".join(texts) or None
        usage = getattr(response, "usage", None)
        tokens = 0
        if usage is not None:
            tokens = (getattr(usage, "input_tokens", 0) or 0) + (
                getattr(usage, "output_tokens", 0) or 0
            )
        return raw_text, tokens
    except Exception as exc:  # noqa: BLE001
        print(f"[evaluator] OpenAI call failed: {exc}", file=sys.stderr)
        return None, 0


def _call_evaluator_openai_chat_completions(
    client: Any,
    model: str,
    user_message: str,
    max_output_tokens: int = _EVALUATOR_DEFAULT_MAX_OUTPUT_TOKENS,
) -> tuple[str | None, int]:
    """Call an OpenAI-compatible ``chat.completions.create()`` endpoint."""
    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_output_tokens,
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
    """Call the deprecated google-generativeai SDK and return (raw_text, tokens_used).

    ``client`` is the ``google.generativeai`` module (see harness._build_eval_client),
    so the call goes through ``GenerativeModel(...).generate_content(...)`` — NOT
    the unified ``google-genai`` ``client.models.generate_content`` interface, which
    this SDK does not expose.
    """
    try:
        full_prompt = _EVALUATOR_SYSTEM_PROMPT + "\n\n" + user_message
        gen_model = client.GenerativeModel(model_name=model)
        response = gen_model.generate_content(full_prompt)
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
    max_output_tokens: int = _EVALUATOR_DEFAULT_MAX_OUTPUT_TOKENS,
) -> tuple[str | None, int]:
    """Call DeepSeek (OpenAI-compat) client and return (raw_text, tokens_used)."""
    # DeepSeek is compatible with Chat Completions, not the Responses API.
    return _call_evaluator_openai_chat_completions(client, model, user_message, max_output_tokens)


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
        return _fail_open(FAIL_OPEN_NO_CLIENT)

    model = os.environ.get(_EVAL_MODEL_ENV, "").strip() or _EVALUATOR_MODELS.get(provider, "claude-haiku-4-5-20251001")
    budget = _evaluator_max_output_tokens(model)
    user_message = _build_evaluator_user_message(question, primary_response, tool_calls)

    try:
        if provider == "openai":
            raw_text, tokens = _call_evaluator_openai(client, model, user_message, budget)
        elif provider == "gemini":
            # The google-generativeai call carries no output cap here.
            raw_text, tokens = _call_evaluator_gemini(client, model, user_message)
        elif provider == "deepseek":
            raw_text, tokens = _call_evaluator_deepseek(client, model, user_message, budget)
        else:
            # Default: anthropic
            raw_text, tokens = _call_evaluator_anthropic(client, model, user_message, budget)
    except Exception as exc:  # noqa: BLE001
        print(f"[evaluator] unexpected error during provider call: {exc}", file=sys.stderr)
        return _fail_open(FAIL_OPEN_PROVIDER_ERROR)

    verdict = _parse_verdict(raw_text, tokens)
    if verdict is None:
        reason = _parse_failure_reason(raw_text, tokens)
        if raw_text is not None:
            print(f"[evaluator] could not parse JSON verdict ({reason}) from: {raw_text!r}", file=sys.stderr)
        return _fail_open(reason, tokens)

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
