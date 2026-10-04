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

i143 adds two detectors, reported apart from the three above (``leaks`` keeps
its i123 contract):

* tooltalk    -- the answer talks about the machinery instead of the football:
                 «la salida (de recomendación) no muestra…», «la herramienta no
                 aporta…», «el sistema no puede confirmar…», «los datos
                 recibidos», «el resultado no incluye…». Anchored so football
                 prose («salida de balón», «el resultado del partido») stays
                 clean.
* chipname_es -- a chip named in Spanish (Leo, 2026-10-04: chip names stay in
                 English -- Triple Captain, Bench Boost, Free Hit, Wildcard).

Reads measurement JSONL (rows with ``final_text`` or ``response.final_text``).
Usage: python grade_i123_internal_names.py FILE [FILE ...]
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata

SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
BACKTICK = re.compile(r"`[^`\n]{1,60}`")
FIELDEQ = re.compile(r"\b[a-z_]{3,}\s*=\s*(?:\[\]|\{\}|null|None|true|false|\"[^\"]*\"|\d+)")

#: i143. Matched on the accent-folded, lower-cased text.
TOOLTALK = re.compile(
    r"\b(?:la|esta|esa|de la|segun la) herramienta\b|"
    r"\b(?:la|esta|esa|de la|segun la) salida\b(?! de balon| en corto| en largo| rapida| del balon)|"
    r"\b(?:el|este|del) sistema\b(?= (?:no|desconoce|indica|muestra|aporta|devuelve|conoce))|"
    r"\b(?:el|este|del) resultado\b(?= (?:no |indica|muestra|aporta|devuelve|incluye))|"
    r"\blos datos (?:recibidos|que recibi|que tengo|que me llegan|disponibles no)\b|"
    r"\bcon los datos (?:disponibles|recibidos|que tengo)\b|"
    r"\b(?:no se aporta|no aporta|no incluye|no muestra|no devuelve) (?:ningun|ninguna|un|una)? ?(?:campo|dato)\b|"
    r"\b(?:no aparece|no hay|no figura|no se incluye) (?:un|ningun) campo\b"
)
CHIPNAME_ES = re.compile(
    r"\btriple capitan\b|\bcomodin\b|\bimpulso de banca\b|\bficha libre\b|\bbanca extra\b|\bbanco extra\b|"
    r"\bgolpe de suerte\b"
)


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def tool_talk(text: str) -> list[str]:
    """i143: phrases that talk about the tool / its output / the system."""
    return [m.group(0) for m in TOOLTALK.finditer(_fold(text))]


def spanish_chip_names(text: str) -> list[str]:
    """i143: chip names written in Spanish."""
    return [m.group(0) for m in CHIPNAME_ES.finditer(_fold(text))]


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
    total = dirty = talk = chip_es = 0
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
            extra = {"tooltalk": tool_talk(text), "chipname_es": spanish_chip_names(text)}
            talk += bool(extra["tooltalk"])
            chip_es += bool(extra["chipname_es"])
            if any(found.values()):
                dirty += 1
            if any(found.values()) or any(extra.values()):
                print(json.dumps({"question": (row.get("question") or "")[:60], **found, **extra},
                                 ensure_ascii=False))
    print(f"answers with internal names: {dirty}/{total}")
    print(f"answers with tool talk (i143): {talk}/{total}")
    print(f"answers with Spanish chip names (i143): {chip_es}/{total}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
