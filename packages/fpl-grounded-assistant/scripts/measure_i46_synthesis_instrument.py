"""i46: why does the synthesis call return 200 with no text?

MEASUREMENT ONLY. Imports the product; edits none of it. Makes real, paid
LLM calls. This is an INSTRUMENT, not a gate: it must never be wired into
CI and it must never touch the i25 golden battery's reference row.

The defect
----------
``orchestrator.py`` makes a second ("synthesis") provider call after tools
run. When that call succeeds but ``_extract_text_from_response`` finds no
text, the orchestrator falls through to a deterministic ``render()`` of the
first tool and the user sees a raw table. The observable signal is
``synthesis_turn == False`` on a turn that DID execute a tool -- not
``tool_call_count``, which confuses a single-tool turn (which has had
synthesis since #160) with a turn that lost it.

Three candidate factors, no arm separating any of them
------------------------------------------------------
1. tool payload size
2. tool identity
3. output budget (``max_tokens``)

What this script adds that nothing else has: **per-provider-call capture of
finish_reason and the usage breakdown, reasoning tokens included.** Nobody
has looked at those. If a reasoning model is spending its output budget
thinking and never emitting a message item, that is visible in
``incomplete_details.reason == "max_output_tokens"`` plus a ``reasoning``
output item with no ``message`` item -- and no arm-running is needed.

Two modes
---------
``--mode probe``  Step 1. N reps of one case (default gw-04, the confirmed
                  repro at 6/9) at production budget. Confirms the
                  instrument captures what we think it captures. **If this
                  answers the question, stop and report -- do not run the
                  arms.**

``--mode arms``   Step 2. Payload vs budget, tool held FIXED.
                  ``rank_players_by_metric`` is the vehicle because its
                  ``ranked`` field is NOT in ``_TRUNCATABLE_FIELDS``
                  (orchestrator.py:572), so the list reaches the model
                  whole: ~3.2 KB at top_n=3, ~9.8 KB at 10, ~48 KB at 50.
                  6 arms = 3 payload sizes x max_tokens {1024, 4096},
                  plus a gw-04 control arm at both budgets.

Holding the tool fixed is what makes the payload contrast clean. The price
is that this experiment says NOTHING about factor 2: it cannot explain why
``get_gameweek_context`` failed 2/4 in the captaincy track. Tool identity
stays confounded after this runs.

**The model picks ``top_n``, not us.** The arm wording only induces a size.
Every call is classified by the bytes ACTUALLY serialized into the
follow-up message, read from the instrumented trace. Runs are never
discarded for landing in a different bin than intended.

Usage (from packages/fpl-grounded-assistant):

    python scripts/measure_i46_synthesis_instrument.py --mode probe \
        --out ../../field-notes/artifacts/i46-instrument-probe.jsonl --reps 10

    python scripts/measure_i46_synthesis_instrument.py --mode arms \
        --out ../../field-notes/artifacts/i46-instrument-arms.jsonl --reps 10
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import measure_tool_routing as base  # noqa: E402

# --------------------------------------------------------------------------
# Pinned run configuration.
#
# Provider and model are pinned explicitly (never read from FPL_ORCH_PROVIDER
# / FPL_ORCH_MODEL) and every call's fpl_provider_event is checked against
# them. A silent fallback to another provider once produced a run that passed
# and proved nothing.
# --------------------------------------------------------------------------
PROVIDER = base.PROVIDER      # "openai"
MODEL = base.MODEL            # "gpt-5.6-luna"

#: Production budget. orchestrator.ask_orchestrated's default, and what the
#: server actually gets: fpl_server.py calls ask_v2(), and ask_v2() has no
#: max_tokens parameter at all, so nothing can override it.
PROD_MAX_TOKENS = 1024

#: The doubled arm.
HIGH_MAX_TOKENS = 4096

#: Mean cost per call over the i41 run (84 calls, $0.367) on gpt-5.6-luna.
#: Pre-spend estimate only; the run reports real spend.
EST_USD_PER_CALL = 0.0044

# --------------------------------------------------------------------------
# PRE-REGISTERED DECISION RULES -- written before any call was made.
#
# Denominator for every rate below: turns that EXECUTED A TOOL. A turn that
# called no tool cannot fail synthesis and only dilutes the denominator.
# Numerator: those turns with synthesis_turn == False.
# --------------------------------------------------------------------------
RATIO_THRESHOLD = 3  # int: the rule is compared by exact cross-multiplication

#: Payload bins, in bytes actually serialized into the follow-up message.
#: Fixed before running so a surprising distribution cannot be re-binned into
#: a result. Chosen around the known sizes: ~3.2 KB / ~9.8 KB / ~48 KB.
BIN_SMALL_MAX = 6_000
BIN_MEDIUM_MAX = 20_000

#: Zero-event tie-break, pre-registered because "3x" is undefined when the
#: comparison arm has no failures. With zero failures in the comparison arm,
#: the hypothesis is declared SUPPORTED only if the other arm produced at
#: least this many failures; otherwise UNDETERMINED (too few events to tell
#: a real effect from noise). Never silently treated as a pass.
MIN_EVENTS_FOR_INFINITE_RATIO = 3

# --------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------

#: Step 1. The confirmed repro: gw-04, 6/9 across three battery runs.
#: Taken from tool_routing_corpus so the wording is not re-typed and drift
#: with the battery is impossible.
PROBE_CASE_ID = "gw-04"

#: Step 2 arms. One tool, one metric, one question stem; only the requested
#: count varies. Stem follows corpus case sb-04 (a rank_players_by_metric
#: control) so the routing is already known to be clean.
_STEM = "¿Quién lleva más goles esperados (xG) esta temporada entre todos los jugadores?"

PAYLOAD_ARMS: list[dict[str, Any]] = [
    {
        "arm": "payload_small",
        "id": "i46-p03",
        "family": "squad_building",
        "control": True,
        "acceptable_tools": ["rank_players_by_metric"],
        "question": f"{_STEM} Dame solo los 3 primeros.",
        "intended_top_n": 3,
    },
    {
        "arm": "payload_medium",
        "id": "i46-p10",
        "family": "squad_building",
        "control": True,
        "acceptable_tools": ["rank_players_by_metric"],
        "question": f"{_STEM} Dame los 10 primeros.",
        "intended_top_n": 10,
    },
    {
        "arm": "payload_large",
        "id": "i46-p50",
        "family": "squad_building",
        "control": True,
        "acceptable_tools": ["rank_players_by_metric"],
        "question": f"{_STEM} Dame la lista completa de los 50 primeros.",
        "intended_top_n": 50,
    },
]


# --------------------------------------------------------------------------
# Provider-event capture (same guard the golden battery uses)
# --------------------------------------------------------------------------

class _ProviderEventCapture(logging.Handler):
    """Collects fpl_provider_event payloads so provider/model can be asserted."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.events: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        event = getattr(record, "fpl_event", None)
        if isinstance(event, dict) and "provider" in event:
            self.events.append(event)


def _verify_provider(events: list[dict[str, Any]], provider: str, model: str) -> None:
    """Abort on any event that did not come from what was requested."""
    if not events:
        raise SystemExit(
            "ABORT: no fpl_provider_event was captured. The run cannot prove "
            "which provider answered, so its result would mean nothing."
        )
    bad = [
        e for e in events
        if e.get("provider") != provider
        or (e.get("model") and model not in str(e.get("model")))
    ]
    if bad:
        seen = {(e.get("provider"), e.get("model")) for e in bad}
        raise SystemExit(
            f"ABORT: {len(bad)} provider event(s) did not match the requested "
            f"{provider}/{model}. Saw: {sorted(seen)}."
        )


# --------------------------------------------------------------------------
# The instrumentation itself
# --------------------------------------------------------------------------

def _payload_bytes(messages: Any) -> int:
    """Bytes of tool-result payload actually serialized into this request.

    Read from the message list the orchestrator is about to send, AFTER
    ``_truncate_tool_output`` has run -- so this is what the model really
    receives, not what the tool produced. Covers all three provider shapes
    built by ``_build_multi_tool_follow_up``.

    Returns 0 for the primary call (no tool results yet), which is how the
    primary and synthesis calls are told apart without relying on order.
    """
    total = 0
    try:
        for item in messages or []:
            # OpenAI Responses: {"type": "function_call_output", "output": "<json>"}
            if isinstance(item, dict) and item.get("type") == "function_call_output":
                total += len(str(item.get("output") or "").encode("utf-8"))
                continue
            if isinstance(item, dict):
                # Anthropic: {"role": "user", "content": [{"type": "tool_result", ...}]}
                content = item.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            total += len(str(block.get("content") or "").encode("utf-8"))
                # Gemini: {"role": "user", "parts": [{"function_response": {...}}]}
                for part in item.get("parts") or []:
                    if isinstance(part, dict) and "function_response" in part:
                        total += len(
                            json.dumps(
                                part["function_response"], ensure_ascii=False
                            ).encode("utf-8")
                        )
    except Exception:  # noqa: BLE001 -- instrumentation must never alter behaviour
        return -1
    return total


def _finish_and_usage(response: Any, provider: str) -> dict[str, Any]:
    """Finish reason + full usage breakdown for one provider call.

    THE POINT OF THIS SCRIPT. Every access is defensive: instrumentation that
    can raise would change the behaviour it is measuring.

    OpenAI Responses exposes ``status`` / ``incomplete_details.reason`` rather
    than a ``finish_reason`` field; ``reasoning_tokens`` lives under
    ``usage.output_tokens_details``. ``output_item_types`` is the direct test
    of the standing hypothesis: a ``reasoning`` item with no ``message`` item
    is a call that thought until the budget ran out and never spoke.
    """
    out: dict[str, Any] = {
        "finish_reason": None,
        "incomplete_reason": None,
        "usage_input_tokens": None,
        "usage_output_tokens": None,
        "usage_reasoning_tokens": None,
        "usage_cached_tokens": None,
        "output_item_types": None,
    }
    if response is None:
        return out

    def _g(obj: Any, *names: str) -> Any:
        for n in names:
            try:
                obj = obj.get(n) if isinstance(obj, dict) else getattr(obj, n, None)
            except Exception:  # noqa: BLE001
                return None
            if obj is None:
                return None
        return obj

    try:
        if provider == "openai":
            out["finish_reason"] = _g(response, "status")
            out["incomplete_reason"] = _g(response, "incomplete_details", "reason")
            out["usage_input_tokens"] = _g(response, "usage", "input_tokens")
            out["usage_output_tokens"] = _g(response, "usage", "output_tokens")
            out["usage_reasoning_tokens"] = _g(
                response, "usage", "output_tokens_details", "reasoning_tokens"
            )
            out["usage_cached_tokens"] = _g(
                response, "usage", "input_tokens_details", "cached_tokens"
            )
            try:
                out["output_item_types"] = [
                    getattr(i, "type", None)
                    for i in (getattr(response, "output", None) or [])
                ]
            except Exception:  # noqa: BLE001
                pass
        elif provider == "gemini":
            cands = getattr(response, "candidates", None) or []
            if cands:
                fr = getattr(cands[0], "finish_reason", None)
                out["finish_reason"] = (
                    getattr(fr, "name", None) or (str(fr) if fr is not None else None)
                )
            out["usage_input_tokens"] = _g(response, "usage_metadata", "prompt_token_count")
            out["usage_output_tokens"] = _g(
                response, "usage_metadata", "candidates_token_count"
            )
            out["usage_reasoning_tokens"] = _g(
                response, "usage_metadata", "thoughts_token_count"
            )
            out["usage_cached_tokens"] = _g(
                response, "usage_metadata", "cached_content_token_count"
            )
        else:  # anthropic
            out["finish_reason"] = _g(response, "stop_reason")
            out["usage_input_tokens"] = _g(response, "usage", "input_tokens")
            out["usage_output_tokens"] = _g(response, "usage", "output_tokens")
            out["usage_cached_tokens"] = _g(response, "usage", "cache_read_input_tokens")
            try:
                out["output_item_types"] = [
                    getattr(b, "type", None)
                    for b in (getattr(response, "content", None) or [])
                ]
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    return out


class _CallRecorder:
    """Wraps ``call_orch_provider`` in the orchestrator's module namespace.

    Records one row per provider call and forwards the untouched result. The
    wrapper is installed for the length of one ``ask_orchestrated`` call and
    removed in a ``finally``, so a crash cannot leave the product patched.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, real_fn: Any, provider_name: str, /, **kwargs: Any) -> Any:
        payload = _payload_bytes(kwargs.get("messages"))
        t0 = time.monotonic()
        result = real_fn(provider_name, **kwargs)
        elapsed = round((time.monotonic() - t0) * 1000, 1)

        row: dict[str, Any] = {
            "call_index": len(self.calls) + 1,
            # A call carrying tool-result bytes IS the synthesis call. Derived
            # from the payload, not from call order, so a multi-round turn
            # labels every round correctly.
            "role": "synthesis" if payload > 0 else "primary",
            "requested_max_tokens": kwargs.get("max_tokens"),
            "tool_payload_bytes": payload,
            "latency_ms": elapsed,
            "error_code": getattr(result, "error_code", None),
            "error_msg": getattr(result, "error_msg", None),
            "text_extracted": None,
            "text_len": None,
        }
        row.update(_finish_and_usage(getattr(result, "response", None), provider_name))

        # Ask the product's own extractor whether it would find text here --
        # the exact predicate that decides the fallback in orchestrator.py.
        try:
            from fpl_grounded_assistant.orchestrator import _extract_text_from_response
            text = _extract_text_from_response(
                getattr(result, "response", None), provider_name
            )
            row["text_extracted"] = bool(text)
            row["text_len"] = len(text) if text else 0
        except Exception:  # noqa: BLE001
            pass

        self.calls.append(row)
        return result


def run_one(
    question: dict[str, Any],
    rep_index: int,
    bootstrap: dict[str, Any],
    api_key: str,
    max_tokens: int,
) -> dict[str, Any]:
    """One ask_orchestrated() call, with every provider call instrumented.

    Mirrors ``measure_tool_routing.run_one``'s observation shape field for
    field so rows are directly comparable to the battery's, and adds
    ``provider_calls``. It does NOT call ``base.run_one``: that helper pins
    ``max_tokens=1024`` inline, and varying the budget is half this
    experiment. Everything else -- provider, model, bootstrap, cost helper,
    tool-sequence helper -- is base's, unchanged.

    Never raises: exceptions land in the observation so the caller can write
    it to disk and keep going.
    """
    from fpl_grounded_assistant import orchestrator as orch_mod
    from fpl_grounded_assistant.orchestrator import ask_orchestrated

    recorder = _CallRecorder()
    real_fn = orch_mod.call_orch_provider

    t0 = time.monotonic()
    obs: dict[str, Any] = {
        "question_id": question["id"],
        "arm": question.get("arm", "control"),
        "family": question.get("family"),
        "acceptable_tools": question.get("acceptable_tools"),
        "control": question.get("control"),
        "rep": rep_index,
        "question": question["question"],
        "model": MODEL,
        "provider": PROVIDER,
        "requested_max_tokens": max_tokens,
        "intended_top_n": question.get("intended_top_n"),
        "captured_at": None,
        "latency_ms": None,
        "exception": None,
    }
    try:
        orch_mod.call_orch_provider = (
            lambda provider_name, **kw: recorder(real_fn, provider_name, **kw)
        )
        try:
            result = ask_orchestrated(
                question["question"],
                bootstrap,
                provider=PROVIDER,
                model=MODEL,
                api_key=api_key,
                max_tokens=max_tokens,
                temperature=None,
                top_p=None,
                _eval_client=None,
            )
        finally:
            orch_mod.call_orch_provider = real_fn

        tool_output = result.tool_output if isinstance(result.tool_output, dict) else {}
        tool_args = dict(result.tool_args or {})
        obs.update(
            outcome=result.outcome,
            tool_chosen=result.tool_chosen,
            tool_sequence=base.extract_tool_sequence(result),
            tool_call_count=result.tool_call_count,
            tool_args=tool_args,
            # What the model actually asked for, vs what the arm induced.
            actual_top_n=tool_args.get("top_n"),
            returned_rows=(
                len(tool_output.get("ranked") or [])
                if isinstance(tool_output, dict) else None
            ),
            tool_output_status=tool_output.get("status"),
            tool_output_code=tool_output.get("code"),
            tool_output_metric=tool_output.get("metric"),
            synthesis_turn=bool(getattr(result, "synthesis_turn", False)),
            answer_text=(result.answer_text or "")[:400],
            rounds_used=getattr(result, "rounds_used", 0),
            error=result.error,
            primary_input_tokens=result.primary_input_tokens,
            primary_output_tokens=result.primary_output_tokens,
            primary_cache_read_tokens=result.primary_cache_read_tokens,
            total_tokens=result.total_tokens,
            cost_usd=base.cost_usd(
                result.primary_input_tokens,
                result.primary_output_tokens,
                result.primary_cache_read_tokens,
            ),
        )
    except Exception as exc:  # noqa: BLE001 -- must never lose an observation
        obs.update(
            outcome="harness_exception",
            tool_chosen=None, tool_sequence=[], tool_call_count=0, tool_args={},
            actual_top_n=None, returned_rows=None,
            tool_output_status=None, tool_output_code=None, tool_output_metric=None,
            synthesis_turn=False, answer_text="", rounds_used=0, error=str(exc),
            primary_input_tokens=0, primary_output_tokens=0,
            primary_cache_read_tokens=0, total_tokens=0, cost_usd=0.0,
            exception=repr(exc),
        )

    obs["provider_calls"] = recorder.calls
    # Bytes the SYNTHESIS call actually carried -- the classification key.
    synth = [c for c in recorder.calls if c["role"] == "synthesis"]
    obs["synthesis_payload_bytes"] = synth[-1]["tool_payload_bytes"] if synth else 0
    obs["synthesis_call_made"] = bool(synth)
    obs["latency_ms"] = round((time.monotonic() - t0) * 1000, 1)
    obs["captured_at"] = datetime.now(timezone.utc).isoformat()
    return obs


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def _bin_for(payload_bytes: int) -> str:
    if payload_bytes < BIN_SMALL_MAX:
        return "small"
    if payload_bytes < BIN_MEDIUM_MAX:
        return "medium"
    return "large"


def _scored(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only turns that executed a tool. A turn with no tool cannot fail
    synthesis; including it would dilute the denominator."""
    return [
        o for o in observations
        if o.get("exception") is None and (o.get("tool_sequence") or [])
    ]


def _rate(rows: list[dict[str, Any]]) -> tuple[int, int]:
    """(failures, total). Failure == synthesis_turn is False."""
    return sum(1 for r in rows if not r.get("synthesis_turn")), len(rows)


def _ratio_verdict(
    name: str, hi: tuple[int, int], lo: tuple[int, int]
) -> tuple[str, str]:
    """Apply the pre-registered 3x rule, including the zero-event tie-break."""
    hi_n, hi_d = hi
    lo_n, lo_d = lo
    if hi_d == 0 or lo_d == 0:
        return "UNDETERMINED", f"{name}: an arm has no scored turns."
    hi_r = hi_n / hi_d
    lo_r = lo_n / lo_d
    if lo_r == 0:
        if hi_n >= MIN_EVENTS_FOR_INFINITE_RATIO:
            return "SUPPORTED", (
                f"{name}: {hi_n}/{hi_d} vs 0/{lo_d}; ratio infinite and the "
                f"non-zero arm cleared the pre-registered floor of "
                f"{MIN_EVENTS_FOR_INFINITE_RATIO}."
            )
        return "UNDETERMINED", (
            f"{name}: {hi_n}/{hi_d} vs 0/{lo_d}; ratio undefined and the "
            f"non-zero arm has fewer than {MIN_EVENTS_FOR_INFINITE_RATIO} "
            f"events. Too few to separate an effect from noise."
        )
    ratio = hi_r / lo_r
    # Compared by cross-multiplication, not by dividing the two float rates:
    # 6/10 vs 2/10 is exactly 3x, but in binary floats 0.6/0.2 == 2.9999...,
    # which silently flips a boundary result to FALSIFIED. The printed ratio
    # is cosmetic; this comparison is the rule.
    supported = hi_n * lo_d >= RATIO_THRESHOLD * lo_n * hi_d
    if supported:
        return "SUPPORTED", (
            f"{name}: {hi_n}/{hi_d} vs {lo_n}/{lo_d}; ratio {ratio:.2f}x >= 3x."
        )
    return "FALSIFIED", (
        f"{name}: {hi_n}/{hi_d} vs {lo_n}/{lo_d}; ratio {ratio:.2f}x < 3x."
    )


def summarise_probe(observations: list[dict[str, Any]]) -> None:
    """Step 1 report: does the instrument capture what we think it does?"""
    print("\n=== STEP 1 -- INSTRUMENT CONFIRMATION ===")
    n_exc = sum(1 for o in observations if o.get("exception"))
    scored = _scored(observations)
    fails, total = _rate(scored)
    print(f"  observations {len(observations)}   exceptions {n_exc}")
    print(f"  scored (tool executed) {total}   synthesis_turn=False {fails}")

    print("\n  --- synthesis calls, one row per call ---")
    print(f"  {'rep':>3} {'bytes':>7} {'maxtok':>7} {'finish':>12} "
          f"{'incomplete':>18} {'out_tok':>8} {'reason_tok':>10} {'text':>5} items")
    for o in observations:
        for c in o.get("provider_calls") or []:
            if c["role"] != "synthesis":
                continue
            print(f"  {o['rep']:>3} {c['tool_payload_bytes']:>7} "
                  f"{c['requested_max_tokens']:>7} {str(c['finish_reason']):>12} "
                  f"{str(c['incomplete_reason']):>18} "
                  f"{str(c['usage_output_tokens']):>8} "
                  f"{str(c['usage_reasoning_tokens']):>10} "
                  f"{str(c['text_extracted']):>5} "
                  f"{','.join(str(t) for t in (c.get('output_item_types') or []))}")

    # Cross-tab: the answer, if there is one.
    combos: dict[tuple[Any, Any, Any], int] = defaultdict(int)
    for o in observations:
        for c in o.get("provider_calls") or []:
            if c["role"] == "synthesis":
                combos[
                    (c["finish_reason"], c["incomplete_reason"], c["text_extracted"])
                ] += 1
    print("\n  --- finish_reason x incomplete_reason x text_extracted ---")
    for (fr, ir, tx), n in sorted(combos.items(), key=lambda kv: -kv[1]):
        print(f"    finish={fr!s:<12} incomplete={ir!s:<20} text={tx!s:<6} n={n}")

    captured = sum(
        1 for o in observations for c in (o.get("provider_calls") or [])
        if c["role"] == "synthesis" and c["finish_reason"] is not None
    )
    print(f"\n  finish_reason captured on {captured} synthesis call(s).")
    if captured == 0:
        print("  INSTRUMENT NOT CONFIRMED -- no finish_reason was read. Fix the "
              "extractor before spending anything on arms.")
    else:
        print("  Instrument confirmed: finish_reason and usage are being read.")
        print("  If the cross-tab above already explains the empty-text calls, "
              "STOP and report. Do not run --mode arms.")


def summarise_arms(observations: list[dict[str, Any]], reps: int) -> int:
    """Step 2 report: the six cells, plus the two pre-registered rules."""
    print("\n=== STEP 2 -- PAYLOAD vs BUDGET ===")
    n_exc = sum(1 for o in observations if o.get("exception"))
    scored = _scored(observations)

    ranked = [o for o in scored if o["question_id"].startswith("i46-p")]
    control = [o for o in scored if o["question_id"] == PROBE_CASE_ID]

    print(f"  observations {len(observations)}   exceptions {n_exc}   "
          f"scored {len(scored)} (ranked {len(ranked)}, control {len(control)})")
    if n_exc:
        print("  WARNING: exceptions present. An excepted observation is not "
              "evidence either way -- read the rows before trusting any cell.")

    # --- The six cells. Classified by REAL bytes, never by intended arm. ---
    cells: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for o in ranked:
        cells[
            (_bin_for(o["synthesis_payload_bytes"]), o["requested_max_tokens"])
        ].append(o)

    print("\n  --- SIX CELLS (binned by bytes actually serialized) ---")
    print(f"  {'payload':>8} {'max_tokens':>11} {'n':>4} {'synth=False':>12} "
          f"{'rate':>7} {'median bytes':>13} top_n seen")
    for b in ("small", "medium", "large"):
        for mt in (PROD_MAX_TOKENS, HIGH_MAX_TOKENS):
            rows = cells[(b, mt)]
            f, t = _rate(rows)
            byts = sorted(r["synthesis_payload_bytes"] for r in rows)
            med = byts[len(byts) // 2] if byts else 0
            tns = sorted({r.get("actual_top_n") for r in rows if r.get("actual_top_n")})
            rate = f"{f / t:.0%}" if t else "n/a"
            print(f"  {b:>8} {mt:>11} {t:>4} {f:>12} {rate:>7} {med:>13} "
                  f"{','.join(str(x) for x in tns)}")

    print("\n  --- CONTROL (gw-04, tool identity free to vary) ---")
    for mt in (PROD_MAX_TOKENS, HIGH_MAX_TOKENS):
        rows = [o for o in control if o["requested_max_tokens"] == mt]
        f, t = _rate(rows)
        rate = f"{f / t:.0%}" if t else "n/a"
        print(f"  {'gw-04':>8} {mt:>11} {t:>4} {f:>12} {rate:>7}")

    # --- The two pre-registered rules ---
    lo_budget = [o for o in ranked if o["requested_max_tokens"] == PROD_MAX_TOKENS]
    hi_budget = [o for o in ranked if o["requested_max_tokens"] == HIGH_MAX_TOKENS]
    v_budget, msg_budget = _ratio_verdict(
        "H-presupuesto  rate(1024) >= 3x rate(4096)",
        _rate(lo_budget), _rate(hi_budget),
    )

    big = [o for o in ranked if _bin_for(o["synthesis_payload_bytes"]) == "large"]
    small = [o for o in ranked if _bin_for(o["synthesis_payload_bytes"]) == "small"]
    v_payload, msg_payload = _ratio_verdict(
        "H-payload      rate(large) >= 3x rate(small)",
        _rate(big), _rate(small),
    )

    print("\n=== PRE-REGISTERED VERDICTS ===")
    print(f"  {v_budget:<13} {msg_budget}")
    print(f"  {v_payload:<13} {msg_payload}")
    print("\n  Both hypotheses can be true at once; they are scored independently.")
    if v_budget == "SUPPORTED":
        print("  -> H-presupuesto holds: the mitigation is one line in fpl_server.py "
              "(thread a larger max_tokens through ask_v2).")
    if v_payload == "SUPPORTED":
        print("  -> H-payload holds: 'ranked' escaping _TRUNCATABLE_FIELDS is "
              "load-bearing.")
    if v_budget == "FALSIFIED" and v_payload == "FALSIFIED":
        print("  -> BOTH FALSIFIED. The next step is finish_reason/usage "
              "(--mode probe output), NOT another round of arms.")

    print("\n  NOT ANSWERED BY THIS EXPERIMENT: tool identity. The tool was held "
          "fixed on purpose -- that is what makes the payload contrast clean, and "
          "the price is that nothing here explains why get_gameweek_context failed "
          "2/4 in the captaincy track. That factor remains confounded.")
    return 3 if n_exc else 0


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plan(mode: str) -> list[tuple[dict[str, Any], int]]:
    """(question, max_tokens) pairs, each to be run `reps` times."""
    from tool_routing_corpus import CORPUS
    by_id = {q["id"]: q for q in CORPUS}
    if PROBE_CASE_ID not in by_id:
        raise SystemExit(f"{PROBE_CASE_ID} not in corpus")
    probe_case = dict(by_id[PROBE_CASE_ID], arm="control")

    if mode == "probe":
        return [(probe_case, PROD_MAX_TOKENS)]
    return (
        [(q, mt) for q in PAYLOAD_ARMS for mt in (PROD_MAX_TOKENS, HIGH_MAX_TOKENS)]
        + [(probe_case, mt) for mt in (PROD_MAX_TOKENS, HIGH_MAX_TOKENS)]
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=("probe", "arms"), required=True)
    ap.add_argument("--bootstrap", default=str(base.DEFAULT_BOOTSTRAP))
    ap.add_argument("--reps", type=int, default=10,
                    help="10, not 3: cp-12 went 0/3, 0/3, 3/3 across battery runs.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--env-file", default=None,
                    help="KEY=VALUE file holding OPENAI_API_KEY. Defaults to "
                         "the package .env; this worktree may not have one.")
    ap.add_argument("--yes", action="store_true",
                    help="Skip the interactive spend confirmation.")
    args = ap.parse_args(argv)

    base._configure_imports()
    base._load_env_file(
        Path(args.env_file) if args.env_file else base.PACKAGE_ROOT / ".env"
    )

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set (checked env + --env-file); aborting "
              "before any paid call.", file=sys.stderr)
        return 2

    bootstrap_path = Path(args.bootstrap)
    bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    boot_sha = _sha256(bootstrap_path)

    plan = _plan(args.mode)
    total_calls = len(plan) * args.reps
    est = total_calls * EST_USD_PER_CALL

    header = {
        "mode": args.mode, "provider": PROVIDER, "model": MODEL,
        "reps": args.reps, "calls_planned": total_calls,
        "bootstrap_name": bootstrap_path.name, "bootstrap_sha256": boot_sha,
        "prod_max_tokens": PROD_MAX_TOKENS, "high_max_tokens": HIGH_MAX_TOKENS,
        "ratio_threshold": RATIO_THRESHOLD,
        "bins": {"small_max": BIN_SMALL_MAX, "medium_max": BIN_MEDIUM_MAX},
        "run_at": datetime.now(timezone.utc).isoformat(),
    }
    print("=== i46 SYNTHESIS INSTRUMENT ===", file=sys.stderr)
    for k, v in header.items():
        print(f"  {k}: {v}", file=sys.stderr)
    print(f"  ESTIMATED COST: ${est:.4f} "
          f"({total_calls} calls x ~${EST_USD_PER_CALL}/call)", file=sys.stderr)

    if not args.yes:
        try:
            reply = input(f"Spend ~${est:.4f} on {total_calls} calls? [y/N] ")
        except EOFError:
            print("No TTY for confirmation; re-run with --yes.", file=sys.stderr)
            return 2
        if reply.strip().lower() not in ("y", "yes"):
            print("Aborted before any paid call.", file=sys.stderr)
            return 1

    capture = _ProviderEventCapture()
    logging.getLogger("fpl_grounded_assistant").addHandler(capture)
    logging.getLogger("fpl_grounded_assistant").setLevel(logging.INFO)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    observations: list[dict[str, Any]] = []
    spend = 0.0
    n_done = 0
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_header": header}, ensure_ascii=False) + "\n")
        fh.flush()
        for question, max_tokens in plan:
            for rep in range(args.reps):
                obs = run_one(question, rep, bootstrap, api_key, max_tokens)
                obs["_bootstrap_sha256"] = boot_sha
                # Written to disk before any aggregate is computed: a crash
                # or an analysis bug cannot lose an already-paid-for call.
                fh.write(json.dumps(obs, ensure_ascii=False) + "\n")
                fh.flush()
                observations.append(obs)
                spend += obs.get("cost_usd") or 0.0
                n_done += 1
                if n_done % 10 == 0 or n_done == total_calls:
                    print(f"  {n_done}/{total_calls} done, ${spend:.4f} so far",
                          file=sys.stderr)

    _verify_provider(capture.events, PROVIDER, MODEL)
    print(f"\nReal spend: ${spend:.4f}   provider events checked: "
          f"{len(capture.events)}", file=sys.stderr)

    if args.mode == "probe":
        summarise_probe(observations)
        return 0
    return summarise_arms(observations, args.reps)


if __name__ == "__main__":
    raise SystemExit(main())
