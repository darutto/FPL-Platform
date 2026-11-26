"""@xa: season expected assists, built like @top_xg. Synthetic data only; no provider, no network."""
from __future__ import annotations

import pytest

from fpl_grounded_assistant import intent_aliases
from fpl_grounded_assistant.decision_router import decide
from fpl_grounded_assistant.resource_registry import list_resource_specs
from fpl_grounded_assistant.table_conclusions import resource_ranking_conclusions


def _bootstrap() -> dict:
    # xA order differs from xGI order on purpose; xa values arrive as strings, as in the FPL payload.
    spec = [("Alfa", "9.00", "1.00"), ("Bravo", "1.00", "8.00"), ("Charlie", "2.50", "3.00"),
            ("Delta", "0.50", "9.50"), ("Echo", "2.00", "2.00"), ("Foxtrot", "1.50", "1.50")]
    elements = [{"id": i, "web_name": name, "team": i, "element_type": 3, "status": "a",
                 "expected_assists": xa, "expected_goal_involvements": xgi, "selected_by_percent": "50.0"}
                for i, (name, xa, xgi) in enumerate(spec, 1)]
    elements.append({"id": 99, "web_name": "Hurt", "team": 1, "element_type": 3, "status": "i",
                     "expected_assists": "20.00"})
    return {"elements": elements, "teams": [{"id": i, "short_name": f"T{i}"} for i in range(1, 7)], "events": []}


@pytest.mark.parametrize("command", [
    "@xa", "@XA", "  @Xa  ", "@top_xa", "@expected_assists", "@asistencias_esperadas", "@Asistencias_Esperadas",
])
def test_xa_commands_rank_season_expected_assists(command: str) -> None:
    result = decide(command, _bootstrap())
    assert result["outcome"] == "ok" and result["resource"] == "top_xa"
    payload = result["resource_rows"]
    assert payload["title"] == "Top xA — asistencias esperadas"
    assert payload["columns"] == ["web_name", "team_short", "position", "value"]
    assert [(r["web_name"], r["value"]) for r in payload["rows"][:3]] == [
        ("Alfa", 9.0), ("Charlie", 2.5), ("Echo", 2.0)]
    assert "Hurt" not in [r["web_name"] for r in payload["rows"]]


def test_xa_is_registered_next_to_xg_and_suggested() -> None:
    names = [spec.name for spec in list_resource_specs()]
    assert names[names.index("top_xg") + 1] == "top_xa"
    assert tuple(names) == intent_aliases.list_resources()
    assert "@top_xa" in decide("@nope", _bootstrap())["suggestions"]


def test_xa_conclusions_use_expected_assists() -> None:
    bootstrap = _bootstrap()
    payload = decide("@xa", bootstrap)["resource_rows"]
    conclusions = resource_ranking_conclusions("top_xa", payload, bootstrap)
    assert conclusions[0]["key"] == "gap"
    assert conclusions[0]["params"] == {"leaders": ["Alfa"], "metric": "expected_assists"}
    assert conclusions[-1]["key"] == "reading"


def test_no_alias_is_claimed_by_two_resources() -> None:
    claims: dict[str, set[str]] = {}
    for canonical in intent_aliases.RESOURCE_CANONICAL:
        for alias in (canonical, *intent_aliases._RAW_ALIASES.get(canonical, ())):
            claims.setdefault(intent_aliases._nfc_fold(alias), set()).add(canonical)
    assert {a: c for a, c in claims.items() if len(c) > 1} == {}
    assert intent_aliases.resolve_resource("esperados") == "top_xg"
    assert intent_aliases.resolve_resource("xg") == "top_xg"
