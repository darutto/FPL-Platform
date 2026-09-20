"""i104 + i105: the audit log lands where the environment says, and every
line names the provider and model that ACTUALLY ran, priced at that model's
rate.

Prod audit of 2026-09-19: all six snapshot lines said ``provider=gemini``
while ``/healthz.orchestrator`` said ``openai / gpt-5.6-luna``, because
``fpl_server`` stamped ``os.environ["DEFAULT_PROVIDER"]`` (the presentation
layer's classifier variable) on the audit line, and ``audit.py`` priced the
tokens at a per-provider table whose gemini row was $0.075/M input. Every
prod cost estimate was therefore a number that looked true and was wrong.
And the log itself lived in the container's ephemeral filesystem with no way
to point it at a volume.

What is pinned here, and what kills each pin (each guard mutated separately):

  M1  fpl_server /ask reads DEFAULT_PROVIDER again         -> test_ask_audit_ignores_default_provider_env dies
  M2  harness stops projecting orchestrator_provider/model -> test_ask_audit_line_names_the_model_that_ran dies
  M3  audit prices an unknown model at a default tariff    -> test_unpriced_model_is_none_not_a_default_tariff dies
  M4  resolve_log_dir ignores AUDIT_LOG_DIR                -> test_audit_log_dir_env_absolute dies
  M5  ask_orchestrated stops stamping provider             -> test_ask_orchestrated_stamps_the_dispatched_provider dies
  M6  a second price table reappears in a script           -> test_there_is_one_price_table dies

The orchestrated-turn tests run the REAL ``ask_orchestrated`` (client
resolution, provider label, tool execution, harness projection, server
audit) with only ``call_orch_provider`` faked at the wire, so ``provider``
and ``model`` on the line come from the orchestrator's own dispatch, not
from a stub that was handed the expected answer. No network: the fake is
the only "provider" and it records what it was dispatched with.
"""
from __future__ import annotations

import json
import os as _os
import re
import sys as _sys
from pathlib import Path
from types import SimpleNamespace as NS

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
from fpl_grounded_assistant import model_pricing  # noqa: E402
from fpl_grounded_assistant import orchestrator as orch_mod  # noqa: E402
from fpl_grounded_assistant.orchestrator import (  # noqa: E402
    OUTCOME_NO_CLIENT,
    OUTCOME_OK,
    OUTCOME_TOOL_ERROR,
    OrchestratorResult,
    ask_orchestrated,
)
from fpl_grounded_assistant.provider_client import OrchCallResult  # noqa: E402
from fpl_grounded_assistant.quota import reset_quota  # noqa: E402

LUNA = "gpt-5.6-luna"
TOOL = "rank_players_by_metric"
QUESTION = "jugadores con mas puntos"

# Luna's published rates, written out rather than read from the table, so a
# table that silently became the old gemini one ($0.075/M input) fails here.
_LUNA_INPUT_PER_TOKEN = 0.20 / 1_000_000
_LUNA_OUTPUT_PER_TOKEN = 1.20 / 1_000_000
_LUNA_CACHE_PER_TOKEN = 0.02 / 1_000_000


# ---------------------------------------------------------------------------
# Fixtures
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
    """Send the server's audit writes to a temp dir via the REAL env knob
    (i104), and hand back a reader of the NDJSON lines that landed there."""
    log_dir = tmp_path / "audit_logs"
    monkeypatch.setenv(audit_mod.AUDIT_LOG_DIR_ENV, str(log_dir))

    def _read() -> list[dict]:
        lines: list[dict] = []
        if not log_dir.is_dir():
            return lines
        for name in sorted(_os.listdir(log_dir)):
            with open(log_dir / name, encoding="utf-8") as fh:
                lines.extend(json.loads(ln) for ln in fh if ln.strip())
        return lines

    return _read


def _openai_tool_call_response() -> NS:
    return NS(
        output=[
            NS(type="function_call", call_id="oai-1", name=TOOL,
               arguments=json.dumps({"metric": "total_points"})),
        ],
        output_text="",
        usage=NS(input_tokens=900, output_tokens=120,
                 input_tokens_details=NS(cached_tokens=0)),
    )


def _openai_text_response(text: str = "Haaland lidera la tabla de puntos.") -> NS:
    return NS(
        output=[NS(type="message", content=[NS(type="output_text", text=text)])],
        output_text=text,
        usage=NS(input_tokens=400, output_tokens=60,
                 input_tokens_details=NS(cached_tokens=0)),
    )


@pytest.fixture
def fake_openai_wire(monkeypatch: pytest.MonkeyPatch):
    """The production orchestrator config for luna, with the ONLY network
    boundary (``orchestrator.call_orch_provider``) replaced by a recorder
    that answers OpenAI-shaped: first a tool call, then text. Records the
    ``provider_name`` / ``model`` it was dispatched with.

    ``DEFAULT_PROVIDER=gemini`` is set on purpose: it is the trap the audit
    used to fall into.
    """
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "openai")
    monkeypatch.setenv("FPL_ORCH_MODEL", LUNA)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.setenv("DEFAULT_PROVIDER", "gemini")
    monkeypatch.delenv("FPL_ORCH_TEST_INJECTION", raising=False)
    calls: list[dict] = []

    def _fake_call(provider_name, *, model, **_kw):
        calls.append({"provider_name": provider_name, "model": model})
        response = (
            _openai_tool_call_response() if len(calls) == 1 else _openai_text_response()
        )
        return OrchCallResult(
            response=response, error_code=None, error_msg=None,
            attempts=1, latency_ms=1.0,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=0,
        )

    monkeypatch.setattr(orch_mod, "call_orch_provider", _fake_call)
    return calls


def _luna_cost_from(tokens: dict) -> float:
    """Luna cost recomputed from the LINE's own token counts (openai
    convention: cached share is a subset of input, priced once)."""
    total_input = (tokens.get("primary_input", 0) + tokens.get("evaluator", 0)
                   + tokens.get("retry_input", 0))
    total_output = tokens.get("primary_output", 0) + tokens.get("retry_output", 0)
    cache = tokens.get("primary_cache_read", 0)
    return (
        max(0, total_input - cache) * _LUNA_INPUT_PER_TOKEN
        + total_output * _LUNA_OUTPUT_PER_TOKEN
        + cache * _LUNA_CACHE_PER_TOKEN
    )


# ---------------------------------------------------------------------------
# i104 -- AUDIT_LOG_DIR
# ---------------------------------------------------------------------------

def _entry(**kw) -> audit_mod.AuditEntry:
    defaults = dict(question="q", branch="unsupported", outcome="unsupported")
    defaults.update(kw)
    return audit_mod.make_audit_entry(**defaults)


def test_audit_log_dir_env_absolute(monkeypatch, tmp_path):
    """AUDIT_LOG_DIR=<absolute>: the line lands there, dir auto-created. (M4)"""
    target = tmp_path / "vol" / "audit"
    monkeypatch.setenv(audit_mod.AUDIT_LOG_DIR_ENV, str(target))
    assert not target.exists()
    audit_mod.write_audit_entry(_entry(question="landed?"))
    files = sorted(target.glob("*.ndjson"))
    assert len(files) == 1
    line = json.loads(files[0].read_text(encoding="utf-8").strip())
    assert line["question"] == "landed?"


def test_audit_log_dir_env_relative_is_under_the_package(monkeypatch, tmp_path):
    """A relative value resolves against the package dir, not the cwd."""
    monkeypatch.setattr(audit_mod, "_PACKAGE_DIR", str(tmp_path))
    monkeypatch.setenv(audit_mod.AUDIT_LOG_DIR_ENV, "rel_logs")
    monkeypatch.chdir(tmp_path / "..")  # cwd is NOT the package dir
    assert audit_mod.resolve_log_dir() == _os.path.join(str(tmp_path), "rel_logs")
    audit_mod.write_audit_entry(_entry())
    assert list((tmp_path / "rel_logs").glob("*.ndjson"))


def test_audit_log_dir_unset_keeps_the_old_default(monkeypatch, tmp_path):
    """No env var (and a blank one): the default of today, unchanged."""
    monkeypatch.delenv(audit_mod.AUDIT_LOG_DIR_ENV, raising=False)
    expected = _os.path.join(audit_mod._PACKAGE_DIR, "audit_logs")
    assert audit_mod.resolve_log_dir() == expected
    assert audit_mod._DEFAULT_LOG_DIR == expected
    monkeypatch.setenv(audit_mod.AUDIT_LOG_DIR_ENV, "   ")
    assert audit_mod.resolve_log_dir() == expected
    # And write_audit_entry consults that default (proved by moving it).
    monkeypatch.setattr(audit_mod, "_DEFAULT_LOG_DIR", str(tmp_path / "dflt"))
    audit_mod.write_audit_entry(_entry())
    assert list((tmp_path / "dflt").glob("*.ndjson"))


def test_explicit_log_dir_argument_still_wins(monkeypatch, tmp_path):
    monkeypatch.setenv(audit_mod.AUDIT_LOG_DIR_ENV, str(tmp_path / "env"))
    audit_mod.write_audit_entry(_entry(), log_dir=str(tmp_path / "arg"))
    assert list((tmp_path / "arg").glob("*.ndjson"))
    assert not (tmp_path / "env").exists()


# ---------------------------------------------------------------------------
# i105 (a) -- an orchestrated luna turn audits provider=openai, model=luna,
#             cost at luna's rate
# ---------------------------------------------------------------------------

def test_ask_audit_line_names_the_model_that_ran(server, audit_lines, fake_openai_wire):
    """(a) /ask through the real orchestrator: the line says what the wire
    was dispatched with, and the cost is luna's tariff on the line's own
    tokens. (M2 kills provider/model; the old table kills the cost.)"""
    resp = server.post("/ask", json={"question": QUESTION}, headers={"X-User-Id": "u-i105"})
    assert resp.status_code == 200
    # What the fake wire was actually dispatched with -- the independent source.
    assert fake_openai_wire, "the orchestrator never reached the wire"
    assert {c["provider_name"] for c in fake_openai_wire} == {"openai"}
    assert {c["model"] for c in fake_openai_wire} == {LUNA}

    lines = audit_lines()
    assert len(lines) == 1
    line = lines[0]
    assert line["branch"] == "orchestrator", line
    assert line["provider"] == "openai"
    assert line["model"] == LUNA
    assert line["tokens"]["total"] > 0
    assert line["usd_cost_estimate"] == pytest.approx(_luna_cost_from(line["tokens"]), rel=1e-6)
    assert line["usd_cost_estimate"] > 0.0


def test_ask_audit_ignores_default_provider_env(server, audit_lines, fake_openai_wire, monkeypatch):
    """(b) DEFAULT_PROVIDER says gemini (set by the fixture), the orchestrator
    ran luna on openai: the WRITTEN line says openai/luna. Dies if fpl_server
    goes back to os.environ["DEFAULT_PROVIDER"]. (M1)"""
    assert _os.environ["DEFAULT_PROVIDER"] == "gemini"
    server.post("/ask", json={"question": QUESTION}, headers={"X-User-Id": "u-i105"})
    line = audit_lines()[0]
    assert line["provider"] == "openai"
    assert line["provider"] != _os.environ["DEFAULT_PROVIDER"]
    assert line["model"] == LUNA


def _open_session(client: TestClient) -> str:
    resp = client.post("/session")
    assert resp.status_code == 200
    return resp.json()["session_id"]


def test_session_audit_line_carries_the_same_provider_and_model(
    server, audit_lines, fake_openai_wire,
):
    """Parity: the session path reads provider/model off the same ask_v2 dict
    (via FinalResponse.orchestration), never off DEFAULT_PROVIDER."""
    sid = _open_session(server)
    resp = server.post(f"/session/{sid}/ask", json={"question": QUESTION},
                       headers={"X-User-Id": "u-i105-s"})
    assert resp.status_code == 200
    line = audit_lines()[0]
    assert line["branch"] == "session"
    assert line["provider"] == "openai"
    assert line["model"] == LUNA
    assert line["orchestration_absent"] is False
    assert line["usd_cost_estimate"] == pytest.approx(_luna_cost_from(line["tokens"]), rel=1e-6)


# ---------------------------------------------------------------------------
# i105 -- turns where no LLM ran say so: None / None / 0.0, never a default
# ---------------------------------------------------------------------------

def test_turn_without_an_llm_audits_none_provider_none_model_zero_cost(
    server, audit_lines, monkeypatch,
):
    monkeypatch.delenv("FPL_ORCH_ENABLED", raising=False)
    monkeypatch.setenv("DEFAULT_PROVIDER", "gemini")   # the trap, again
    server.post("/ask", json={"question": QUESTION}, headers={"X-User-Id": "u-i105-d"})
    line = audit_lines()[0]
    assert line["branch"] == "unsupported"
    assert line["provider"] is None
    assert line["model"] is None
    assert line["usd_cost_estimate"] == 0.0
    assert line["tokens"] in ({}, {"total": 0}) or line["tokens"].get("total", 0) == 0


def test_session_legacy_path_audits_none_provider_none_model(server, audit_lines, monkeypatch):
    monkeypatch.delenv("FPL_ORCH_ENABLED", raising=False)
    monkeypatch.setenv("DEFAULT_PROVIDER", "gemini")
    sid = _open_session(server)
    server.post(f"/session/{sid}/ask", json={"question": QUESTION},
                headers={"X-User-Id": "u-i105-l"})
    line = audit_lines()[0]
    assert line["orchestration_absent"] is True
    assert line["provider"] is None
    assert line["model"] is None
    assert line["usd_cost_estimate"] == 0.0


# ---------------------------------------------------------------------------
# i105 -- the no-grounded-tool branch still names the model that billed
# ---------------------------------------------------------------------------

@pytest.fixture
def stub_orchestrator(monkeypatch: pytest.MonkeyPatch):
    holder: dict = {"result": None}
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-used")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.setattr(
        "fpl_grounded_assistant.orchestrator.ask_orchestrated",
        lambda *a, **k: holder["result"],
    )
    return holder


def _stub_result(*, outcome: str, model: str, provider: str | None, llm_used: bool = True):
    return OrchestratorResult(
        question=QUESTION, tool_chosen=TOOL if outcome != OUTCOME_NO_CLIENT else None,
        tool_args={"metric": "total_points"},
        tool_output={"status": "ok"} if outcome == OUTCOME_OK else {},
        answer_text="texto", llm_used=llm_used, model=model, outcome=outcome,
        primary_input_tokens=1000 if llm_used else 0,
        primary_output_tokens=100 if llm_used else 0,
        total_tokens=1100 if llm_used else 0,
        tool_call_count=1 if llm_used else 0,
        tool_calls_trace=(
            ({"round": 1, "name": TOOL, "args": {"metric": "total_points"},
              "output": {"status": "error"}, "success": False},)
            if llm_used else ()
        ),
        provider=provider,
    )


def test_no_grounded_tool_branch_still_audits_provider_and_model(
    server, audit_lines, stub_orchestrator,
):
    """An LLM that named a tool whose execution failed still ran and billed:
    the line names it and prices it (this branch carried no model before)."""
    stub_orchestrator["result"] = _stub_result(outcome=OUTCOME_TOOL_ERROR, model=LUNA, provider="openai")
    server.post("/ask", json={"question": QUESTION}, headers={"X-User-Id": "u-i105-ng"})
    line = audit_lines()[0]
    assert line["branch"] == "unsupported"
    assert line["provider"] == "openai"
    assert line["model"] == LUNA
    assert line["usd_cost_estimate"] == pytest.approx(1000 * _LUNA_INPUT_PER_TOKEN + 100 * _LUNA_OUTPUT_PER_TOKEN)


def test_unpriced_model_is_none_not_a_default_tariff(server, audit_lines, stub_orchestrator, caplog):
    """A model the table does not know: usd_cost_estimate=None plus a
    warning. Never priced at someone else's rate. (M3)"""
    stub_orchestrator["result"] = _stub_result(outcome=OUTCOME_OK, model="gpt-9-nobody-priced", provider="openai")
    with caplog.at_level("WARNING", logger="fpl_grounded_assistant.audit"):
        server.post("/ask", json={"question": QUESTION}, headers={"X-User-Id": "u-i105-up"})
    line = audit_lines()[0]
    assert line["model"] == "gpt-9-nobody-priced"
    assert line["provider"] == "openai"
    assert line["tokens"]["total"] == 1100
    assert line["usd_cost_estimate"] is None
    assert any("gpt-9-nobody-priced" in r.getMessage() and "no price" in r.getMessage()
               for r in caplog.records)


def test_llm_used_false_result_audits_none_even_with_a_model_sentinel(
    server, audit_lines, stub_orchestrator,
):
    """OrchestratorResult(model="none", llm_used=False) must not put the
    string "none" on the line as a model id."""
    stub_orchestrator["result"] = _stub_result(
        outcome=OUTCOME_NO_CLIENT, model="none", provider=None, llm_used=False,
    )
    server.post("/ask", json={"question": QUESTION}, headers={"X-User-Id": "u-i105-nc"})
    line = audit_lines()[0]
    assert line["provider"] is None
    assert line["model"] is None
    assert line["usd_cost_estimate"] == 0.0


# ---------------------------------------------------------------------------
# i105 -- ask_orchestrated stamps the provider it dispatched to
# ---------------------------------------------------------------------------

def test_ask_orchestrated_stamps_the_dispatched_provider(fake_openai_wire, bootstrap):
    """(M5) provider=openai explicit -> result.provider == "openai" and the
    fake wire confirms that is what was dispatched."""
    result = ask_orchestrated(QUESTION, bootstrap, provider="openai", model=LUNA,
                              api_key="k", _eval_client=None)
    assert result.llm_used is True
    assert result.provider == "openai"
    assert result.model == LUNA
    assert {c["provider_name"] for c in fake_openai_wire} == {"openai"}


def test_ask_orchestrated_auto_detect_stamps_anthropic(monkeypatch, bootstrap):
    """provider=None dispatches to Anthropic (the documented default); the
    stamp says so rather than None."""
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    seen: list[str] = []

    def _fake_call(provider_name, *, model, **_kw):
        seen.append(provider_name)
        resp = NS(content=[NS(type="text", text="respuesta directa")], stop_reason="end_turn",
                  usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0))
        return OrchCallResult(response=resp, error_code=None, error_msg=None, attempts=1,
                              latency_ms=1.0, input_tokens=10, output_tokens=5, cache_read_tokens=0)

    monkeypatch.setattr(orch_mod, "call_orch_provider", _fake_call)
    result = ask_orchestrated(QUESTION, bootstrap, client=object(), provider=None,
                              model="claude-haiku-4-5-20251001", _eval_client=None)
    assert result.llm_used is True
    assert seen == ["anthropic"]
    assert result.provider == "anthropic"


def test_ask_orchestrated_no_client_leaves_provider_none(monkeypatch, bootstrap):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = ask_orchestrated(QUESTION, bootstrap, provider="openai", model=LUNA, _eval_client=None)
    assert result.outcome == OUTCOME_NO_CLIENT
    assert result.llm_used is False
    assert result.provider is None
    assert result.model == "none"


# ---------------------------------------------------------------------------
# i105 (c) -- one price table
# ---------------------------------------------------------------------------

def _load_script(name: str):
    import importlib.util as ilu
    path = Path(_PKG) / "scripts" / f"{name}.py"
    spec = ilu.spec_from_file_location(name, path)
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_there_is_one_price_table():
    """(c) audit.py has no per-provider table any more; both scripts use the
    shared per-model one; and no other file in the package carries a literal
    price row. (M6)"""
    assert not hasattr(audit_mod, "PROVIDER_PRICING_PER_1M")
    assert not hasattr(audit_mod, "_DEFAULT_PROVIDER")
    base = _load_script("measure_tool_routing")
    exp = _load_script("run_agentic_loop_experiment")
    assert base.PRICING_PER_1M_BY_MODEL is model_pricing.PRICING_PER_1M_BY_MODEL
    assert exp.DEFAULT_MODEL_PRICING_PER_1M == model_pricing.PRICING_PER_1M_BY_MODEL
    # Literal rows (`"<model>": {"input": ..., "output": ..., "cache_read": ...}`)
    # exist in exactly one source file.
    row = re.compile(r'"[^"]+":\s*\{\s*"input":\s*[\d.]+,\s*"output":\s*[\d.]+,\s*"cache_read"')
    carriers: set[str] = set()
    for py in Path(_PKG).rglob("*.py"):
        if "tests" in py.parts or ".venv" in py.parts:
            continue
        if row.search(py.read_text(encoding="utf-8", errors="ignore")):
            carriers.add(py.relative_to(_PKG).as_posix())
    assert carriers == {"fpl_grounded_assistant/model_pricing.py"}, carriers


def test_estimate_usd_cost_prices_by_model_with_the_provider_cache_convention():
    tokens = {"primary_input": 1_000_000, "primary_output": 0, "primary_cache_read": 900_000}
    # openai: cached share is a subset of input -> priced once, at the cache rate.
    assert audit_mod.estimate_usd_cost(tokens, LUNA, "openai") == pytest.approx(
        100_000 * _LUNA_INPUT_PER_TOKEN + 900_000 * _LUNA_CACHE_PER_TOKEN
    )
    # anthropic: cached share reported separately -> additive.
    haiku = model_pricing.PRICING_PER_1M_BY_MODEL["claude-haiku-4-5-20251001"]
    assert audit_mod.estimate_usd_cost(tokens, "claude-haiku-4-5-20251001", "anthropic") == pytest.approx(
        1.0 * haiku["input"] + 0.9 * haiku["cache_read"]
    )
    # Nothing bought -> 0.0 whatever the model, even None.
    assert audit_mod.estimate_usd_cost({}, None, None) == 0.0
    assert audit_mod.estimate_usd_cost({"total": 0}, "whatever", None) == 0.0
    # Tokens with no model -> unknown, not free.
    assert audit_mod.estimate_usd_cost({"primary_input": 5}, None, None) is None


def test_audit_entry_serialises_model_and_null_cost():
    line = audit_mod.make_audit_entry(
        question="q", branch="orchestrator", outcome="ok",
        tokens={"primary_input": 5, "total": 5}, provider="openai", model="unpriced-x",
    )
    assert line.model == "unpriced-x"
    assert line.usd_cost_estimate is None
    d = json.loads(json.dumps({"model": line.model, "usd_cost_estimate": line.usd_cost_estimate,
                               "provider": line.provider}))
    assert d == {"model": "unpriced-x", "usd_cost_estimate": None, "provider": "openai"}
