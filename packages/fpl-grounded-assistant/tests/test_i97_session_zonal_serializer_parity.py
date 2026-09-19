"""i97 -- the session path serves the SAME zonal card /ask serves.

Two HTTP routes served the same ``DefensiveZonesMeta`` through two
serializers: ``POST /ask`` via ``harness_adapter._to_dict`` (the generic
dataclass walk, every field) and ``POST /session/{id}/ask`` via a hand
list in ``fpl_server._zonal_opportunity_meta_dict`` that carried six fields
per exploiter and none of i85-i91's / i75's additions (``team_filter``,
``weakness_strength``, ``has_exploiters``, ``club_source`` / ``club_note``,
``n_shots``, ``zone_share``, ...). The UI sends the first turn by /ask and
the rest by session, so a follow-up zonal question got a thinner card than
the opening one.

The test does not read the code: it builds ONE orchestrator result for a
zonal turn, serves it through both routes, and compares what the two JSON
bodies actually carry -- keys AND values, the full nested payload. Restoring
the old serializer fails it naming the fields that went missing.
"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_PKGS = os.path.dirname(_PKG)
for _path in [
    _PKG,
    os.path.join(_PKGS, "fpl-api-client"),
    os.path.join(_PKGS, "fpl-data-core"),
    os.path.join(_PKGS, "fpl-player-registry"),
    os.path.join(_PKGS, "fpl-query-tools"),
    os.path.join(_PKGS, "fpl-tool-contract"),
    os.path.join(_PKGS, "fpl-tool-runner"),
    os.path.join(_PKGS, "fpl-captain-engine"),
]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

import fpl_server  # noqa: E402
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant.orchestrator import OUTCOME_OK, OrchestratorResult  # noqa: E402
from fpl_grounded_assistant.quota import reset_quota  # noqa: E402

QUESTION = "¿Qué jugadores pueden explotar la zona más débil de la defensa del Chelsea?"
TOOL = "get_zonal_opportunity"


def _exploiter(rank: int, **extra) -> dict:
    row = {
        "rank": rank, "web_name": f"P{rank}", "team_short": "EVE", "position": "FWD",
        "zone": "central", "fit_score": 10.0 - rank,
        # i88-i90 / i75 fields the hand list never carried:
        "n_shots": 14, "zone_share": 0.79, "sample": "ok", "zone_shots": 11,
        "set_piece_share": 0.1, "origin": "open_play", "gameweek": 5, "is_home": False,
        "club_source": "store", "club_note": None,
    }
    row.update(extra)
    return row


def _zonal_payload() -> dict:
    return {
        "status": "ok",
        "opponent": "Chelsea",
        "weakness_label": "centro del área",
        "verdict": "attack the centre",
        "zones": [
            {"lateral": "left", "pct_over_avg": -5.0, "opportunity_level": "cold"},
            {"lateral": "central", "pct_over_avg": 26.1, "opportunity_level": "hot"},
            {"lateral": "right", "pct_over_avg": 120.3, "opportunity_level": "hot"},
        ],
        "exploiters": [
            _exploiter(1),
            _exploiter(2, team_short="MUN", club_source="bootstrap", club_note="moved from BRE in the window"),
        ],
        "penalty_context": {"penalty_xga_per_game": 0.12},
        "data_provenance": {
            "season": "2026-2027", "season_label": "2026/27", "live_season": "2026-2027",
            "is_current": True, "status": "current", "label": "temporada actual",
            "ingested_at": "2026-09-14T06:13:26Z", "n_matches": 40, "n_shots": 1012,
        },
        "team_filter": {
            "requested": "rivales", "matched": "rivales", "source": "fixtures",
            "min_shots": 5, "zone_share_threshold": 0.4,
            "requested_teams": ["BRE", "BOU"], "matched_teams": ["BRE", "BOU"], "unmatched_teams": [],
            "fixture_window": {"from_gw": 5, "to_gw": 9, "horizon": 5},
            "fixtures": [{"gameweek": 5, "team": "BRE", "is_home": True}],
        },
        "weakness_strength": "clear",
    }


def _zonal_result(payload: dict) -> OrchestratorResult:
    trace = ({
        "round": 1, "tool_call_id": "call_0", "name": TOOL,
        "args": {"opponent": "Chelsea"}, "output": payload, "success": True,
    },)
    return OrchestratorResult(
        question=QUESTION,
        tool_chosen=TOOL,
        tool_args={"opponent": "Chelsea"},
        tool_output=payload,
        answer_text="La zona más débil del Chelsea es el centro del área.",
        llm_used=True,
        model="stub-model",
        outcome=OUTCOME_OK,
        primary_input_tokens=900, primary_output_tokens=120, total_tokens=1020,
        tool_call_count=1,
        tool_calls_trace=trace,
        synthesis_turn=True,
    )


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._sessions.clear()
    reset_quota()
    # Fresh, already-audited quota keys; no audit file writes from this test.
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: None)
    yield TestClient(fpl_server.app)
    fpl_server._sessions.clear()
    reset_quota()


@pytest.fixture
def stub_zonal_orchestrator(monkeypatch: pytest.MonkeyPatch):
    result = _zonal_result(_zonal_payload())
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-never-used")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: result)
    return result


def _walk(prefix: str, value) -> dict[str, object]:
    """Flatten a JSON payload to {dotted.path: leaf} so a diff names fields."""
    out: dict[str, object] = {}
    if isinstance(value, dict):
        for k, v in value.items():
            out.update(_walk(f"{prefix}.{k}" if prefix else k, v))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out.update(_walk(f"{prefix}[{i}]", v))
    else:
        out[prefix] = value
    return out


def _both_routes(server: TestClient) -> tuple[dict, dict]:
    ask = server.post("/ask", json={"question": QUESTION}, headers={"X-User-Id": "u-i97-ask"})
    assert ask.status_code == 200
    sid = server.post("/session").json()["session_id"]
    sess = server.post(f"/session/{sid}/ask", json={"question": QUESTION}, headers={"X-User-Id": "u-i97-sess"})
    assert sess.status_code == 200
    return ask.json(), sess.json()


def test_session_zonal_card_is_the_same_payload_ask_serves(server, stub_zonal_orchestrator):
    ask, sess = _both_routes(server)
    assert ask["intent"] == "zonal_opportunity" == sess["intent"]
    assert ask["zonal_opportunity"] is not None and sess["zonal_opportunity"] is not None

    flat_ask = _walk("", ask["zonal_opportunity"])
    flat_sess = _walk("", sess["zonal_opportunity"])
    missing = sorted(set(flat_ask) - set(flat_sess))
    extra = sorted(set(flat_sess) - set(flat_ask))
    assert not missing and not extra, (
        f"session zonal card differs from /ask: missing={missing} extra={extra}"
    )
    differing = {k: (flat_ask[k], flat_sess[k]) for k in flat_ask if flat_ask[k] != flat_sess[k]}
    assert differing == {}, f"same keys, different values: {differing}"
    assert ask["zonal_opportunity"] == sess["zonal_opportunity"]


def test_the_fields_the_hand_list_dropped_reach_the_session_card(server, stub_zonal_orchestrator):
    """Named on purpose, so a regression says WHICH card fields went thin --
    not just 'the dicts differ'."""
    _ask, sess = _both_routes(server)
    zo = sess["zonal_opportunity"]
    first, second = zo["exploiters"]
    # i75: the club the row is stamped with, and where it came from
    assert first["club_source"] == "store" and first["club_note"] is None
    assert second["club_source"] == "bootstrap" and second["club_note"] == "moved from BRE in the window"
    # i88-i90: sample / zone detail behind fit_score
    assert first["n_shots"] == 14 and first["zone_share"] == 0.79 and first["zone_shots"] == 11
    assert first["origin"] == "open_play" and first["gameweek"] == 5 and first["is_home"] is False
    # i85-i87 team scope, i89 strength, i91 exploiter switch, i74 provenance
    assert zo["team_filter"]["matched_teams"] == ["BRE", "BOU"]
    assert zo["team_filter"]["fixture_window"] == {"from_gw": 5, "to_gw": 9, "horizon": 5}
    assert zo["weakness_strength"] == "clear"
    assert zo["has_exploiters"] is True
    assert zo["data_provenance"]["season"] == "2026-2027"


def test_the_hand_serializer_is_gone():
    assert not hasattr(fpl_server, "_zonal_opportunity_meta_dict"), (
        "fpl_server._zonal_opportunity_meta_dict is back -- the session path "
        "must serialize DefensiveZonesMeta with harness_adapter._to_dict"
    )
