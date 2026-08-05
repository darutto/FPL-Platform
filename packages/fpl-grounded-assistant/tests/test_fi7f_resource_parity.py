from __future__ import annotations

import copy
import json

import pytest

from fpl_grounded_assistant.decision_router import decide
from fpl_grounded_assistant.harness import ask_v2
from fpl_grounded_assistant.input_normalizer import ResourceInput, normalize
from fpl_grounded_assistant.intent_aliases import list_resources, resolve_resource
from fpl_grounded_assistant.resource_registry import (
    list_resource_specs,
    run_resource,
)
import fpl_grounded_assistant.resource_registry as registry


_EXISTING = (
    "injuries", "top_form", "top_xg", "top_points", "top_minutes", "popular",
)
_MINUTES_COLUMNS = [
    "web_name", "team_short", "position", "value", "unit", "scope", "provenance",
]
_ROLE_COLUMNS = [
    "web_name", "team_short", "role", "role_kind", "provenance",
]


@pytest.fixture
def fi_bootstrap(bootstrap: dict) -> dict:
    data = copy.deepcopy(bootstrap)
    for index, element in enumerate(data["elements"]):
        element["minutes"] = index * 100
    return data


def _payload(question: str, bootstrap: dict) -> dict:
    result = decide(question, bootstrap)
    assert result["outcome"] == "ok"
    return result["resource_rows"]


def test_registration_order_public_forms_and_internal_keys() -> None:
    assert list_resources() == _EXISTING + ("player_minutes", "player_role")
    assert tuple(spec.name for spec in list_resource_specs()) == list_resources()
    assert len(set(list_resources())) == 8
    assert resolve_resource("minutes") == "top_minutes"
    assert resolve_resource("player_minutes") is None
    assert resolve_resource("player_role") is None


def test_existing_six_resource_bytes_are_unchanged(fi_bootstrap: dict) -> None:
    before = {
        name: json.dumps(run_resource(name, fi_bootstrap).to_dict(), separators=(",", ":"))
        for name in _EXISTING
    }
    after = {
        name: json.dumps(run_resource(name, fi_bootstrap).to_dict(), separators=(",", ":"))
        for name in _EXISTING
    }
    assert after == before


def test_bare_minutes_remains_top_minutes(fi_bootstrap: dict) -> None:
    bare = decide("@minutes", fi_bootstrap)
    canonical = decide("@top_minutes", fi_bootstrap)
    assert bare["resource"] == "top_minutes"
    assert bare["resource_rows"] == canonical["resource_rows"]


@pytest.mark.parametrize("question", ["@player_minutes", "@player_role"])
def test_internal_keys_are_not_public_commands(question: str, fi_bootstrap: dict) -> None:
    assert decide(question, fi_bootstrap)["outcome"] == "unsupported"


def test_argument_parsing_preserves_internal_whitespace_and_case() -> None:
    norm = normalize("  @MiNuTeS   Bukayo    Saka  ")
    assert isinstance(norm, ResourceInput)
    assert norm.canonical == "player_minutes"
    assert norm.argument == "Bukayo    Saka"
    assert norm.shape_reason is None


@pytest.mark.parametrize("question", ["@role", "@ROLE   "])
def test_role_missing_argument_is_governed_degradation(question: str, fi_bootstrap: dict) -> None:
    payload = _payload(question, fi_bootstrap)
    assert payload["status"] == "unavailable"
    assert payload["reason"] == "missing_player_argument"
    assert payload["rows"] == []


@pytest.mark.parametrize(
    "argument",
    ["Saka --team ARS", "x" * 101, "Sa\x00ka", "Sa\x1fka", "Sa\x7fka", "Sa\x85ka"],
)
def test_invalid_shape_stops_before_resolver(
    argument: str,
    fi_bootstrap: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args, **_kwargs):
        raise AssertionError("resolver must not run")

    monkeypatch.setattr(registry, "tool_resolve_player", fail)
    payload = _payload(f"@minutes {argument}", fi_bootstrap)
    assert payload["reason"] == "invalid_command_shape"


def test_structurally_unusable_bootstrap_stops_before_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args, **_kwargs):
        raise AssertionError("resolver must not run")

    monkeypatch.setattr(registry, "tool_resolve_player", fail)
    payload = _payload("@minutes Saka", {"elements": [], "teams": []})
    assert payload["reason"] == "resource_data_unavailable"


def test_resolver_receives_exact_query_once(fi_bootstrap: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real = registry.tool_resolve_player

    def spy(query, bootstrap):
        calls.append(query)
        return real(query, bootstrap)

    monkeypatch.setattr(registry, "tool_resolve_player", spy)
    _payload("@minutes   Bukayo    Saka", fi_bootstrap)
    assert calls == ["Bukayo    Saka"]


@pytest.mark.parametrize(
    ("resolver_result", "reason"),
    [
        ({"status": "not_found"}, "unresolved_player"),
        ({"status": "ambiguous"}, "ambiguous_player"),
        ({"status": "other"}, "resource_data_unavailable"),
        ({"status": "ok"}, "resource_data_unavailable"),
        (None, "resource_data_unavailable"),
    ],
)
def test_resolver_outcomes_degrade_honestly(
    resolver_result,
    reason: str,
    fi_bootstrap: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry, "tool_resolve_player", lambda *_: resolver_result)
    assert _payload("@minutes Saka", fi_bootstrap)["reason"] == reason


def test_duplicate_resolved_id_is_resource_data_unavailable(
    fi_bootstrap: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fi_bootstrap["elements"].append(copy.deepcopy(fi_bootstrap["elements"][2]))
    monkeypatch.setattr(
        registry,
        "tool_resolve_player",
        lambda *_: {
            "status": "ok", "player_id": 3, "web_name": "Saka",
            "team_short": "ARS", "position": "MID",
        },
    )
    assert _payload("@minutes Saka", fi_bootstrap)["reason"] == "resource_data_unavailable"


def test_minutes_success_envelope_zero_and_order(fi_bootstrap: dict) -> None:
    payload = _payload("@minutes Haaland", fi_bootstrap)
    assert list(payload) == [
        "resource", "title", "columns", "rows", "data_age", "status", "reason",
    ]
    assert payload == {
        "resource": "player_minutes",
        "title": "Player Minutes",
        "columns": _MINUTES_COLUMNS,
        "rows": [{
            "web_name": "Haaland",
            "team_short": "MCI",
            "position": "FWD",
            "value": 0,
            "unit": "minutes",
            "scope": "current_season_to_bootstrap",
            "provenance": "fpl_bootstrap.elements.minutes",
        }],
        "data_age": "current_bootstrap",
        "status": "ok",
        "reason": None,
    }


@pytest.mark.parametrize("bad", [None, -1, 1.5, "100", True, False])
def test_invalid_minutes_never_coerce(bad, fi_bootstrap: dict) -> None:
    fi_bootstrap["elements"][2]["minutes"] = bad
    payload = _payload("@minutes Saka", fi_bootstrap)
    assert payload["reason"] == "minutes_unavailable"
    assert payload["rows"] == []


@pytest.mark.parametrize(("element_type", "role"), [(1, "GKP"), (2, "DEF"), (3, "MID"), (4, "FWD")])
def test_role_mappings_are_nominal_only(
    element_type: int,
    role: str,
    fi_bootstrap: dict,
) -> None:
    fi_bootstrap["elements"][2]["element_type"] = element_type
    payload = _payload("@role Saka", fi_bootstrap)
    assert payload["columns"] == _ROLE_COLUMNS
    assert payload["rows"] == [{
        "web_name": "Saka",
        "team_short": "ARS",
        "role": role,
        "role_kind": "nominal_fpl_position",
        "provenance": "fpl_bootstrap.elements.element_type",
    }]
    assert "confidence" not in payload["rows"][0]
    assert "evidence" not in payload["rows"][0]


@pytest.mark.parametrize("bad", [None, 0, 5, "3", True, False])
def test_invalid_role_is_unavailable(bad, fi_bootstrap: dict) -> None:
    fi_bootstrap["elements"][2]["element_type"] = bad
    assert _payload("@role Saka", fi_bootstrap)["reason"] == "role_unavailable"


def test_reversal_and_replay_are_byte_stable(fi_bootstrap: dict) -> None:
    first = _payload("@minutes Saka", fi_bootstrap)
    reversed_bootstrap = copy.deepcopy(fi_bootstrap)
    reversed_bootstrap["elements"].reverse()
    second = _payload("@minutes Saka", reversed_bootstrap)
    assert json.dumps(first, separators=(",", ":")) == json.dumps(second, separators=(",", ":"))
    assert first == _payload("@minutes Saka", copy.deepcopy(fi_bootstrap))


def test_ask_v2_transports_resource_rows_unchanged(fi_bootstrap: dict) -> None:
    expected = _payload("@role Saka", fi_bootstrap)
    result = ask_v2("@role Saka", fi_bootstrap)
    assert result["kind"] == "resource"
    assert result["resource_rows"] == expected
    assert result.get("evidence") is None


def test_resource_execution_is_flag_independent(
    fi_bootstrap: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOOTBALL_INTELLIGENCE_ENABLED", "OFF")
    off = _payload("@minutes Saka", fi_bootstrap)
    monkeypatch.setenv("FOOTBALL_INTELLIGENCE_ENABLED", "ON")
    on = _payload("@minutes Saka", fi_bootstrap)
    assert on == off
