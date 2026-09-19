"""i100, deterministic level -- the two HTTP routes serialize ONE turn the same.

The UI sends the first turn by ``POST /ask`` and every later one by
``POST /session/{id}/ask``. Two routes, two serializers (harness_adapter's
generic ``_to_dict`` vs the hand-written bundles in ``fpl_server.session_ask``).
i97 found the zonal card thinner on the session route and i102 found the
calendar card missing on both; this pins the whole surface, not one field.

Method: ONE stubbed orchestrator result per intent family (real tool outputs
produced offline by ``run_tool`` on STANDARD_BOOTSTRAP where the tool works
offline; the i97/i102 synthetic payloads for the two store-backed cards),
served through both routes, then the two JSON bodies are flattened to dotted
paths and compared -- presence AND value of every nested leaf. Only the keys
that are structural to a route are excluded, listed once, by name.

A live turn may differ between the routes for a legitimate reason (session
history, reference resolution); this test removes that reason by construction
(same stubbed result, fresh session) so what is left is serialization only.
"""
from __future__ import annotations

import copy
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
import fpl_grounded_assistant  # noqa: E402,F401  (registers every tool)
from fpl_tool_runner import run_tool  # noqa: E402
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant.orchestrator import OUTCOME_OK, OrchestratorResult  # noqa: E402
from fpl_grounded_assistant.quota import reset_quota  # noqa: E402

#: Keys that exist on one route by construction. Everything else -- every
#: card, every audit field, every scalar -- must be identical.
ROUTE_STRUCTURAL_KEYS: frozenset[str] = frozenset({
    "session_id",           # session only: the id the client opened
    "rewritten_question",   # session only: reference resolution echo
    "web_search",           # /ask only: premium opt-in payload slot
    "debug",                # different shapes by design (routing_trace vs session debug)
})


def _tool_output(name: str, args: dict) -> dict:
    out = run_tool(name, dict(args), copy.deepcopy(STANDARD_BOOTSTRAP))
    assert out.get("status") == "ok", (name, out)
    return out


def _zonal_payload() -> dict:
    return {
        "status": "ok", "opponent": "Chelsea", "weakness_label": "centro del área", "verdict": "attack the centre",
        "zones": [{"lateral": "left", "pct_over_avg": -5.0, "opportunity_level": "cold"},
                  {"lateral": "central", "pct_over_avg": 26.1, "opportunity_level": "hot"},
                  {"lateral": "right", "pct_over_avg": 120.3, "opportunity_level": "hot"}],
        "exploiters": [{"rank": 1, "web_name": "P1", "team_short": "EVE", "position": "FWD", "zone": "central",
                        "fit_score": 9.0, "n_shots": 14, "zone_share": 0.79, "sample": "ok", "zone_shots": 11,
                        "set_piece_share": 0.1, "origin": "open_play", "gameweek": 5, "is_home": False,
                        "club_source": "store", "club_note": None}],
        "penalty_context": {"penalty_xga_per_game": 0.12},
        "data_provenance": {"season": "2026-2027", "season_label": "2026/27", "live_season": "2026-2027",
                            "is_current": True, "status": "current", "label": "temporada actual",
                            "ingested_at": "2026-09-14T06:13:26Z", "n_matches": 40, "n_shots": 1012},
        "team_filter": {"requested": "rivales", "matched": "rivales", "source": "fixtures", "min_shots": 5,
                        "zone_share_threshold": 0.4, "requested_teams": ["BRE"], "matched_teams": ["BRE"],
                        "unmatched_teams": [], "fixture_window": {"from_gw": 5, "to_gw": 9, "horizon": 5},
                        "fixtures": [{"gameweek": 5, "team": "BRE", "is_home": True}]},
        "weakness_strength": "clear",
    }


def _outlook_payload() -> dict:
    def gw(n, band, klass, opp, home):
        return {"gameweek": n, "band": band, "klass": klass, "is_dgw": False, "is_bgw": band is None,
                "fixtures": [] if band is None else [{"opponent_short": opp, "is_home": home, "band": band}]}
    return {"status": "ok", "axis": "attack", "horizon": 5, "current_gameweek": 5,
            "teams": [{"team_short": "ARS", "team_name": "Arsenal", "axis": "attack", "avg_band": 2.25,
                       "verdict": "racha favorable J6-J8",
                       "series": [gw(5, 3, "neutral", "MCI", False), gw(6, 2, "good", "BUR", True),
                                  gw(7, 2, "good", "SUN", False), gw(8, 2, "good", "WOL", True), gw(9, None, "blank", "", False)],
                       "runs": [{"type": "good", "start_gw": 6, "end_gw": 8, "length": 3, "intensity": "mild"}]}]}


NAMES = [e["web_name"] for e in STANDARD_BOOTSTRAP["elements"]]

#: (id, question, tool, args, payload factory)
CASES = [
    ("captain_ranking", "¿A quién capitaneo esta jornada?", "rank_captain_candidates", {},
     lambda: _tool_output("rank_captain_candidates", {})),
    ("comparison", f"¿Quién es mejor, {NAMES[0]} o {NAMES[1]}?", "compare_players",
     {"query_a": NAMES[0], "query_b": NAMES[1]},
     lambda: _tool_output("compare_players", {"query_a": NAMES[0], "query_b": NAMES[1]})),
    ("generic_card", "¿Quiénes son los máximos anotadores?", "rank_players_by_metric", {"metric": "total_points"},
     lambda: _tool_output("rank_players_by_metric", {"metric": "total_points"})),
    ("transfer_suggestion", "¿Qué mediocampista fichar?", "get_transfer_suggestion", {"position_query": "MID"},
     lambda: _tool_output("get_transfer_suggestion", {"position_query": "MID"})),
    ("injury_list", "¿Quién está lesionado?", "get_injury_list", {},
     lambda: _tool_output("get_injury_list", {})),
    ("zonal_opportunity", "¿Qué jugadores pueden explotar la zona más débil del Chelsea?", "get_zonal_opportunity",
     {"opponent": "Chelsea"}, _zonal_payload),
    ("fixture_outlook", "¿Cómo pinta el calendario del Arsenal?", "get_fixture_outlook",
     {"team_query": "Arsenal", "axis": "attack", "horizon": 5}, _outlook_payload),
]


def _result(question: str, tool: str, args: dict, payload: dict) -> OrchestratorResult:
    return OrchestratorResult(
        question=question, tool_chosen=tool, tool_args=args, tool_output=payload,
        answer_text="Respuesta sintetizada de prueba.", llm_used=True, model="stub-model", outcome=OUTCOME_OK,
        primary_input_tokens=900, primary_output_tokens=120, total_tokens=1020, tool_call_count=1,
        tool_calls_trace=({"round": 1, "tool_call_id": "call_0", "name": tool, "args": args,
                           "output": payload, "success": True},),
        synthesis_turn=True,
    )


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._sessions.clear()
    reset_quota()
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-never-used")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: None)
    yield TestClient(fpl_server.app)
    fpl_server._sessions.clear()
    reset_quota()


def _flatten(prefix: str, value) -> dict[str, object]:
    out: dict[str, object] = {}
    if isinstance(value, dict):
        for k, v in value.items():
            out.update(_flatten(f"{prefix}.{k}" if prefix else k, v))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out.update(_flatten(f"{prefix}[{i}]", v))
    else:
        out[prefix] = value
    return out


@pytest.mark.parametrize("case_id,question,tool,args,payload", CASES, ids=[c[0] for c in CASES])
def test_both_routes_serialize_the_same_turn_identically(server, monkeypatch, case_id, question, tool, args, payload):
    result = _result(question, tool, args, payload())
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: result)

    ask = server.post("/ask", json={"question": question}, headers={"X-User-Id": f"i100-{case_id}-a"})
    sid = server.post("/session").json()["session_id"]
    sess = server.post(f"/session/{sid}/ask", json={"question": question}, headers={"X-User-Id": f"i100-{case_id}-s"})
    assert ask.status_code == 200 and sess.status_code == 200
    a, s = ask.json(), sess.json()
    assert a["outcome"] == "ok" and a["intent"] == s["intent"], (a["outcome"], a["intent"], s["intent"])

    only_ask = set(a) - set(s)
    only_sess = set(s) - set(a)
    assert only_ask <= ROUTE_STRUCTURAL_KEYS and only_sess <= ROUTE_STRUCTURAL_KEYS, (only_ask, only_sess)

    fa = _flatten("", {k: v for k, v in a.items() if k not in ROUTE_STRUCTURAL_KEYS})
    fs = _flatten("", {k: v for k, v in s.items() if k not in ROUTE_STRUCTURAL_KEYS})
    missing = sorted(set(fa) - set(fs))
    extra = sorted(set(fs) - set(fa))
    differing = {k: (fa[k], fs[k]) for k in fa if k in fs and fa[k] != fs[k]}
    assert not missing and not extra and not differing, (
        f"{case_id}: session != /ask\n  missing on session: {missing}\n  extra on session: {extra}\n"
        f"  different values: {differing}"
    )


def test_the_structural_exclusions_are_the_only_ones(server, monkeypatch):
    """The exclusion list must not grow silently: on a plain turn the two
    bodies differ in exactly those keys, no more, no fewer."""
    case_id, question, tool, args, payload = CASES[0]
    result = _result(question, tool, args, payload())
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: result)
    a = server.post("/ask", json={"question": question, "debug": True}, headers={"X-User-Id": "i100-x-a"}).json()
    sid = server.post("/session").json()["session_id"]
    s = server.post(f"/session/{sid}/ask", json={"question": question, "debug": True}, headers={"X-User-Id": "i100-x-s"}).json()
    asymmetric = (set(a) ^ set(s)) | {k for k in set(a) & set(s) if a[k] != s[k] and k == "debug"}
    assert asymmetric == ROUTE_STRUCTURAL_KEYS, asymmetric
