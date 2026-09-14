"""i80 + i36 + i57: the audit log and /healthz report what was produced, not
what a constant said.

One defect, three symptoms (Bloque 3, slice 2-E):

  * i80  POST /ask wrote ``retry_attempted=False`` as a literal and
         ``evaluator_verdict=None`` as a comment; POST /session/{id}/ask
         wrote ``tokens={}`` and no ``tool_calls`` at all. Both endpoints
         had the real values one dict away (``OrchestratorResult.retry_attempted``
         / ``.evaluator_verdict`` on the harness side, the ``ask_v2()`` dict
         on the session side) and discarded them.
  * i36  The session ``debug=true`` bundle carried no ``routing_trace``, so
         ``synthesis_turn`` / ``tool_call_count`` of a session turn were
         unobservable from the outside.
  * i57  ``/healthz`` said nothing about which mode the orchestrator runs in.

Every assertion below reads from the thing PRODUCED -- the NDJSON line the
real ``write_audit_entry`` wrote to a temp dir, or the JSON the endpoint
returned -- never from the variable that requested the data. The
orchestrator is a stubbed ``OrchestratorResult`` (no LLM, no network); the
env keys set here only satisfy the harness's "is a client reachable" gate.

Mutations (each applied and reverted on its own; results in the PR):
  M1  harness: drop the ``retry_attempted`` projection       -> harness + /ask tests die
  M2  harness: drop the ``evaluator_verdict`` projection     -> verdict tests die
  M3  harness: drop the ``tool_sequence`` projection         -> tool_sequence tests die
  M4  /ask: ``retry_attempted=False`` literal again          -> /ask audit test dies
  M5  /ask: ``evaluator_verdict=None`` literal again         -> /ask audit test dies
  M6  session: ``tokens={}`` literal again                   -> session tokens test dies
  M7  session: ``tool_calls`` dropped again                  -> session tool_calls test dies
  M8  session: ``orchestration_absent`` never set            -> legacy-path test dies
  M9  session: ``orchestration`` not stored on FinalResponse -> session tests + debug test die
  M10 /healthz: ``orchestrator`` block cached at import      -> setenv-in-test test dies
"""
from __future__ import annotations

import json
import os as _os
import sys as _sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PKG = _os.path.dirname(_HERE)
_PKGS = _os.path.dirname(_PKG)
for _p in [
    _PKG,
    _os.path.join(_PKGS, "fpl-api-client"),
    _os.path.join(_PKGS, "fpl-data-core"),
    _os.path.join(_PKGS, "fpl-player-registry"),
    _os.path.join(_PKGS, "fpl-query-tools"),
    _os.path.join(_PKGS, "fpl-tool-contract"),
    _os.path.join(_PKGS, "fpl-tool-runner"),
    _os.path.join(_PKGS, "fpl-captain-engine"),
    _os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import fpl_server  # noqa: E402
from fpl_grounded_assistant import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant import audit as audit_mod  # noqa: E402
from fpl_grounded_assistant.evaluator import EvaluatorVerdict  # noqa: E402
from fpl_grounded_assistant.harness import (  # noqa: E402
    ROUTING_TRACE_OPTIONAL_KEYS,
    ask_v2,
)
from fpl_grounded_assistant.orchestrator import (  # noqa: E402
    OUTCOME_OK,
    OUTCOME_TOOL_ERROR,
    OrchestratorResult,
)
from fpl_grounded_assistant.quota import reset_quota  # noqa: E402

TOOL = "rank_players_by_metric"
QUESTION = "jugadores con mas puntos"


# ---------------------------------------------------------------------------
# Stub orchestrator results -- the SOURCE the projection must read from
# ---------------------------------------------------------------------------

def _trace(*names: str) -> tuple[dict, ...]:
    return tuple(
        {
            "round": 1 if i == 0 else 2,
            "tool_call_id": f"call_{i}",
            "name": name,
            "args": {"metric": "total_points"},
            "output": {"status": "ok"},
            "success": True,
        }
        for i, name in enumerate(names)
    )


_REJECTED = EvaluatorVerdict(
    approved=False, grounded=True, complete=False, safe=True,
    retry_feedback="name the top three, not one", tokens_used=120,
)


def _rank_output(n: int = 3) -> dict:
    return {
        "status": "ok", "metric": "total_points", "top_n": n,
        "ranked": [
            {"rank": i + 1, "web_name": f"P{i}", "team_short": "MCI",
             "position": "FWD", "metric_value": float(100 - i)}
            for i in range(n)
        ],
    }


def _orch_result(
    *,
    retry_attempted: bool,
    verdict: EvaluatorVerdict | None,
    trace: tuple[dict, ...],
    outcome: str = OUTCOME_OK,
    tool_chosen: str | None = TOOL,
) -> OrchestratorResult:
    return OrchestratorResult(
        question=QUESTION,
        tool_chosen=tool_chosen,
        tool_args={"metric": "total_points"},
        tool_output=_rank_output() if outcome == OUTCOME_OK else {},
        answer_text="Haaland lidera; Palmer y Salah completan el podio.",
        llm_used=True,
        model="stub-model",
        outcome=outcome,
        evaluator_verdict=verdict,
        retry_attempted=retry_attempted,
        primary_input_tokens=900,
        primary_output_tokens=120,
        evaluator_input_tokens=120,
        retry_input_tokens=300 if retry_attempted else 0,
        retry_output_tokens=80 if retry_attempted else 0,
        total_tokens=1520 if retry_attempted else 1140,
        tool_call_count=len(trace),
        tool_calls_trace=trace,
        synthesis_turn=True,
    )


@pytest.fixture
def stub_orchestrator(monkeypatch: pytest.MonkeyPatch):
    """Stub ``ask_orchestrated`` (imported lazily by harness.ask_v2) and
    satisfy the harness's client-reachability gate with fake env keys.
    ``FPL_EVAL_DISABLED`` keeps ``_build_eval_client`` from touching a SDK."""
    holder: dict = {"result": None}
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-never-used")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *a, **k: holder["result"],
    )
    return holder


# ---------------------------------------------------------------------------
# Step 1 -- harness projects what OrchestratorResult already carries
# ---------------------------------------------------------------------------

def test_optional_keys_registry_declares_the_three_projected_keys():
    assert {"retry_attempted", "evaluator_verdict", "tool_sequence"} <= ROUTING_TRACE_OPTIONAL_KEYS


def test_harness_projects_retry_verdict_and_sequence_from_the_result(stub_orchestrator):
    """A retried turn: retry_attempted=True, a rejected verdict, the same
    tool executed twice. All three land on routing_trace exactly as the
    result says (M1/M2/M3 each kill this)."""
    stub_orchestrator["result"] = _orch_result(
        retry_attempted=True, verdict=_REJECTED, trace=_trace(TOOL, TOOL),
    )
    rt = ask_v2(QUESTION, STANDARD_BOOTSTRAP)["routing_trace"]
    assert rt["branch"] == "orchestrator"
    assert rt["retry_attempted"] is True
    assert rt["evaluator_verdict"] == {
        "approved": False, "grounded": True, "complete": False, "safe": True,
        "retry_feedback": "name the top three, not one",
    }
    assert rt["tool_sequence"] == [TOOL, TOOL]
    # The verdict projection is JSON-serialisable as-is (the audit line needs it).
    json.dumps(rt["evaluator_verdict"])


def test_harness_projects_false_and_none_when_no_retry_happened(stub_orchestrator):
    """Not-retried is projected as an explicit False / None from the result,
    not left absent -- absence would read the same as 'orchestrator never
    ran' downstream."""
    stub_orchestrator["result"] = _orch_result(
        retry_attempted=False, verdict=None, trace=_trace(TOOL),
    )
    rt = ask_v2(QUESTION, STANDARD_BOOTSTRAP)["routing_trace"]
    assert rt["retry_attempted"] is False
    assert rt["evaluator_verdict"] is None
    assert rt["tool_sequence"] == [TOOL]


def test_harness_projects_on_the_no_grounded_tool_branch_too(stub_orchestrator):
    """A retry that still failed to ground is still a retry: the
    unsupported branch carries the same three keys."""
    stub_orchestrator["result"] = _orch_result(
        retry_attempted=True, verdict=_REJECTED, trace=_trace(TOOL),
        outcome=OUTCOME_TOOL_ERROR,
    )
    result = ask_v2(QUESTION, STANDARD_BOOTSTRAP)
    rt = result["routing_trace"]
    assert rt["branch"] == "unsupported"
    assert rt["orchestrator_outcome"] == OUTCOME_TOOL_ERROR
    assert rt["retry_attempted"] is True
    assert rt["evaluator_verdict"]["approved"] is False
    assert rt["tool_sequence"] == [TOOL]


def test_harness_leaves_the_keys_absent_when_the_orchestrator_did_not_run(monkeypatch):
    """Deterministic branch (@resource): nothing to project, keys absent --
    so the endpoints' ``.get(..., False)`` means 'not run', not 'not retried'."""
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    rt = ask_v2("@gameweek", STANDARD_BOOTSTRAP)["routing_trace"]
    assert rt["orchestrator_called"] is False
    assert "retry_attempted" not in rt
    assert "evaluator_verdict" not in rt
    assert "tool_sequence" not in rt


# ---------------------------------------------------------------------------
# HTTP scaffolding: capture the AuditEntry the endpoint built, write it with
# the REAL writer to a temp dir, and assert from the line on disk.
# ---------------------------------------------------------------------------

@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._sessions.clear()
    reset_quota()
    yield TestClient(fpl_server.app)
    fpl_server._sessions.clear()
    reset_quota()


@pytest.fixture
def audit_lines(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Route the endpoints' ``write_audit_entry`` to the real writer on a temp
    dir and hand back a reader of the NDJSON lines it produced."""
    log_dir = str(tmp_path / "audit_logs")

    def _write(entry):
        audit_mod.write_audit_entry(entry, log_dir=log_dir)

    monkeypatch.setattr(fpl_server, "write_audit_entry", _write)

    def _read() -> list[dict]:
        lines: list[dict] = []
        if not _os.path.isdir(log_dir):
            return lines
        for name in sorted(_os.listdir(log_dir)):
            with open(_os.path.join(log_dir, name), encoding="utf-8") as fh:
                lines.extend(json.loads(ln) for ln in fh if ln.strip())
        return lines

    return _read


def _open_session(client: TestClient) -> str:
    resp = client.post("/session")
    assert resp.status_code == 200
    return resp.json()["session_id"]


# ---------------------------------------------------------------------------
# Step 3 / 6(a) -- POST /ask audits retry_attempted / evaluator_verdict
# ---------------------------------------------------------------------------

def test_ask_audit_line_carries_retry_attempted_true_from_the_result(
    server, audit_lines, stub_orchestrator,
):
    """The NDJSON line of a retried /ask turn says retry_attempted=true and
    carries the verdict. (M1 and M4 kill this; M5 kills the verdict half.)"""
    stub_orchestrator["result"] = _orch_result(
        retry_attempted=True, verdict=_REJECTED, trace=_trace(TOOL, TOOL),
    )
    resp = server.post("/ask", json={"question": QUESTION}, headers={"X-User-Id": "u-i80"})
    assert resp.status_code == 200
    lines = audit_lines()
    assert len(lines) == 1
    line = lines[0]
    assert line["branch"] == "orchestrator"
    assert line["retry_attempted"] is True
    assert line["evaluator_verdict"] == {
        "approved": False, "grounded": True, "complete": False, "safe": True,
        "retry_feedback": "name the top three, not one",
    }
    assert line["tokens"]["retry_input"] == 300
    assert line["tokens"]["total"] == 1520
    assert line["tool_calls"] == [
        {"name": TOOL, "args": {"metric": "total_points"}, "output_status": "ok"},
    ]
    assert line["orchestration_absent"] is False


def test_ask_audit_line_says_false_and_null_when_the_result_did_not_retry(
    server, audit_lines, stub_orchestrator,
):
    """Both directions: a non-retried result must not be written as retried."""
    stub_orchestrator["result"] = _orch_result(
        retry_attempted=False, verdict=None, trace=_trace(TOOL),
    )
    server.post("/ask", json={"question": QUESTION}, headers={"X-User-Id": "u-i80"})
    line = audit_lines()[0]
    assert line["retry_attempted"] is False
    assert line["evaluator_verdict"] is None


# ---------------------------------------------------------------------------
# Step 2 / 3 / 6(b) -- POST /session/{id}/ask audits what ask_v2 produced
# ---------------------------------------------------------------------------

def test_session_audit_line_carries_real_tokens_tool_calls_and_retry(
    server, audit_lines, stub_orchestrator,
):
    """The session line carries the tokens dict and the tool_calls list ask_v2
    produced, plus retry_attempted/evaluator_verdict off its routing_trace --
    and says orchestration_absent=false. (M6 kills tokens, M7 tool_calls, M9
    all of it.)"""
    stub_orchestrator["result"] = _orch_result(
        retry_attempted=True, verdict=_REJECTED, trace=_trace(TOOL, TOOL),
    )
    session_id = _open_session(server)
    resp = server.post(
        f"/session/{session_id}/ask",
        json={"question": QUESTION},
        headers={"X-User-Id": "u-i80"},
    )
    assert resp.status_code == 200
    lines = audit_lines()
    assert len(lines) == 1
    line = lines[0]
    assert line["branch"] == "session"
    assert line["tokens"] != {}
    assert line["tokens"]["primary_input"] == 900
    assert line["tokens"]["total"] == 1520
    assert line["usd_cost_estimate"] > 0.0
    assert line["tool_calls"] == [
        {"name": TOOL, "args": {"metric": "total_points"}, "output_status": "ok"},
    ]
    assert line["retry_attempted"] is True
    assert line["evaluator_verdict"]["retry_feedback"] == "name the top three, not one"
    assert line["orchestration_absent"] is False


def test_session_and_ask_write_the_same_tool_calls_and_tokens_for_the_same_turn(
    server, audit_lines, stub_orchestrator,
):
    """Parity on the audit surface: the two endpoints project the SAME
    ask_v2 dict through the SAME helper (audit.tool_calls_from_ask_v2), so
    their lines agree on tool_calls, tokens, retry and verdict."""
    stub_orchestrator["result"] = _orch_result(
        retry_attempted=True, verdict=_REJECTED, trace=_trace(TOOL, TOOL),
    )
    server.post("/ask", json={"question": QUESTION}, headers={"X-User-Id": "u-i80"})
    session_id = _open_session(server)
    server.post(
        f"/session/{session_id}/ask", json={"question": QUESTION},
        headers={"X-User-Id": "u-i80"},
    )
    ask_line, session_line = audit_lines()
    assert ask_line["branch"] == "orchestrator" and session_line["branch"] == "session"
    for key in ("tool_calls", "tokens", "retry_attempted", "evaluator_verdict", "orchestration_absent"):
        assert ask_line[key] == session_line[key], f"{key!r} diverged between /ask and /session"


def test_session_legacy_path_marks_orchestration_absent(server, audit_lines, monkeypatch):
    """Orchestrator disabled -> the session turn never went through ask_v2()
    (the preserved early-out). tokens={} and tool_calls=[] then mean 'not
    measured', and the line says so explicitly. (M8 kills this.)"""
    monkeypatch.delenv("FPL_ORCH_ENABLED", raising=False)
    session_id = _open_session(server)
    resp = server.post(
        f"/session/{session_id}/ask",
        json={"question": "I want stats for Haaland"},
        headers={"X-User-Id": "u-i80"},
    )
    assert resp.status_code == 200
    assert resp.json()["intent"] == "player_snapshot"
    line = audit_lines()[0]
    assert line["branch"] == "session"
    assert line["orchestration_absent"] is True
    assert line["tokens"] == {}
    assert line["tool_calls"] == []
    assert line["retry_attempted"] is False
    assert line["evaluator_verdict"] is None


def test_session_response_synthesis_turn_comes_from_routing_trace(server, stub_orchestrator):
    """i36 parity: /ask already projected synthesis_turn from routing_trace;
    the session response used to leave it null on every turn."""
    stub_orchestrator["result"] = _orch_result(
        retry_attempted=False, verdict=None, trace=_trace(TOOL),
    )
    session_id = _open_session(server)
    body = server.post(
        f"/session/{session_id}/ask", json={"question": QUESTION},
    ).json()
    assert body["synthesis_turn"] is True


# ---------------------------------------------------------------------------
# Step 4 -- session debug bundle carries the full routing_trace (i36)
# ---------------------------------------------------------------------------

def test_session_debug_bundle_carries_the_full_routing_trace(server, stub_orchestrator):
    stub_orchestrator["result"] = _orch_result(
        retry_attempted=True, verdict=_REJECTED, trace=_trace(TOOL, TOOL),
    )
    session_id = _open_session(server)
    body = server.post(
        f"/session/{session_id}/ask", json={"question": QUESTION, "debug": True},
    ).json()
    dbg = body["debug"]
    assert dbg is not None
    rt = dbg["routing_trace"]
    assert rt["branch"] == "orchestrator"
    assert rt["synthesis_turn"] is True
    assert rt["tool_call_count"] == 2
    assert rt["retry_attempted"] is True
    assert rt["tool_sequence"] == [TOOL, TOOL]
    assert rt["evaluator_verdict"]["approved"] is False
    assert dbg["selected_tool"] == TOOL
    assert dbg["tool_calls"][0]["name"] == TOOL
    assert dbg["tokens"]["total"] == 1520
    assert "orchestration_absent" not in dbg


def test_session_debug_bundle_without_debug_flag_stays_null(server, stub_orchestrator):
    stub_orchestrator["result"] = _orch_result(
        retry_attempted=False, verdict=None, trace=_trace(TOOL),
    )
    session_id = _open_session(server)
    body = server.post(f"/session/{session_id}/ask", json={"question": QUESTION}).json()
    assert body["debug"] is None


def test_session_debug_bundle_on_legacy_path_says_orchestration_absent(server, monkeypatch):
    monkeypatch.delenv("FPL_ORCH_ENABLED", raising=False)
    session_id = _open_session(server)
    body = server.post(
        f"/session/{session_id}/ask",
        json={"question": "I want stats for Haaland", "debug": True},
    ).json()
    dbg = body["debug"]
    assert dbg is not None
    assert dbg["routing_trace"] is None
    assert dbg["orchestration_absent"] is True


# ---------------------------------------------------------------------------
# Step 5 / 6(c) -- /healthz.orchestrator is read at request time (i57)
# ---------------------------------------------------------------------------

def test_healthz_orchestrator_reflects_env_changed_inside_the_test(server, monkeypatch):
    """Two GETs in the same test with the env flipped in between: the block
    must follow the env, which it can only do if it is read per request
    (M10 -- reading once at import -- kills this)."""
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_LOOP_ENABLED", "0")
    monkeypatch.setenv("FPL_ORCH_MAX_ROUNDS", "2")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "gemini")
    monkeypatch.setenv("FPL_ORCH_MODEL", "model-before")
    before = server.get("/healthz").json()["orchestrator"]
    assert before == {
        "enabled": True, "loop_enabled": False, "max_rounds": 2,
        "provider": "gemini", "model": "model-before",
    }

    monkeypatch.setenv("FPL_ORCH_LOOP_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_MAX_ROUNDS", "4")
    monkeypatch.setenv("FPL_ORCH_MODEL", "model-after")
    after = server.get("/healthz").json()["orchestrator"]
    assert after["loop_enabled"] is True
    assert after["max_rounds"] == 4
    assert after["model"] == "model-after"
    assert after["provider"] == "gemini"


def test_healthz_orchestrator_model_falls_back_to_the_provider_default(server, monkeypatch):
    """No FPL_ORCH_MODEL: the block reports the model orch_config would hand
    the orchestrator for that provider -- the same function, same input."""
    from fpl_grounded_assistant.orch_config import get_orch_model

    monkeypatch.delenv("FPL_ORCH_MODEL", raising=False)
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "openai")
    block = server.get("/healthz").json()["orchestrator"]
    assert block["provider"] == "openai"
    assert block["model"] == get_orch_model("openai")


def test_healthz_orchestrator_reports_unset_provider_as_null(server, monkeypatch):
    monkeypatch.delenv("FPL_ORCH_PROVIDER", raising=False)
    monkeypatch.delenv("FPL_ORCH_ENABLED", raising=False)
    block = server.get("/healthz").json()["orchestrator"]
    assert block["provider"] is None
    assert block["enabled"] is False
    assert set(block) == {"enabled", "loop_enabled", "max_rounds", "provider", "model"}


# ---------------------------------------------------------------------------
# audit.tool_calls_from_ask_v2 -- the one shared projection
# ---------------------------------------------------------------------------

def test_tool_calls_projection_is_empty_without_a_selected_tool():
    assert audit_mod.tool_calls_from_ask_v2({"selected_tool": None}) == []
    assert audit_mod.tool_calls_from_ask_v2({}) == []


def test_tool_calls_projection_reads_args_and_status_from_the_dict():
    assert audit_mod.tool_calls_from_ask_v2({
        "selected_tool": "get_player_snapshot",
        "tool_input": {"player_name": "Haaland"},
        "raw_output": {"status": "ambiguous"},
    }) == [{
        "name": "get_player_snapshot",
        "args": {"player_name": "Haaland"},
        "output_status": "ambiguous",
    }]
