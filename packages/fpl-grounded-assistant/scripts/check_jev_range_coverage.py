"""i121: does every Jev chip-path answer cover the gameweeks the user asked for?

The check the i108 E3 grader does not make. The grader reads the answer's
SHAPE (general -> particular); it passed, in prod on 2026-10-02, a Jev answer
that evaluated GW6 only for "¿free hit en la jornada 6, 7 u 8? ¿cuándo?".

Reads the audit NDJSON (it holds the question) and the shadow NDJSON (it
holds what the chip path EXECUTED: ``layer2.chip_args``), joined by
``turn_id``. For every shadow row whose layer 1 took the chip path it flags:

* ``asked_several``   -- the question names more than one gameweek;
* ``asked_open``      -- "próximas N", a window, or WHEN ("¿cuándo?",
                         "mejor momento", "en qué jornada");
* ``wrong_gameweek``  -- one gameweek named, a different one evaluated.

What was ASKED is read from the question text here, with its own parser --
never from the router's logged ``range_signal``, which is the decision being
checked (asked-for vs shipped). What was ANSWERED is read from the executed
``chip_args``, not from the answer prose.

Usage::

    python scripts/check_jev_range_coverage.py AUDIT.ndjson SHADOW.ndjson

Exit 0 when nothing is flagged, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

_GW = r"(?:fechas?|jornadas?|gameweeks?|gws?|semanas?|rondas?)"
#: A gameweek word followed by numbers joined by , y u o / - a al hasta.
_GW_RUN = re.compile(rf"\b{_GW}\s*(\d{{1,2}}(?:\s*(?:,|\by\b|\bu\b|\bo\b|/|-|–|\ba\b|\bal\b|\bhasta\b)\s*(?:la\s+|el\s+)?(?:{_GW}\s*)?\d{{1,2}})*)")
#: "de la 6 a la 8", "entre la 6 y la 8" -- numbers after an article.
_ARTICLE_RUN = re.compile(r"\b(?:de|entre)\s+(?:las?|los?|el)\s+(\d{1,2})\s*(?:a|al|y|hasta|-)\s*(?:la\s+|el\s+)?(?:" + _GW + r"\s*)?(\d{1,2})\b")
_OPEN = re.compile(rf"\b(?:proxim[oa]s|siguientes|next)\s+(?:\d{{1,2}}|dos|tres|cuatro|cinco|seis|two|three|four|five)\s+{_GW}"
                   r"|\bventana\b|\bwindow\b|\bcuando\b|\bmejor\s+momento\b|\bwhen\b"
                   rf"|\ben\s+que\s+(?:momento|{_GW})\b|\best[ae]\s+\w+\s+(?:y|o|u)\s+(?:la|el)\s+(?:proxim[oa]|siguiente)\b")


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def requested(question: str) -> tuple[set[int], bool]:
    """(gameweek numbers the question names, whether it asks an open span)."""
    q = _fold(question)
    nums: set[int] = set()
    for m in _GW_RUN.finditer(q):
        nums.update(int(n) for n in re.findall(r"\d{1,2}", m.group(1)))
    for m in _ARTICLE_RUN.finditer(q):
        lo, hi = int(m.group(1)), int(m.group(2))
        nums.update(range(min(lo, hi), max(lo, hi) + 1) if 0 < hi - lo <= 10 else {lo, hi})
    return nums, bool(_OPEN.search(q))


def violations(audit_rows: list[dict[str, Any]], shadow_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    questions = {r.get("turn_id"): r.get("question") for r in audit_rows if r.get("turn_id")}
    out: list[dict[str, Any]] = []
    for s in shadow_rows:
        layer1 = s.get("layer1") or {}
        if layer1.get("path") != "chip":
            continue
        question = questions.get(s.get("turn_id"))
        if question is None:
            out.append({"turn_id": s.get("turn_id"), "flag": "no_audit_line"})
            continue
        nums, open_span = requested(question)
        evaluated = ((s.get("layer2") or {}).get("chip_args") or {}).get("gameweek")
        flag = None
        if len(nums) > 1:
            flag = "asked_several"
        elif open_span:
            flag = "asked_open"
        elif nums and evaluated not in nums:
            flag = "wrong_gameweek"
        if flag:
            out.append({"turn_id": s.get("turn_id"), "flag": flag, "asked": sorted(nums),
                        "open_span": open_span, "evaluated_gameweek": evaluated, "question": question})
    return out


def _load(path: str) -> list[dict[str, Any]]:
    text = Path(path).read_bytes().decode("utf-8-sig")
    return [json.loads(line) for line in text.splitlines() if line.strip().startswith("{")]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audit")
    ap.add_argument("shadow")
    a = ap.parse_args(argv)
    shadow_rows = _load(a.shadow)
    found = violations(_load(a.audit), shadow_rows)
    chip_rows = sum(1 for s in shadow_rows if (s.get("layer1") or {}).get("path") == "chip")
    print(json.dumps({"shadow_rows": len(shadow_rows), "chip_path_rows": chip_rows,
                      "flagged": len(found), "violations": found}, ensure_ascii=False, indent=1))
    return 0 if not found else 1


if __name__ == "__main__":
    sys.exit(main())
