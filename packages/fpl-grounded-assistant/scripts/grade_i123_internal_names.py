"""i123 grader: does a served answer show internal names or raw values?

Prod 2026-10-02 (free hit 6/7/8): «… con `dgw_teams=[]` y `bgw_teams=[]`».
Three detectors, each reported separately so a reader sees WHICH fired:

* snake    -- a snake_case identifier of two or more parts (dgw_teams,
              fixture_context, conditions_unfavorable). Spanish prose has none.
* backtick -- code-formatted data (`a`, `news`, `fixture_context: null`).
* fieldeq  -- field=value notation (dgw_teams=[], x = null / true / 3).

Measured before choosing a prompt rule over a final_text_guard reason: on
104 real answers (i124 local + replay, i125 runs, prod audit previews) the
three fire on exactly the 3 answers that leak and on none of the other 101 --
but that is prose on today's tools, so the rule ships in the prompt and this
stays a grader, not a guard.

Reads measurement JSONL (rows with ``final_text`` or ``response.final_text``).
Usage: python grade_i123_internal_names.py FILE [FILE ...]
"""
from __future__ import annotations

import json
import re
import sys

SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
BACKTICK = re.compile(r"`[^`\n]{1,60}`")
FIELDEQ = re.compile(r"\b[a-z_]{3,}\s*=\s*(?:\[\]|\{\}|null|None|true|false|\"[^\"]*\"|\d+)")


def leaks(text: str) -> dict[str, list[str]]:
    """Every detector's matches in *text* (empty lists when clean)."""
    t = text or ""
    return {
        "snake": sorted(set(SNAKE.findall(t))),
        "backtick": BACKTICK.findall(t),
        "fieldeq": [m.group(0) for m in FIELDEQ.finditer(t)],
    }


def is_clean(text: str) -> bool:
    return not any(leaks(text).values())


def _text(row: dict) -> str | None:
    if row.get("kind") not in (None, "turn"):
        return None
    return row.get("final_text") or (row.get("response") or {}).get("final_text") or row.get("primary_response")


def main(argv: list[str]) -> int:
    total = dirty = 0
    for path in argv:
        for line in open(path, encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            text = _text(row)
            if text is None:
                continue
            total += 1
            found = leaks(text)
            if any(found.values()):
                dirty += 1
                print(json.dumps({"question": (row.get("question") or "")[:60], **found}, ensure_ascii=False))
    print(f"answers with internal names: {dirty}/{total}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
