"""i78-A: which tool does the orchestrator pick when a /fixtures cell or team
row is tapped?

MEASUREMENT ONLY -- real, paid LLM calls through the SAME ``run_one`` the
tool-routing and i82 measurements used (measure_tool_routing.py: pinned
provider/model, same observation row, same cost table). Nothing here is
mocked and nothing product-side is edited.

The corpus is not typed here. ``tool_routing_corpus.i78a_fixture_click_corpus``
loads field-notes/artifacts/i78a-canonical-phrases.json, which the jest test
packages/fpl-ui/__tests__/fixture-chat-links-canonical.test.ts generates from
``teamOutlookQuestion`` / ``fixtureCellQuestion`` -- the functions the UI
calls on the tap. Controls are the i82 traps plus the two team_fixtures
neighbours (``I78A_CONTROL_IDS``).

Fixed order: the 28 canonical phrases in JSON order, then the controls, each
repeated ``--reps`` times back to back. The SHA256 of the phrases JSON and of
tool_routing_corpus.py are printed and stamped on every row so a read-out can
prove which corpus it came from.

Usage (from packages/fpl-grounded-assistant; .env is read for the API key):

    python scripts/measure_i78a_fixture_click_routing.py \
        --out field-notes/artifacts/i78a-routing-before.jsonl --reps 3

Read-out: scripts/analyze_i78a_fixture_click_routing.py <jsonl> [<jsonl> ...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import measure_tool_routing as base  # noqa: E402  (path insert must precede this)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _estimate_usd(n_calls: int) -> float:
    """Pre-run ceiling from the i82 reference (84 calls -> $0.11 on luna),
    rounded up: the number printed BEFORE any call so the declared cap is
    compared against something."""
    return round(n_calls * (0.11 / 84) * 1.5, 3)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", default=str(base.DEFAULT_BOOTSTRAP))
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--out", required=True)
    parser.add_argument("--only-kind", default=None,
                        help="teamOutlookQuestion | fixtureCellQuestion (default both)")
    parser.add_argument("--no-controls", action="store_true")
    parser.add_argument("--cap-usd", type=float, default=3.0,
                        help="declared spend cap; abort before the first call if the estimate exceeds it")
    args = parser.parse_args(argv)

    base._configure_imports()
    base._load_env_file(base.PACKAGE_ROOT / ".env")
    api_key = base.require_api_key(base.PROVIDER)

    from tool_routing_corpus import (  # noqa: PLC0415
        I78A_CANONICAL_PHRASES_PATH,
        i78a_controls,
        i78a_fixture_click_corpus,
    )

    canonical = i78a_fixture_click_corpus()
    if args.only_kind:
        canonical = [q for q in canonical if q["i78a"]["kind"] == args.only_kind]
    controls = [] if args.no_controls else i78a_controls()
    questions = canonical + controls
    if not questions:
        print("nothing to run", file=sys.stderr)
        return 1

    # Stamp the two descriptions i78-A rewrites AS LOADED by this process, so
    # a row proves which catalogue text the model saw rather than which commit
    # the operator believes was checked out.
    from fpl_grounded_assistant.tool_schema_registry import get_tool_schema  # noqa: PLC0415
    descriptions = {
        name: (get_tool_schema(name).description if get_tool_schema(name) else None)
        for name in ("get_fixture_outlook", "get_fixtures_for_gw")
    }
    corpus_sha = {
        "i78a_canonical_phrases_json": _sha256(I78A_CANONICAL_PHRASES_PATH),
        "tool_routing_corpus_py": _sha256(SCRIPTS_DIR / "tool_routing_corpus.py"),
        "descriptions": {
            name: hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]
            for name, text in descriptions.items()
        },
    }
    total_calls = len(questions) * args.reps
    estimate = _estimate_usd(total_calls)
    print(
        f"corpus: {len(canonical)} canonical + {len(controls)} controls = {len(questions)} "
        f"phrases x {args.reps} reps = {total_calls} calls against {base.PROVIDER}/{base.MODEL}",
        file=sys.stderr,
    )
    print(f"corpus sha256: {json.dumps(corpus_sha)}", file=sys.stderr)
    print(f"estimated spend: ${estimate:.3f} (cap ${args.cap_usd:.2f})", file=sys.stderr)
    if estimate > args.cap_usd:
        print("estimate exceeds the declared cap; reduce --reps or the corpus. No call made.",
              file=sys.stderr)
        return 2

    bootstrap = json.loads(Path(args.bootstrap).read_text(encoding="utf-8"))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    n_done = 0
    n_exc = 0
    written: list[dict[str, Any]] = []
    with out_path.open("a", encoding="utf-8") as fh:
        for q in questions:
            for rep in range(args.reps):
                obs = base.run_one(q, rep, bootstrap, api_key)
                obs["i78a"] = q.get("i78a")
                obs["forbidden_tools"] = list(q.get("forbidden_tools") or [])
                obs["corpus_sha256"] = corpus_sha
                fh.write(json.dumps(obs, ensure_ascii=False) + "\n")
                fh.flush()
                written.append(obs)
                n_done += 1
                if obs["exception"] is not None:
                    n_exc += 1
                if n_done % 20 == 0 or n_done == total_calls:
                    print(
                        f"  {n_done}/{total_calls} done, {n_exc} exceptions, "
                        f"{base.format_spend(written)} so far",
                        file=sys.stderr,
                    )

    print(
        f"DONE. {n_done} observations -> {out_path}, {n_exc} exceptions, "
        f"spend {base.format_spend(written)}",
        file=sys.stderr,
    )
    return 0 if n_exc == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
