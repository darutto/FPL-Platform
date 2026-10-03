"""i125(a) grader: does the answer's top N match the tool's ranking?

Reads JSONL rows written by ``measure_i125b_captain_retry.py`` (POST /ask with
debug). For each turn:

* expected -- the list the CARD paints, read off the response itself:
  ``presentation.owned_top`` when a squad is connected, else
  ``presentation.global_top`` (ids resolved to names through
  ``captain_ranking[].player_id``), cut to N (``--top``, default 3). These ids
  are the tool's own ``rank_captain_candidates`` output -- the same payload
  the RankingTable renders -- never something the measurement asked for.
* served -- the first N numbered items ("1. ...", "2) ...") in final_text.
* match -- every expected name appears in its own numbered item, in order.
* extra_numbered -- numbered items beyond the first N (the model writing a
  list of its own under the deterministic one); extra_contradicts -- that
  extra list names someone outside the expected list (a second, different
  top N in one answer).

A turn with no captain_ranking on the response (the tool did not end as the
selected payload) is reported as ``no_card`` and counted as a miss: the user
got no ranking to compare with.

Usage: python grade_i125a_captain_list.py FILE.jsonl [FILE.jsonl ...] [--top N]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata

_ITEM = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def expected_names(body: dict, top: int) -> list[str] | None:
    ranking = body.get("captain_ranking") or []
    pres = body.get("presentation") or {}
    if not ranking or not pres:
        return None
    by_id = {e.get("player_id"): e.get("web_name") for e in ranking if e.get("player_id") is not None}
    ids = pres.get("owned_top") if body.get("squad_source") == "connected" else pres.get("global_top")
    names = [by_id.get(i) for i in (ids or []) if by_id.get(i)]
    return names[:top]


def served_items(text: str, top: int) -> list[str]:
    items = [m.group(2) for line in (text or "").splitlines() if (m := _ITEM.match(line))]
    return items[:top]


def grade(body: dict, top: int) -> dict:
    expected = expected_names(body, top)
    all_items = served_items(body.get("final_text") or "", 10_000)
    items = all_items[:top]
    extra = all_items[top:]
    if expected is None:
        return {"match": False, "reason": "no_card", "expected": None, "items": items,
                "extra_numbered": len(extra), "extra_contradicts": None}
    ok = len(items) >= len(expected) and all(
        fold(name) in fold(items[i]) for i, name in enumerate(expected)
    )
    names = [e.get("web_name") for e in body.get("captain_ranking") or [] if e.get("web_name")]
    extra_named = [n for item in extra for n in names if fold(n) in fold(item)]
    contradicts = any(n not in expected for n in extra_named)
    return {"match": ok, "reason": None if ok else "order_or_omission", "expected": expected, "items": items,
            "extra_numbered": len(extra), "extra_contradicts": contradicts}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--top", type=int, default=3)
    a = ap.parse_args(argv)
    total = hits = extra_turns = contradicting = 0
    for path in a.files:
        for line in open(path, encoding="utf-8"):
            row = json.loads(line)
            if row.get("kind") != "turn":
                continue
            g = grade(row["response"], a.top)
            total += 1
            hits += g["match"]
            extra_turns += g["extra_numbered"] > 0
            contradicting += bool(g["extra_contradicts"])
            print(json.dumps({"file": path.rsplit("/", 1)[-1], "i": row["i"], **g}, ensure_ascii=False))
    print(f"match {hits}/{total}  extra_list {extra_turns}/{total}  extra_contradicts {contradicting}/{total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
