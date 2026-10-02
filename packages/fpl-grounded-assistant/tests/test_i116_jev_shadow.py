"""i116 -- the Jev shadow: runs next to the served turn, never instead of it.

No test here reaches TypeSafe or an LLM provider. Autouse guards fail the
test (``pytest.fail``, a BaseException the shadow's own ``except Exception``
cannot swallow) on any real TypeSafe HTTP call and on any real
``call_orch_provider`` call; tests that need either install a fake. The
orchestrator is stubbed the way ``test_i102_fixture_outlook_http`` does it,
and the shadow's thread spawn is replaced by an inline call so every
assertion sees the finished shadow row.

What this file pins (the card's gates plus the brain's extra one)
-----------------------------------------------------------------
A. Flag off (unset, "off", "canary", typos) -> zero Jev calls, no turn_id,
   no shadow row. Flag read at call time.
B. The shadow never changes the served result: the ask_v2 dict with the
   shadow on equals the one with it off, except the turn_id trace key --
   including when layer 2 runs and when the shadow fails.
C. A Jev timeout / error / an exception inside the shadow is logged in the
   shadow row and the served turn is unaffected; ``start`` never raises.
D. Privacy on the REAL harness path: with a linked team (and a session, on
   the HTTP route), the Jev request is ``{model, state, questions}`` with
   ``state`` == the text the orchestrator received, and no team id, user,
   squad or session data anywhere in it.
E. ``scripts/grade_i108_chip_two_parts.py`` runs UNCHANGED on a shadow file.
F. The audit line carries ``turn_id`` only on a shadowed turn (byte-identical
   otherwise), on /ask and on session turns, equal to the shadow row's.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import requests
from fastapi.testclient import TestClient

_PKG = Path(__file__).resolve().parents[1]
for _p in [_PKG, *(_PKG.parent / n for n in ("fpl-api-client", "fpl-data-core", "fpl-player-registry",
                                              "fpl-query-tools", "fpl-tool-contract", "fpl-tool-runner",
                                              "fpl-captain-engine"))]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import fpl_server  # noqa: E402
from fpl_grounded_assistant import audit as audit_mod  # noqa: E402
from fpl_grounded_assistant import provider_client  # noqa: E402
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant.harness import ask_v2  # noqa: E402
from fpl_grounded_assistant.jev_router import router as jr  # noqa: E402
from fpl_grounded_assistant.jev_router import shadow  # noqa: E402
from fpl_grounded_assistant.orchestrator import OUTCOME_OK, OrchestratorResult  # noqa: E402
from fpl_grounded_assistant.quota import reset_quota  # noqa: E402

#: Captured at import, before the autouse fixture swaps it for an inline call:
#: production must spawn a daemon thread, never run the shadow inline (that
#: would put Jev + the chip tool + a provider call inside the user's turn).
_PRODUCTION_SPAWN = shadow._SPAWN

CHIP_Q = "¿Tiro el bench boost en la fecha 2?"
TEAM_ID = 68643


# ------------------------------------------------------------------ fixtures

@pytest.fixture(autouse=True)
def _guards(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    real = requests.Session.request

    def guarded(self: Any, method: str, url: str, *a: Any, **kw: Any) -> Any:
        if "typesafe.ai" in str(url):
            pytest.fail(f"real TypeSafe call from a test: {method} {url}")
        return real(self, method, url, *a, **kw)

    monkeypatch.setattr(requests.Session, "request", guarded)

    def no_provider(*a: Any, **kw: Any) -> Any:
        pytest.fail("real call_orch_provider from a test")

    monkeypatch.setattr(provider_client, "call_orch_provider", no_provider)
    monkeypatch.setattr(shadow, "_SPAWN", lambda fn: fn())
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit"))
    monkeypatch.setenv(jr.API_KEY_ENV, "test-key-not-real")
    monkeypatch.delenv(shadow.MODE_ENV, raising=False)


class _Resp:
    def __init__(self, status: int, body: Any) -> None:
        self.status_code, self._body = status, body

    def json(self) -> Any:
        return self._body


class _JevFake:
    """Stands in for requests.post toward TypeSafe; records every body."""

    def __init__(self, route: str = jr.CHIP_PLAN, chip: str = "bench_boost",
                 raises: BaseException | None = None) -> None:
        self.route, self.chip, self.raises = route, chip, raises
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kw: Any) -> Any:
        self.calls.append({"url": url, **kw})
        if self.raises is not None:
            raise self.raises
        return _Resp(200, {"answers": {"route": {"choice": self.route, "confidence": 0.95},
                                       "chip": {"choice": self.chip, "confidence": 1.0}},
                           "usage": {"input_tokens": 5138}})


@pytest.fixture
def jev(monkeypatch: pytest.MonkeyPatch) -> _JevFake:
    fake = _JevFake()
    monkeypatch.setattr(requests, "post", fake)
    return fake


class _BodyCall:
    def __init__(self, text: str) -> None:
        self.response = type("R", (), {"output_text": text, "output": []})()
        self.input_tokens, self.output_tokens, self.cache_read_tokens = 900, 120, 0


@pytest.fixture
def body_llm(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake(provider: str, **kw: Any) -> _BodyCall:
        calls.append({"provider": provider, **kw})
        return _BodyCall("Los cruces de la fecha favorecen a los mejores jugadores de campo.")

    monkeypatch.setattr(provider_client, "call_orch_provider", fake)
    return calls


def _orch_result(question: str) -> OrchestratorResult:
    payload = {"status": "ok", "chip": "bench_boost", "recommendation": "conditions_favorable",
               "signals": {}, "advice_text": "favorable"}
    return OrchestratorResult(
        question=question, tool_chosen="get_chip_advice", tool_args={"chip": "bench_boost"},
        tool_output=payload, answer_text="Respuesta servida por el orquestador.",
        llm_used=True, model="stub-model", outcome=OUTCOME_OK,
        primary_input_tokens=900, primary_output_tokens=120, total_tokens=1020,
        tool_call_count=1,
        tool_calls_trace=({"round": 1, "tool_call_id": "c0", "name": "get_chip_advice",
                           "args": {"chip": "bench_boost"}, "output": payload, "success": True},),
        synthesis_turn=True,
    )


@pytest.fixture
def orch(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def fake(question: str, *a: Any, **kw: Any) -> OrchestratorResult:
        seen.append(question)
        return _orch_result(question)

    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-used")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", fake)
    return seen


def _shadow_rows() -> list[dict[str, Any]]:
    path = Path(shadow.shadow_log_path())
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _without_turn_id(d: dict[str, Any]) -> dict[str, Any]:
    out = dict(d)
    rt = dict(out.get("routing_trace") or {})
    rt.pop(shadow.TURN_ID_TRACE_KEY, None)
    out["routing_trace"] = rt
    return out


# ------------------------------------------------------------------ A. flag off

@pytest.mark.parametrize("value", [None, "", "off", "OFF", "canary", "shadoww", "1", "true"])
def test_flag_not_shadow_means_zero_jev_calls(monkeypatch: pytest.MonkeyPatch, orch: list[str],
                                             jev: _JevFake, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv(shadow.MODE_ENV, raising=False)
    else:
        monkeypatch.setenv(shadow.MODE_ENV, value)
    out = ask_v2(CHIP_Q, STANDARD_BOOTSTRAP, team_id=TEAM_ID)
    assert orch, "precondition: the orchestrator branch ran"
    assert jev.calls == []
    assert shadow.TURN_ID_TRACE_KEY not in out["routing_trace"]
    assert _shadow_rows() == []


def test_flag_is_read_at_call_time(monkeypatch: pytest.MonkeyPatch, orch: list[str], jev: _JevFake,
                                   body_llm: list) -> None:
    ask_v2(CHIP_Q, STANDARD_BOOTSTRAP)
    monkeypatch.setenv(shadow.MODE_ENV, "shadow")
    ask_v2(CHIP_Q, STANDARD_BOOTSTRAP)
    monkeypatch.setenv(shadow.MODE_ENV, "off")
    ask_v2(CHIP_Q, STANDARD_BOOTSTRAP)
    assert len(jev.calls) == 1


def test_shadow_runs_layer1_once_and_logs_the_turn(monkeypatch: pytest.MonkeyPatch, orch: list[str],
                                                   jev: _JevFake, body_llm: list) -> None:
    monkeypatch.setenv(shadow.MODE_ENV, "shadow")
    out = ask_v2(CHIP_Q, STANDARD_BOOTSTRAP)
    rows = _shadow_rows()
    assert len(jev.calls) == 1 and len(rows) == 1
    assert rows[0]["turn_id"] == out["routing_trace"][shadow.TURN_ID_TRACE_KEY]
    assert rows[0]["layer1"]["path"] == "chip" and rows[0]["layer1"]["reason"] == "plan"
    assert rows[0]["served_tool_sequence"] == ["get_chip_advice"]
    assert "question" not in rows[0] and "user_id" not in rows[0]


@pytest.mark.parametrize("chip", ["none", "bench_boost"])
def test_non_chip_route_runs_layer1_only(monkeypatch: pytest.MonkeyPatch, orch: list[str],
                                        body_llm: list, chip: str) -> None:
    # chip="bench_boost" is the dangerous one: Jev names a chip, the route is
    # not the chip path -- layer 2 must still not run.
    fake = _JevFake(route="get_player_snapshot", chip=chip)
    monkeypatch.setattr(requests, "post", fake)
    monkeypatch.setenv(shadow.MODE_ENV, "shadow")
    ask_v2("¿Cómo viene Saka?", STANDARD_BOOTSTRAP)
    row = _shadow_rows()[0]
    assert row["layer1"]["path"] == "escalate" and row["layer2"] is None
    assert body_llm == [], "layer 2 must not run off the chip path"


# ------------------------------------------------------------------ B. served result unchanged

def test_served_result_identical_with_shadow_on(monkeypatch: pytest.MonkeyPatch, orch: list[str],
                                                jev: _JevFake, body_llm: list) -> None:
    off = ask_v2(CHIP_Q, STANDARD_BOOTSTRAP, team_id=TEAM_ID)
    monkeypatch.setenv(shadow.MODE_ENV, "shadow")
    on = ask_v2(CHIP_Q, STANDARD_BOOTSTRAP, team_id=TEAM_ID)
    assert body_llm, "precondition: layer 2 ran and produced its own answer"
    assert _shadow_rows()[0]["answer_text_full"] != on["answer_text"]
    assert _without_turn_id(on) == _without_turn_id(off)
    assert on["answer_text"] == "Respuesta servida por el orquestador."


def test_served_result_identical_when_the_shadow_fails(monkeypatch: pytest.MonkeyPatch, orch: list[str]) -> None:
    off = ask_v2(CHIP_Q, STANDARD_BOOTSTRAP)
    monkeypatch.setattr(requests, "post", _JevFake(raises=requests.Timeout("slow")))
    monkeypatch.setenv(shadow.MODE_ENV, "shadow")
    on = ask_v2(CHIP_Q, STANDARD_BOOTSTRAP)
    assert _without_turn_id(on) == _without_turn_id(off)


# ------------------------------------------------------------------ C. failures are logged, never raised

@pytest.mark.parametrize("exc,reason", [(requests.Timeout("slow"), "timeout"),
                                        (requests.ConnectionError("down"), "transport_error")])
def test_jev_failure_is_a_logged_escalation(monkeypatch: pytest.MonkeyPatch, orch: list[str],
                                           exc: Exception, reason: str) -> None:
    monkeypatch.setattr(requests, "post", _JevFake(raises=exc))
    monkeypatch.setenv(shadow.MODE_ENV, "shadow")
    out = ask_v2(CHIP_Q, STANDARD_BOOTSTRAP)
    row = _shadow_rows()[0]
    assert (row["layer1"]["path"], row["layer1"]["reason"]) == ("escalate", reason)
    assert row["error"] is None and out["answer_text"] == "Respuesta servida por el orquestador."


def test_exception_inside_the_shadow_is_recorded_not_raised(monkeypatch: pytest.MonkeyPatch, orch: list[str],
                                                           jev: _JevFake) -> None:
    def boom(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("chip tool exploded")

    monkeypatch.setattr("fpl_grounded_assistant.tool_dispatch.run_tool", boom)
    monkeypatch.setenv(shadow.MODE_ENV, "shadow")
    out = ask_v2(CHIP_Q, STANDARD_BOOTSTRAP)
    row = _shadow_rows()[0]
    assert row["error"] and "chip tool exploded" in row["error"]
    assert out["answer_text"] == "Respuesta servida por el orquestador."


def test_a_shadow_that_cannot_start_does_not_raise(monkeypatch: pytest.MonkeyPatch, orch: list[str],
                                                   jev: _JevFake) -> None:
    def cannot_spawn(fn: Any) -> None:
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(shadow, "_SPAWN", cannot_spawn)
    monkeypatch.setenv(shadow.MODE_ENV, "shadow")
    out = ask_v2(CHIP_Q, STANDARD_BOOTSTRAP)
    assert out["answer_text"] == "Respuesta servida por el orquestador."
    assert jev.calls == []


def test_production_spawn_is_the_daemon_spawner() -> None:
    assert _PRODUCTION_SPAWN is shadow._spawn_daemon


def test_production_spawn_is_a_daemon_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[Any] = []

    class _T:
        def __init__(self, target: Any, name: str, daemon: bool) -> None:
            started.append({"name": name, "daemon": daemon})

        def start(self) -> None:
            started[-1]["started"] = True

    monkeypatch.setattr(shadow.threading, "Thread", _T)
    shadow._spawn_daemon(lambda: None)
    assert started == [{"name": "jev-shadow", "daemon": True, "started": True}]


# ------------------------------------------------------------------ D. privacy on the real path

_FORBIDDEN = {"team_id", "_my_team_id", "user_id", "user", "squad", "picks", "history",
              "session", "session_id", "messages", "bootstrap", "squad_context"}


def _keys(obj: Any) -> set[str]:
    if isinstance(obj, dict):
        return set(obj).union(*(_keys(v) for v in obj.values())) if obj else set()
    if isinstance(obj, list):
        return set().union(*(_keys(v) for v in obj)) if obj else set()
    return set()


def _assert_question_only(call: dict[str, Any], expected_state: str) -> None:
    body = call["json"]
    assert set(body) == {"model", "state", "questions"}
    assert body["state"] == expected_state
    assert not _keys(body["questions"]) & _FORBIDDEN
    dumped = json.dumps(body, ensure_ascii=False)
    assert str(TEAM_ID) not in dumped, "the linked team id leaked into the Jev request"


def test_harness_path_with_a_linked_team_sends_only_the_question(monkeypatch: pytest.MonkeyPatch, orch: list[str],
                                                                 jev: _JevFake, body_llm: list) -> None:
    monkeypatch.setenv(shadow.MODE_ENV, "shadow")
    ask_v2(CHIP_Q, STANDARD_BOOTSTRAP, team_id=TEAM_ID)
    assert len(jev.calls) == 1
    _assert_question_only(jev.calls[0], expected_state=orch[-1])
    assert _shadow_rows()[0]["team_id_present"] is True


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Any:
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._sessions.clear()
    reset_quota()
    written: list[Any] = []
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: written.append(entry))
    client = TestClient(fpl_server.app)
    client.audit = written  # type: ignore[attr-defined]
    yield client
    fpl_server._sessions.clear()
    reset_quota()


def test_http_ask_with_team_and_squad_context_sends_only_the_question(monkeypatch: pytest.MonkeyPatch, server: Any,
                                                                      orch: list[str], jev: _JevFake,
                                                                      body_llm: list) -> None:
    monkeypatch.setenv(shadow.MODE_ENV, "shadow")
    r = server.post("/ask", json={"question": CHIP_Q, "team_id": TEAM_ID,
                                  "squad_context": {"bench": ["X"]}},
                    headers={"X-User-Id": "u-i116"})
    assert r.status_code == 200
    assert len(jev.calls) == 1
    _assert_question_only(jev.calls[0], expected_state=orch[-1])
    assert "u-i116" not in json.dumps(jev.calls[0]["json"])


def test_http_session_turns_send_only_the_question(monkeypatch: pytest.MonkeyPatch, server: Any, orch: list[str],
                                                   jev: _JevFake, body_llm: list) -> None:
    monkeypatch.setenv(shadow.MODE_ENV, "shadow")
    sid = server.post("/session").json()["session_id"]
    r = server.post(f"/session/{sid}/ask", json={"question": CHIP_Q, "team_id": TEAM_ID},
                    headers={"X-User-Id": "u-i116-s"})
    assert r.status_code == 200
    assert jev.calls, "precondition: the session turn went through ask_v2's orchestrator branch"
    for call, sent_to_orch in zip(jev.calls, orch):
        _assert_question_only(call, expected_state=sent_to_orch)
        assert sid not in json.dumps(call["json"])


# ------------------------------------------------------------------ F. audit join

def test_audit_line_has_turn_id_only_when_shadowed(tmp_path: Path) -> None:
    common = dict(question="q", branch="orchestrator", outcome="ok", final_text="t")
    plain = audit_mod.make_audit_entry(**common)
    joined = audit_mod.make_audit_entry(**common, turn_id="abc123")
    audit_mod.write_audit_entry(plain, log_dir=str(tmp_path))
    audit_mod.write_audit_entry(joined, log_dir=str(tmp_path))
    lines = [json.loads(l) for l in next(tmp_path.glob("*.ndjson")).read_text(encoding="utf-8").splitlines()]
    assert "turn_id" not in lines[0]
    assert lines[1]["turn_id"] == "abc123"


def test_http_ask_audit_carries_the_shadow_turn_id(monkeypatch: pytest.MonkeyPatch, server: Any, orch: list[str],
                                                   jev: _JevFake, body_llm: list) -> None:
    server.post("/ask", json={"question": CHIP_Q}, headers={"X-User-Id": "u-off"})
    monkeypatch.setenv(shadow.MODE_ENV, "shadow")
    server.post("/ask", json={"question": CHIP_Q}, headers={"X-User-Id": "u-on"})
    assert server.audit[0].turn_id is None
    assert server.audit[1].turn_id == _shadow_rows()[0]["turn_id"]


def test_session_audit_carries_the_shadow_turn_id(monkeypatch: pytest.MonkeyPatch, server: Any, orch: list[str],
                                                  jev: _JevFake, body_llm: list) -> None:
    monkeypatch.setenv(shadow.MODE_ENV, "shadow")
    sid = server.post("/session").json()["session_id"]
    server.post(f"/session/{sid}/ask", json={"question": CHIP_Q}, headers={"X-User-Id": "u-s"})
    sess = [e for e in server.audit if e.branch == "session"]
    assert sess and sess[-1].turn_id == _shadow_rows()[-1]["turn_id"]


# ------------------------------------------------------------------ E. the E3 grader, unchanged

def test_e3_grader_runs_unchanged_on_a_shadow_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, orch: list[str],
                                                   jev: _JevFake, body_llm: list) -> None:
    monkeypatch.setenv(shadow.MODE_ENV, "shadow")
    ask_v2(CHIP_Q, STANDARD_BOOTSTRAP)
    ask_v2("¿Activo el wildcard esta fecha?", STANDARD_BOOTSTRAP)
    rows = _shadow_rows()
    assert len(rows) == 2 and all(r["chip_trace"] and r["answer_text_full"] for r in rows)
    boot = tmp_path / "bootstrap.json"
    boot.write_text(json.dumps(STANDARD_BOOTSTRAP), encoding="utf-8")
    grader = _PKG / "scripts" / "grade_i108_chip_two_parts.py"
    out = subprocess.run([sys.executable, str(grader), shadow.shadow_log_path(), "--bootstrap", str(boot)],
                         capture_output=True, text=True, encoding="utf-8", cwd=_PKG,
                         env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=120)
    assert "Traceback" not in out.stderr, out.stderr[-2000:]
    summary = json.loads(out.stdout[out.stdout.index("{"): out.stdout.index("}\n") + 1])
    assert summary["rows"] == 2
    assert summary["denominator"] == summary["pass"] > 0, summary


def test_chip_trace_projection_matches_the_measurement_script() -> None:
    """The shadow row's chip_trace must be the projection the E3 runs wrote
    (measure_tool_routing.extract_chip_trace), field for field -- the grader
    alone cannot see a dropped favoured group, because the header already
    names it."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_mtr", _PKG / "scripts" / "measure_tool_routing.py")
    mtr = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mtr)
    output = {
        "status": "ok", "chip": "bench_boost", "recommendation": "conditions_favorable",
        "squad_source": "linked", "linked_squad_error": None,
        "squad_fit": {"verdict": "needs_transfers", "missing_count": 2, "held": [{"element": 9}]},
        "signals": {"favoured_teams": [{"team": 7, "team_short": "CHE", "extra": 1}],
                    "favoured_players": [{"element": 9, "web_name": "Palmer", "extra": 2}]},
    }
    result = type("R", (), {"tool_calls_trace": [{"name": "get_chip_advice", "output": output}]})()
    assert shadow.project_chip_output(output) == mtr.extract_chip_trace(result)
