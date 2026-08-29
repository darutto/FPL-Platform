"""i25 — offline preflight: does every entity the battery pins still exist?

The corpus expires and nothing says so. Found by reading one case: `pv-11` asks
about Gordon, who left in this window. An audit of the 90 corpus questions plus
the battery's own cases against the live bootstrap found **9 stale cases**,
concentrated in captaincy (4 of 12).

Why this and not a patch of the nine names: fixing today's names buys nothing,
because this degrades again every transfer window. The check is the deliverable.
It runs **offline, before a cent is spent**, and aborts naming the expired cases.

What staleness does to a result
-------------------------------
It does not merely lose a case, it *manufactures* findings. The first reference
run reported `pv-11` failing `synthesis_present` 3/3 and called it a
deterministic reproduction of i46. It is not: there is nothing to synthesise
because `get_player_snapshot('Gordon')` returns `not_found`. The defect is real
at a lower rate; the repro was an artefact.

So stale cases are **excluded from scoring with the reason recorded**, and both
denominators are reported. They are not silently dropped and not counted.

Rewriting the nine questions is deliberately NOT done here: #171, i38 and i41
were scored against that exact text, and changing it in the same commit that
records a reference row would mix two things. Substitution is separate work.

Self-maintaining by construction
--------------------------------
Entity names are declared once and reviewed; the case→entity mapping is derived
by scanning the questions at runtime with the same regex used to build the
declaration. A question added later whose capitalised tokens are in neither
``ENTITIES`` nor ``NON_ENTITIES`` raises, so the declaration cannot go quietly
out of date the way the corpus did.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

PLAYER = "player"
TEAM = "team"

OK = "ok"
NOT_FOUND = "not_found"
AMBIGUOUS = "ambiguous"

#: Capitalised tokens that name a real FPL entity. Reviewed once; membership is
#: what the preflight resolves on every run.
ENTITIES: dict[str, str] = {
    # players
    "Bruno Fernandes": PLAYER, "Bukayo Saka": PLAYER, "Declan Rice": PLAYER,
    "Enzo Fernández": PLAYER, "Gabriel Jesus": PLAYER, "Gordon": PLAYER,
    "Haaland": PLAYER, "Isak": PLAYER, "Mbeumo": PLAYER, "Mitoma": PLAYER,
    "Palmer": PLAYER, "Rashford": PLAYER, "Rodri": PLAYER, "Saka": PLAYER,
    "Salah": PLAYER, "Solanke": PLAYER, "Son": PLAYER, "Sterling": PLAYER,
    "Watkins": PLAYER,
    # teams
    "Aston Villa": TEAM, "Brighton": TEAM, "Chelsea": TEAM, "Everton": TEAM,
    "Fulham": TEAM, "Liverpool": TEAM, "Manchester City": TEAM,
    "Newcastle": TEAM, "Wolves": TEAM, "El Bournemouth": TEAM,
}

#: Capitalised tokens that are Spanish words, not entities. Reviewed alongside
#: ENTITIES; together the two sets must cover every candidate the scan finds.
NON_ENTITIES: frozenset[str] = frozenset({
    "Analizá", "Bench", "Busco", "Contame", "Contra", "Conviene", "Cuál",
    "Cuáles", "Cuánto", "Cómo", "Debería", "En", "Es", "Estamos", "Está",
    "Falta", "Hay", "Le", "Los", "Me", "Premier", "Quién", "Quiénes", "Qué",
    "Saco", "Si", "Vale",
})

#: Team names as written in questions -> the bootstrap's own naming. The
#: bootstrap abbreviates, so a literal comparison reports a live team as gone:
#: "Manchester City" is stored as "Man City".
_TEAM_ALIASES: dict[str, str] = {
    "El Bournemouth": "Bournemouth",
    "Manchester City": "Man City",
}

_CANDIDATE = re.compile(
    r"(?<![.¿¡!]\s)(?<!^)\b([A-ZÁÉÍÓÚÑ][\wáéíóúñü]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñü]+)?)"
)


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def scan_candidates(question: str) -> list[str]:
    """Capitalised tokens that might name an entity. Discovery, not judgement."""
    return _CANDIDATE.findall(question)


def entities_in(question: str) -> list[tuple[str, str]]:
    """Declared entities named by a question.

    Raises on an undeclared candidate: a question added later must be reviewed
    rather than silently contributing an unchecked entity.
    """
    found: list[tuple[str, str]] = []
    for candidate in scan_candidates(question):
        if candidate in ENTITIES:
            found.append((candidate, ENTITIES[candidate]))
        elif candidate not in NON_ENTITIES:
            raise SystemExit(
                f"golden_preflight: undeclared capitalised token {candidate!r} in "
                f"{question!r}. Add it to ENTITIES (with its kind) or to "
                f"NON_ENTITIES. This is the review step that keeps the pin list "
                f"from going stale the way the corpus did."
            )
    return found


# ---------------------------------------------------------------------------
# Resolution against a bootstrap — offline, no network
# ---------------------------------------------------------------------------

def _resolve_team(name: str, bootstrap: dict[str, Any]) -> str:
    wanted = _fold(_TEAM_ALIASES.get(name, name))
    names = [(_fold(t.get("name", "")), _fold(t.get("short_name", "")))
             for t in bootstrap.get("teams") or []]
    if any(wanted in pair for pair in names):
        return OK
    # A containment fallback, but only when it identifies exactly one team --
    # "City" alone matches Coventry, Hull and Man City and must not resolve.
    hits = [full for full, _short in names if wanted and wanted in full]
    return OK if len(hits) == 1 else NOT_FOUND


def _resolve_player(name: str, bootstrap: dict[str, Any]) -> str:
    from fpl_grounded_assistant.find_players import find_players

    result = find_players(name, limit=5, bootstrap=bootstrap)
    if result.get("status") != "ok" or not result.get("matches"):
        return NOT_FOUND

    # Only exact (rank 0) and prefix (rank 1) hits mean the NAMED player is
    # still here. Substring hits do not: "Son" fuzzy-matches Emersonn,
    # Armstrong and Anderson, and "Rodri" matches Rodríguez and Rodrigo, while
    # the player each question was written about has left. Accepting those
    # would report a departed player as present -- the precise failure this
    # preflight exists to catch.
    # NB: `or 99` here would be a bug -- match_rank 0 IS the exact match and is
    # falsy, so the idiom silently discards every exact hit and reports live
    # players as departed. Exactly the instrument failure this card exists to
    # remove; caught only because "Haaland not_found" was obviously wrong.
    def _rank(match: dict[str, Any]) -> int:
        rank = match.get("match_rank")
        return 99 if rank is None else int(rank)

    strong = [m for m in result["matches"] if _rank(m) <= 1]
    if not strong:
        return NOT_FOUND
    if len(strong) > 1:
        # The name still exists but no longer identifies one player, so the
        # tool would stop and ask. The question stops measuring what it was
        # written to measure even though nobody left.
        return AMBIGUOUS
    return OK


@dataclass(frozen=True)
class StaleCase:
    case_id: str
    entity: str
    kind: str
    status: str

    @property
    def reason(self) -> str:
        return f"{self.kind} {self.entity!r} resolves {self.status}"


def check(cases: dict[str, str], bootstrap: dict[str, Any]) -> list[StaleCase]:
    """Resolve every pinned entity. Returns one StaleCase per broken pin.

    ``cases`` maps case id -> question text.
    """
    resolved: dict[tuple[str, str], str] = {}
    stale: list[StaleCase] = []
    for case_id, question in cases.items():
        for name, kind in entities_in(question):
            key = (name, kind)
            if key not in resolved:
                resolved[key] = (
                    _resolve_player(name, bootstrap) if kind == PLAYER
                    else _resolve_team(name, bootstrap)
                )
            if resolved[key] != OK:
                stale.append(StaleCase(case_id, name, kind, resolved[key]))
    return stale


def format_report(stale: list[StaleCase]) -> str:
    if not stale:
        return "preflight: every pinned entity resolves."
    by_entity: dict[tuple[str, str], list[str]] = {}
    for item in stale:
        by_entity.setdefault((item.entity, item.status), []).append(item.case_id)
    lines = [f"preflight: {len({s.case_id for s in stale})} stale case(s):"]
    for (entity, status), ids in sorted(by_entity.items()):
        lines.append(f"  {entity:<18} {status:<11} {', '.join(sorted(set(ids)))}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    import measure_tool_routing as base

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bootstrap", default=None,
                    help="bootstrap JSON; omit to fetch the live one")
    args = ap.parse_args(argv)

    base._configure_imports()
    import golden_axes as gx

    cases: dict[str, str] = {}
    for axis in gx.build_axes("full"):
        for case in axis.cases:
            cases.setdefault(case.id, case.question)

    if args.bootstrap:
        bootstrap = json.loads(Path(args.bootstrap).read_text(encoding="utf-8"))
    else:
        from fpl_api_client.fpl_client import get_bootstrap
        bootstrap = get_bootstrap()

    stale = check(cases, bootstrap)
    print(format_report(stale))
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
