"""Regenerate the European ``manual_curated`` layer and the line Leo pastes into Railway's Raw Editor.

    python -I packages/fpl-grounded-assistant/scripts/build_manual_calendar_railway_var.py \\
        --list-date 2026-10-28 --unverified BHA:2026-11-26

Reads ``DIR/calendario_de_clubes_premier_league_en_copas_europeas.txt`` (DIR defaults to ``data/calendar-manual/``
of this checkout, git-excluded) and writes, in DIR only:

* ``europe_manual.json``          the layer (what the converter writes; local backend reads it)
* ``railway_env_line.txt``        ``FPL_MANUAL_CALENDAR_JSON="..."``: one line, quotes escaped (Raw Editor, ENV tab)
* ``railway_env.json``            the same variable as a JSON object (Raw Editor, JSON tab), if ENV mangles it

Both forms are read back and checked with the backend's own validator before the script succeeds.
Prints counts only, never a row.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

_PACKAGES = Path(__file__).resolve().parents[2]
for sibling in ("football-intelligence", "football-data-contract"):
    sys.path.insert(0, str(_PACKAGES / sibling))

from football_intelligence.manual_calendar import parse_manual_europe  # noqa: E402


def _backend_calendar():
    """``competition_calendar`` by file, not through its package (whose ``__init__`` loads the whole app)."""
    path = _PACKAGES / "fpl-grounded-assistant" / "fpl_grounded_assistant" / "competition_calendar.py"
    spec = importlib.util.spec_from_file_location("_competition_calendar", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_cc = _backend_calendar()
ENV_MANUAL_JSON, _valid_layer = _cc.ENV_MANUAL_JSON, _cc._valid_layer

SOURCE = "calendario_de_clubes_premier_league_en_copas_europeas.txt"


def env_line(value: str) -> str:
    """``NAME="value"``. The compact JSON carries no backslash or newline (checked), so only quotes need escaping."""
    if "\\" in value or "\n" in value or "\r" in value:
        raise ValueError("value would need more than quote escaping")
    return f'{ENV_MANUAL_JSON}="{value.replace(chr(34), chr(92) + chr(34))}"'


def read_env_line(line: str) -> str:
    name, _, quoted = line.partition("=")
    if name != ENV_MANUAL_JSON or not (quoted.startswith('"') and quoted.endswith('"')):
        raise ValueError("not the expected NAME=\"value\" line")
    return quoted[1:-1].replace('\\"', '"')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-date", required=True, help="YYYY-MM-DD the list was compiled (the visible stamp)")
    ap.add_argument("--unverified", action="append", default=[], metavar="CLUB:YYYY-MM-DD")
    ap.add_argument("--dir", type=Path, default=_PACKAGES.parent / "data" / "calendar-manual")
    args = ap.parse_args()

    layer = parse_manual_europe((args.dir / SOURCE).read_text(encoding="utf-8"), list_date=args.list_date,
                                unverified=frozenset(tuple(u.split(":", 1)) for u in args.unverified))
    if not _valid_layer(layer):
        raise SystemExit("converter output fails the backend validator")
    (args.dir / "europe_manual.json").write_text(json.dumps(layer, ensure_ascii=False, indent=1), encoding="utf-8")

    value = json.dumps(layer, ensure_ascii=False, separators=(",", ":"))
    line = env_line(value)
    as_json = json.dumps({ENV_MANUAL_JSON: value}, ensure_ascii=False)
    for back in (read_env_line(line), json.loads(as_json)[ENV_MANUAL_JSON]):
        if json.loads(back) != layer:
            raise SystemExit("round trip changed the layer")
    (args.dir / "railway_env_line.txt").write_text(line + "\n", encoding="utf-8")
    (args.dir / "railway_env.json").write_text(as_json + "\n", encoding="utf-8")

    known = sum(m["kickoff_known"] for m in layer["matches"])
    for w in layer["warnings"]:
        print(f"WARNING line {w['line']}: {w['reason']}")
    print(f"{len(layer['matches'])} matches ({known} with verified time), competitions {layer['competitions']}, "
          f"list_date {layer['list_date']}, variable {len(value)} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
