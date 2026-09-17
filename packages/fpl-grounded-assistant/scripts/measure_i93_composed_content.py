"""i93: does the /fixtures cell tap's answer name REAL players with REAL
numbers, in opportunity framing?

MEASUREMENT ONLY -- real, paid LLM calls through the SAME ``run_one`` every
measurement of the block used (measure_tool_routing.py: pinned
provider/model, same observation row, same cost table). Nothing is mocked
and nothing product-side is edited.

Content, not routing: i78-A measured which tool ran; i101 measured which
argument arrived; this measures what the user READS. Per call it records,
off the executed trace and the produced text:

* ``tool_sequence``           -- did both get_fixture_outlook and
                                 get_team_snapshot run in the round?
* ``snapshot_web_names``      -- the web_names get_team_snapshot RETURNED
                                 (the only names that count as real);
* ``named_real_players``      -- those web_names that appear in answer_text
                                 (accent-folded substring), so an invented
                                 name never counts as a hit;
* ``transaction_hits``        -- opportunity_framing.transaction_hits on
                                 answer_text (target: empty, every rep);
* ``calendar_calls``          -- i93-b: every executed get_fixture_outlook
                                 call's axis / target_gw / status, so
                                 ``both_axes`` (attack AND defence read by
                                 the tool, status ok) and ``target_gw_ok``
                                 (every call names the phrase's gameweek)
                                 are read off the trace, not the prose;
* ``named_def_or_gkp``        -- the named real players whose snapshot
                                 position is GKP/DEF (the defensive side has
                                 a real player behind it) -- reported, not
                                 gated: whether a defender sits in a team's
                                 top-5 by points is a data property.

Corpus: EVERY generated ``fixtureCellQuestion`` phrase of the i78-A contract
file (24 since i93-b: 4 teams x {J1, synthetic DGW J1, J4, J3, J5, J6}) --
the text the UI inserts on a tap, never typed here. Fixed order, ``--reps``
back to back, JSONL flushed after every call, corpus SHA + description hash
+ ``prompt_has_match_composition`` / ``prompt_has_both_sides`` stamps on
every row.

Usage (from packages/fpl-grounded-assistant; .env is read for the API key):
    python scripts/measure_i93_composed_content.py \
        --out field-notes/artifacts/i93-composed-content-before.jsonl --reps 3
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import measure_tool_routing as base  # noqa: E402

CALENDAR_TOOL = "get_fixture_outlook"
PLAYERS_TOOL = "get_team_snapshot"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _estimate_usd(n_calls: int) -> float:
    # Composed turns carry two tool payloads; budget 1.5x the i78-A per-call rate.
    return round(n_calls * (0.1008 / 114) * 1.5, 3)


#: Letters NFKD does not decompose (they are letters of their own, not
#: base + accent): Ødegaard must match "Odegaard" in prose.
_LATIN_FOLD = str.maketrans({"ø": "o", "æ": "ae", "ß": "ss", "đ": "d", "ł": "l", "œ": "oe", "þ": "th"})


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).translate(_LATIN_FOLD)


class _ResultCapture:
    def __init__(self) -> None:
        self.last: Any = None

    def wrap(self, fn: Any) -> Any:
        def _wrapped(*a: Any, **kw: Any) -> Any:
            result = fn(*a, **kw)
            self.last = result
            return result
        return _wrapped


def snapshot_web_names(result: Any) -> list[str]:
    """web_names the players tool RETURNED in this turn, from the trace."""
    return list(snapshot_positions(result))


def snapshot_positions(result: Any) -> dict[str, str]:
    """web_name -> position (GKP/DEF/MID/FWD) the players tool RETURNED, in
    tool order; the position is the tool's field, never inferred."""
    out: dict[str, str] = {}
    for entry in getattr(result, "tool_calls_trace", None) or ():
        if entry.get("name") != PLAYERS_TOOL:
            continue
        for p in (entry.get("output") or {}).get("top_players") or []:
            wn = p.get("web_name")
            if wn and str(wn) not in out:
                out[str(wn)] = str(p.get("position") or "")
    return out


_DEFENSIVE_POSITIONS = frozenset({"GKP", "DEF"})


def calendar_calls(result: Any) -> list[dict[str, Any]]:
    """One record per EXECUTED get_fixture_outlook call: the axis and
    target_gw the model sent, and the status the tool returned."""
    calls: list[dict[str, Any]] = []
    for entry in getattr(result, "tool_calls_trace", None) or ():
        if entry.get("name") != CALENDAR_TOOL:
            continue
        args = entry.get("args") or {}
        calls.append({
            "axis": args.get("axis"),
            "target_gw": args.get("target_gw"),
            "team_query": args.get("team_query"),
            "output_status": (entry.get("output") or {}).get("status"),
        })
    return calls


def both_axes_read(calls: list[dict[str, Any]]) -> bool:
    """True when the calendar tool produced an ok read on BOTH axes."""
    ok_axes = {c.get("axis") for c in calls if c.get("output_status") == "ok"}
    return {"attack", "defence"} <= ok_axes


def target_gw_ok(calls: list[dict[str, Any]], expected_gw: Any) -> bool:
    """Every executed calendar call carried the phrase's gameweek."""
    if expected_gw is None or not calls:
        return False
    try:
        want = int(expected_gw)
    except (TypeError, ValueError):
        return False
    for c in calls:
        try:
            if int(c.get("target_gw")) != want:
                return False
        except (TypeError, ValueError):
            return False
    return True


def named_real_players(answer_text: str, web_names: list[str]) -> list[str]:
    """The returned web_names that the produced text actually mentions."""
    folded = _fold(answer_text)
    return [wn for wn in web_names if _fold(wn) in folded]


def project(result: Any, answer_text: str, expected_gw: Any = None) -> dict[str, Any]:
    from fpl_grounded_assistant.opportunity_framing import transaction_hits  # noqa: PLC0415
    seq = [e.get("name") for e in (getattr(result, "tool_calls_trace", None) or ()) if e.get("name")]
    positions = snapshot_positions(result)
    names = list(positions)
    named = named_real_players(answer_text, names)
    calls = calendar_calls(result)
    return {
        "tool_sequence": seq,
        "composed": CALENDAR_TOOL in seq and PLAYERS_TOOL in seq,
        "snapshot_web_names": names,
        "snapshot_positions": positions,
        "named_real_players": named,
        "named_def_or_gkp": [n for n in named if positions.get(n) in _DEFENSIVE_POSITIONS],
        "calendar_calls": calls,
        "both_axes": both_axes_read(calls),
        "target_gw_ok": target_gw_ok(calls, expected_gw),
        "transaction_hits": transaction_hits(answer_text),
        "answer_chars": len(answer_text or ""),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", default=str(base.DEFAULT_BOOTSTRAP))
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--out", required=True)
    parser.add_argument("--cap-usd", type=float, default=1.0,
                        help="declared spend cap; abort before the first call if the estimate exceeds it")
    args = parser.parse_args(argv)

    base._configure_imports()
    base._load_env_file(base.PACKAGE_ROOT / ".env")
    api_key = base.require_api_key(base.PROVIDER)

    from tool_routing_corpus import (  # noqa: PLC0415
        I78A_CANONICAL_PHRASES_PATH,
        i93_fixture_cell_corpus,
    )
    from fpl_grounded_assistant import orchestrator as orch_mod  # noqa: PLC0415
    from fpl_grounded_assistant.tool_schema_registry import get_tool_schema  # noqa: PLC0415

    questions = i93_fixture_cell_corpus()
    if not questions:
        print("no fixtureCellQuestion phrases in the corpus", file=sys.stderr)
        return 1

    schema = get_tool_schema(CALENDAR_TOOL)
    corpus_sha = {
        "i78a_canonical_phrases_json": _sha256(I78A_CANONICAL_PHRASES_PATH),
        "tool_routing_corpus_py": _sha256(SCRIPTS_DIR / "tool_routing_corpus.py"),
        "description": hashlib.sha256((schema.description if schema else "").encode("utf-8")).hexdigest()[:16],
        "description_asks_snapshot": bool(schema and "ALSO call get_team_snapshot" in schema.description),
        "description_asks_both_axes": bool(schema and "TWICE in the same response" in schema.description),
        "prompt_has_match_composition": "MATCH_COMPOSITION" in orch_mod._SYSTEM_PROMPT,
        "prompt_has_both_sides": "BOTH sides" in orch_mod._SYSTEM_PROMPT,
    }
    total_calls = len(questions) * args.reps
    estimate = _estimate_usd(total_calls)
    print(f"corpus: {len(questions)} fixtureCellQuestion phrases x {args.reps} reps = {total_calls} calls "
          f"against {base.PROVIDER}/{base.MODEL}", file=sys.stderr)
    print(f"corpus sha256: {json.dumps(corpus_sha)}", file=sys.stderr)
    print(f"estimated spend: ${estimate:.3f} (cap ${args.cap_usd:.2f})", file=sys.stderr)
    if estimate > args.cap_usd:
        print("estimate exceeds the declared cap; reduce --reps or the corpus. No call made.", file=sys.stderr)
        return 2

    bootstrap = json.loads(Path(args.bootstrap).read_text(encoding="utf-8"))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    capture = _ResultCapture()
    original = orch_mod.ask_orchestrated
    orch_mod.ask_orchestrated = capture.wrap(original)
    n_done = n_exc = 0
    written: list[dict[str, Any]] = []
    try:
        with out_path.open("a", encoding="utf-8") as fh:
            for q in questions:
                for rep in range(args.reps):
                    capture.last = None
                    obs = base.run_one(q, rep, bootstrap, api_key)
                    answer = getattr(capture.last, "answer_text", "") if capture.last is not None else ""
                    obs["i78a"] = q.get("i78a")
                    obs["i93"] = (
                        project(capture.last, answer, expected_gw=(q.get("i78a") or {}).get("gameweek"))
                        if capture.last is not None else None
                    )
                    obs["answer_text"] = answer
                    obs["corpus_sha256"] = corpus_sha
                    fh.write(json.dumps(obs, ensure_ascii=False) + "\n")
                    fh.flush()
                    written.append(obs)
                    n_done += 1
                    if obs["exception"] is not None:
                        n_exc += 1
                    if n_done % 12 == 0 or n_done == total_calls:
                        print(f"  {n_done}/{total_calls} done, {n_exc} exceptions, "
                              f"{base.format_spend(written)} so far", file=sys.stderr)
    finally:
        orch_mod.ask_orchestrated = original

    print(f"DONE. {n_done} observations -> {out_path}, {n_exc} exceptions, "
          f"spend {base.format_spend(written)}", file=sys.stderr)
    return 0 if n_exc == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
