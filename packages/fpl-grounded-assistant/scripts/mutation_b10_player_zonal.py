"""Bloque 10 mutation check: break each guard ONE at a time and require the
zonal test file to fail. Prints a table; exit 1 if any mutant survives.

Usage (from packages/fpl-grounded-assistant):
    python scripts/mutation_b10_player_zonal.py [--basetemp DIR]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
ZONAL = PKG / "fpl_grounded_assistant" / "player_snapshot_zonal.py"
FINAL = PKG / "fpl_grounded_assistant" / "final_response.py"
RENDERER = PKG / "fpl_grounded_assistant" / "renderer.py"
SNAP = PKG / "fpl_grounded_assistant" / "get_player_snapshot.py"
ENGINE = PKG / "fpl_grounded_assistant" / "zonal_weakness.py"
TEST = "tests/test_player_snapshot_zonal.py"

MUTANTS = [
    # --- identity ---------------------------------------------------------
    ("identity", "team control always true", ZONAL,
     "        return _UNDERSTAT_TO_SHORT.get(store_team, \"\").upper() == current_short",
     "        return True"),
    ("identity", "store-name collision ignored", ZONAL,
     "        if len(cands) > 1:\n            return None, None, \"store_name_collision\"",
     "        if False:\n            return None, None, \"store_name_collision\""),
    ("identity", "bootstrap homonym ignored", ZONAL,
     "            if len(homonyms) > 1:",
     "            if False:"),
    ("identity", "resolver ambiguity ignored", ZONAL,
     "    if len(resolved) > 1:\n        return None, None, \"store_candidates_multiple\"",
     "    if False:\n        return None, None, \"store_candidates_multiple\""),
    ("identity", "substring fallback by web_name", ZONAL,
     "    return None, None, \"no_store_profile\"",
     "    sub = [n for n in shares if (element.get('second_name') or '').lower()[:3] in n.lower()]\n"
     "    if sub:\n        return sub[0], 'substring', 'ok'\n    return None, None, \"no_store_profile\""),
    # --- isolation --------------------------------------------------------
    ("isolation", "exceptions propagate", ZONAL,
     "    except Exception as exc:  # noqa: BLE001 -- enrichment must not break the card\n        result = _omit(f\"exception:{type(exc).__name__}\")",
     "    except ZeroDivisionError as exc:\n        result = _omit('x')"),
    ("isolation", "invalid payload served", ZONAL,
     "    if not _valid_zonal(zonal):",
     "    if False:"),
    ("isolation", "bad zonal block takes the whole meta down", FINAL,
     "    except Exception:  # noqa: BLE001\n        return None\n\n\ndef _extract_player_snapshot_meta",
     "    except ZeroDivisionError:\n        return None\n\n\ndef _extract_player_snapshot_meta"),
    # --- fixture state ----------------------------------------------------
    ("fixture-state", "in-play counted as pending", ZONAL,
     "    if started:\n        return \"live\"",
     "    if started:\n        return \"pending\""),
    ("fixture-state", "provisional finish ignored", ZONAL,
     "    if finished or provisional:",
     "    if finished:"),
    ("fixture-state", "unknown flags read as pending", ZONAL,
     "        return \"unknown\"\n    if finished or provisional:",
     "        return \"pending\"\n    if finished or provisional:"),
    ("fixture-state", "window ignores state (all team fixtures)", ZONAL,
     "    rows = [f for f in in_window if f[\"_state\"] == \"pending\"]",
     "    rows = list(in_window)"),
    ("fixture-state", "window starts at first fixture, not first pending", ZONAL,
     "    start = next((f[\"_gw\"] for f in mine if f[\"_state\"] == \"pending\"), None)",
     "    start = mine[0][\"_gw\"]"),
    ("fixture-state", "empty/malformed response cached", ZONAL,
     "    if not _well_formed(data):\n        return None, \"fixtures_response_invalid\"",
     "    if data is None:\n        return None, \"fixtures_response_invalid\""),
    ("fixture-state", "cache never expires", ZONAL,
     "now - cached_at < FIXTURES_TTL_S", "True"),
    ("fixture-state", "failed fetch cached as empty", ZONAL,
     "    except Exception:  # noqa: BLE001 -- timeout, DNS, HTTP, bad JSON\n        return None, \"fixtures_fetch_failed\"",
     "    except Exception:  # noqa: BLE001 -- timeout, DNS, HTTP, bad JSON\n        _fixtures_cache.update(at=now, data=[])\n        return None, \"fixtures_fetch_failed\""),
    # --- no_data ----------------------------------------------------------
    ("no_data", "all no_data reads as neutral", ZONAL,
     "    if all(f[\"status\"] == \"no_data\" for f in fixtures):",
     "    if False:"),
    ("no_data", "renderer prints no_data as neutral", RENDERER,
     "            elif fx.get(\"status\") == \"no_data\":\n                lines.append(f\"{head}: sin datos zonales del rival\")",
     "            elif fx.get(\"status\") == \"no_data\":\n                lines.append(f\"{head}: sin cruce destacado\")"),
    # --- units / contract -------------------------------------------------
    ("units", "share served as percent", ENGINE,
     "            {\"zone\": zone, \"share\": round(share, 4)}\n            for zone, share in info[\"zone_share\"].items()\n            if share >= PLAYER_ZONE_XG_SHARE_THRESHOLD\n        ),\n        key=lambda z: -z[\"share\"],\n    )\n\n\ndef build_player_outlook",
     "            {\"zone\": zone, \"share\": round(share * 100, 2)}\n            for zone, share in info[\"zone_share\"].items()\n            if share >= PLAYER_ZONE_XG_SHARE_THRESHOLD\n        ),\n        key=lambda z: -z[\"share\"],\n    )\n\n\ndef build_player_outlook"),
    ("isolation", "snapshot attaches zonal even on engine omission", SNAP,
     "    if result.zonal is not None:\n        player_dict[\"zonal\"] = result.zonal",
     "    player_dict[\"zonal\"] = result.zonal"),
]


def run_tests(basetemp: str) -> int:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
         f"--basetemp={basetemp}", TEST],
        cwd=PKG, capture_output=True, text=True,
    ).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--basetemp", default=str(PKG / ".mutation-tmp"))
    a = ap.parse_args()
    base = run_tests(a.basetemp)
    if base != 0:
        print("baseline tests fail; aborting")
        return 2
    survived = []
    print(f"{'guard':14} {'mutant':52} result")
    for guard, name, path, old, new in MUTANTS:
        if path is None:
            continue
        src = path.read_text(encoding="utf-8")
        if src.count(old) != 1:
            print(f"{guard:14} {name:52} PATTERN-NOT-FOUND ({src.count(old)})")
            survived.append(name)
            continue
        path.write_text(src.replace(old, new, 1), encoding="utf-8")
        try:
            rc = run_tests(a.basetemp)
        finally:
            path.write_text(src, encoding="utf-8")
        status = "killed" if rc != 0 else "SURVIVED"
        print(f"{guard:14} {name:52} {status}")
        if rc == 0:
            survived.append(name)
    print(f"\n{len(MUTANTS) - 1 - len(survived)} killed, {len(survived)} survived")
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main())
