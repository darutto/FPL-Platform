"""i124: summarise evaluator rejections from measurement JSONL and/or audit NDJSON.

Inputs, any mix:
  * rows written by measure_i124_evaluator_rejections.py (kind == "turn");
  * raw audit lines (an AuditEntry per line: evaluator_verdict, retry_attempted,
    tool_calls with retry flags, tokens, usd_cost_estimate). UTF-16 files
    (a PowerShell redirect) are read too.

Per rejected turn, read off what ran:
  * primary_grounded -- every primary (non-retry) call came back "ok";
  * feedback_kind    -- "cite_more" when the evaluator's retry_feedback only
    asks to cite / show / make explicit data (keyword rule below, every
    feedback string is printed so the rule can be checked by eye), else
    "other";
  * retry_tools      -- same_tool (the retry re-ran a primary tool),
    other_tool, or none; args_lost -- a retry call to a primary tool carried
    fewer argument keys than the primary call did;
  * tokens / cost of the turn, and the retry's own share
    (evaluator + retry_input + retry_output).

Usage: python analyze_i124_evaluator_rejections.py FILE [FILE ...]
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import unicodedata

_CITE = re.compile(
    r"\b(cita|citar|cite|verificabl|respald|explicit|concret|incluye|incluir|menciona|"
    r"muestra|mostrar|indica|detalla|especifica|fuente|valores|numeros|datos)",
)
_REAL_ERROR = re.compile(
    r"\b(incorrect|err[oó]ne|contradic|invent|no coincide|equivocad|wrong|falso|"
    r"no responde|no contesta|irrelevant|otra pregunta|no corresponde)",
)


def _fold(text: str) -> str:
    d = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in d if not unicodedata.combining(c)).lower()


def feedback_kind(feedback: str | None) -> str:
    f = _fold(feedback or "")
    if not f:
        return "none"
    if _REAL_ERROR.search(f):
        return "other"
    return "cite_more" if _CITE.search(f) else "other"


def _read(path: str) -> list[dict]:
    raw = open(path, "rb").read()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _normalise(row: dict, source: str) -> dict | None:
    if row.get("kind") == "pre":
        return None
    if row.get("kind") == "turn":
        calls = row.get("audit_tool_calls") or []
        return {"source": source, "question": row.get("question"), "verdict": row.get("evaluator_verdict"),
                "retry": bool(row.get("retry_attempted")), "delivery": row.get("retry_delivery"),
                "calls": calls, "tokens": row.get("tokens") or {}, "usd": row.get("usd_cost_estimate")}
    if "evaluator_verdict" in row:  # an audit line
        return {"source": source, "question": row.get("question"), "verdict": row.get("evaluator_verdict"),
                "retry": bool(row.get("retry_attempted")), "delivery": row.get("retry_delivery"),
                "calls": row.get("tool_calls") or [], "tokens": row.get("tokens") or {},
                "usd": row.get("usd_cost_estimate")}
    return None


def analyse(turn: dict) -> dict:
    primary = [c for c in turn["calls"] if not c.get("retry")]
    retry = [c for c in turn["calls"] if c.get("retry")]
    p_names = {c.get("name") for c in primary}
    if not retry:
        retry_tools = "none"
    elif any(c.get("name") in p_names for c in retry):
        retry_tools = "same_tool" if all(c.get("name") in p_names for c in retry) else "same_and_other"
    else:
        retry_tools = "other_tool"
    args_lost = any(
        len(rc.get("args") or {}) < max((len(pc.get("args") or {}) for pc in primary if pc.get("name") == rc.get("name")), default=0)
        for rc in retry if rc.get("name") in p_names
    )
    tok = turn["tokens"]
    retry_share = (tok.get("evaluator", 0) or 0) + (tok.get("retry_input", 0) or 0) + (tok.get("retry_output", 0) or 0)
    v = turn["verdict"] or {}
    return {
        "approved": bool(v.get("approved")),
        "primary_grounded": bool(primary) and all(c.get("output_status") == "ok" for c in primary),
        "feedback_kind": feedback_kind(v.get("retry_feedback")) if not v.get("approved") else None,
        "feedback": v.get("retry_feedback"),
        "retry_tools": retry_tools,
        "args_lost": args_lost,
        "total_tokens": tok.get("total", 0) or 0,
        "retry_share_tokens": retry_share,
        "usd": turn["usd"],
    }


def main(argv: list[str]) -> int:
    turns = []
    for path in argv:
        for row in _read(path):
            t = _normalise(row, path.replace("\\", "/").rsplit("/", 1)[-1])
            if t is not None and t["verdict"] is not None:
                turns.append({**t, **analyse(t)})
    if not turns:
        print("no evaluated turns")
        return 1
    rejected = [t for t in turns if not t["approved"]]
    approved = [t for t in turns if t["approved"]]
    print(f"evaluated turns: {len(turns)}   rejected: {len(rejected)} ({100 * len(rejected) / len(turns):.0f}%)")
    for t in rejected:
        print(f"- [{t['source']}] {t['question'][:70]!r}")
        print(f"    grounded={t['primary_grounded']} kind={t['feedback_kind']} retry={t['retry_tools']} "
              f"args_lost={t['args_lost']} delivery={t['delivery']} tok={t['total_tokens']} usd={t['usd']}")
        print(f"    feedback: {t['feedback']}")
    cite_grounded = [t for t in rejected if t["feedback_kind"] == "cite_more" and t["primary_grounded"]]
    print(f"\nrejections that are cite_more on a grounded primary: {len(cite_grounded)}/{len(rejected)}")
    print(f"retry re-ran a primary tool: {sum(t['retry_tools'] in ('same_tool', 'same_and_other') for t in rejected)}/{len(rejected)}"
          f"   args lost: {sum(t['args_lost'] for t in rejected)}/{len(rejected)}")

    def _m(xs, key):
        vals = [x[key] for x in xs if x[key] is not None]
        return (statistics.mean(vals), statistics.median(vals)) if vals else (None, None)

    for label, group in (("approved", approved), ("rejected", rejected)):
        mt, md = _m(group, "total_tokens")
        mu, _ = _m(group, "usd")
        if mt is not None:
            print(f"{label:9s} n={len(group):3d} tokens mean={mt:,.0f} median={md:,.0f} usd mean={mu}")
    if rejected:
        share = statistics.mean(t["retry_share_tokens"] / t["total_tokens"] for t in rejected if t["total_tokens"])
        print(f"retry share of a rejected turn's tokens (evaluator+retry): {share:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
