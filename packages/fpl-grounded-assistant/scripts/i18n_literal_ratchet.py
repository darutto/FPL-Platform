"""Backend Spanish-literal ratchet (i18n S3b).

Spanish text that a user can see must live in ``catalogue.py`` (es + en side by
side) or in a table that has its English twin next to it. This scans the
modules that BUILD user-visible text for Spanish string literals and compares
them to a checked-in baseline of the literals that are known and still owed an
English version.

* A literal that is **not in the baseline fails** ``tests/test_i18n_literal_ratchet.py``.
  Replacing one old Spanish literal with a new one therefore fails too (a count
  would not catch it).
* Removing a literal (it moved to the catalogue) never fails. Regenerate the
  baseline to shrink it::

      python scripts/i18n_literal_ratchet.py --update

  The updated file is committed in the same PR, so the diff shows exactly which
  Spanish text left the code.

Input-matching modules (router, intent_aliases, off_topic, conversation_state,
the resolvers) and LLM-context modules (prompts, tool schemas) are NOT scanned:
their Spanish is what the user types or what the model reads, not output.
``catalogue.py`` is covered by its own pairing test.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
BASELINE = PKG / "tests" / "i18n_literal_baseline.json"

#: Modules (package-relative) whose string literals can reach the user.
SCANNED: tuple[str, ...] = (
    "fpl_grounded_assistant/renderer.py",
    "fpl_grounded_assistant/final_response.py",
    "fpl_grounded_assistant/generic_card.py",
    "fpl_grounded_assistant/atomic_tool_cards.py",
    "fpl_grounded_assistant/comparison.py",
    "fpl_grounded_assistant/comparison_stats.py",
    "fpl_grounded_assistant/transfer_advisor.py",
    "fpl_grounded_assistant/scoring_shared.py",
    "fpl_grounded_assistant/chip_two_part.py",
    "fpl_grounded_assistant/chip_advisor.py",
    "fpl_grounded_assistant/captain_list.py",
    "fpl_grounded_assistant/captain_factors.py",
    "fpl_grounded_assistant/differential_picks.py",
    "fpl_grounded_assistant/fixture_outlook.py",
    "fpl_grounded_assistant/fixture_outlook_tool.py",
    "fpl_grounded_assistant/fixture_context.py",
    "fpl_grounded_assistant/zonal_weakness.py",
    "fpl_grounded_assistant/zonal_weakness_tool.py",
    "fpl_grounded_assistant/player_snapshot_zonal.py",
    "fpl_grounded_assistant/get_my_squad.py",
    "fpl_grounded_assistant/get_team_results.py",
    "fpl_grounded_assistant/orchestrator.py",
    "fpl_grounded_assistant/harness.py",
    "fpl_grounded_assistant/harness_adapter.py",
    "fpl_grounded_assistant/suggestions.py",
    "fpl_grounded_assistant/resource_registry.py",
    "fpl_grounded_assistant/decision_router.py",
    "fpl_server.py",
)

_ACCENTS = re.compile("[áéíóúñü¿¡ÁÉÍÓÚÑ]")
#: Whole words that are Spanish and not English. Deliberately short and closed.
_MARKERS = frozenset({
    "el", "la", "los", "las", "del", "para", "con", "por", "una", "unos", "unas", "que",
    "jornada", "jornadas", "partido", "partidos", "jugador", "jugadores", "equipo",
    "plantilla", "ventaja", "ventajas", "mejor", "mejores", "puntuaci", "sobre", "entre",
    "esta", "este", "tu", "tus", "tienes", "puedes", "prueba", "pregunta",
})
_WORD = re.compile(r"[a-záéíóúñü]+")


def _looks_spanish(text: str) -> bool:
    if _ACCENTS.search(text):
        return True
    words = _WORD.findall(text.lower())
    return sum(1 for w in words if w in _MARKERS) >= 2


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:100]


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                ids.add(id(body[0].value))
    return ids


def scan_module(path: Path) -> list[str]:
    """Sorted, de-duplicated Spanish literals of one module (docstrings skipped)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _docstring_ids(tree)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            text = _norm(node.value)
            if len(text) >= 3 and _looks_spanish(text):
                found.add(text)
    return sorted(found)


def scan() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for rel in SCANNED:
        path = PKG / rel
        if path.exists():
            literals = scan_module(path)
            if literals:
                out[rel] = literals
    return out


def load_baseline() -> dict[str, list[str]]:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def new_literals(current: dict[str, list[str]], baseline: dict[str, list[str]]) -> dict[str, list[str]]:
    """Literals present now and absent from the baseline, per module."""
    fresh: dict[str, list[str]] = {}
    for rel, literals in current.items():
        extra = sorted(set(literals) - set(baseline.get(rel, ())))
        if extra:
            fresh[rel] = extra
    return fresh


def main(argv: list[str]) -> int:
    current = scan()
    if "--update" in argv:
        BASELINE.write_text(
            json.dumps(current, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        total = sum(len(v) for v in current.values())
        print(f"baseline written: {total} literals in {len(current)} modules")
        return 0
    fresh = new_literals(current, load_baseline())
    for rel, literals in fresh.items():
        for text in literals:
            print(f"NEW  {rel}: {text}")
    return 1 if fresh else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
