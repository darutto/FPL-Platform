"""i109: ``measure_tool_routing.py --team-id`` connects a team the way prod
does, never mutates the shared bootstrap, and every row says what
``get_my_squad`` actually returned -- read off the trace.

Before this, ``run_one`` handed ``ask_orchestrated`` the frozen bootstrap with
no ``_my_team_id``, so every "evaluate my squad" chip question in the corpus
was measured against a tool that could only answer ``no_team_connected``;
the 14 chip-on-existing-squad ids could not be measured as they run in prod.

What is pinned, and what kills each pin (each guard mutated separately):

  M1  run_one passes the shared dict through with the key (mutation)  -> test_shared_bootstrap_is_never_mutated dies
  M2  run_one drops the key from the copy                             -> test_team_id_reaches_the_orchestrator_on_a_copy dies
  M3  my_squad_result read from the question/text, not the trace      -> test_my_squad_result_* die
  M4  --team-id parsed but not passed to run_one                       -> test_team_id_flag_reaches_run_one dies
  M5  env FPL_MEASURE_TEAM_ID ignored                                  -> test_team_id_env_reaches_run_one dies

No credentials and no network: ``ask_orchestrated`` is stubbed at the module
the script imports it from, exactly as ``test_probe_provider_flags`` does.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import types
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parent.parent
_SCRIPTS = _PKG / "scripts"
for _p in (str(_PKG), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import measure_tool_routing as base  # noqa: E402

_REAL_RUN_ONE = base.run_one

_QUESTION = {
    "id": "cvg-02", "family": "chip_vs_gameweek", "acceptable_tools": ["get_chip_advice", "build_squad"],
    "control": False,
    "question": "¿Es buena idea usar el bench boost en la fecha 3? Analizá mi plantilla primero.",
}


@pytest.fixture(autouse=True)
def no_paid_calls(monkeypatch):
    """Same rail as test_probe_provider_flags: run_one is a raiser unless a
    test restores the real one against a stubbed orchestrator."""
    def _forbidden(*args, **kwargs):
        raise AssertionError("run_one reached: no test here may make a provider call")
    monkeypatch.setattr(base, "PROVIDER", base.PROVIDER)
    monkeypatch.setattr(base, "MODEL", base.MODEL)
    monkeypatch.setattr(base, "run_one", _forbidden)
    monkeypatch.setattr(base, "_load_env_file", lambda path: None)
    monkeypatch.delenv(base.TEAM_ID_ENV, raising=False)


class _Result:
    """The subset of OrchestratorResult run_one reads, with a settable trace."""
    outcome = "ok"
    tool_chosen = "get_chip_advice"
    tool_call_count = 1
    tool_args: dict = {}
    tool_output: dict = {"status": "ok"}
    synthesis_turn = True
    answer_text = "Tu plantilla está lista para el bench boost."   # mentions a squad regardless
    rounds_used = 1
    error = None
    primary_input_tokens = 10
    primary_output_tokens = 20
    primary_cache_read_tokens = 0
    total_tokens = 30

    def __init__(self, trace: tuple[dict, ...]) -> None:
        self.tool_calls_trace = trace


def _stub_orchestrator(monkeypatch, result: _Result):
    """Stub the module run_one lazily imports; record the bootstrap it got."""
    seen: dict = {}

    def _ask_orchestrated(question, bootstrap, **kwargs):
        seen["bootstrap"] = bootstrap
        return result

    module = types.ModuleType("fpl_grounded_assistant.orchestrator")
    module.ask_orchestrated = _ask_orchestrated
    monkeypatch.setitem(sys.modules, "fpl_grounded_assistant.orchestrator", module)
    monkeypatch.setattr(base, "run_one", _REAL_RUN_ONE)
    return seen


def _squad_entry(status: str = "ok", players: int = 15) -> dict:
    output = {"status": status}
    if status == "ok":
        output["players"] = [{"id": i} for i in range(players)]
    return {"round": 1, "tool_call_id": "c1", "name": "get_my_squad", "args": {},
            "output": output, "success": status == "ok"}


_CHIP_ENTRY = {"round": 2, "tool_call_id": "c2", "name": "get_chip_advice", "args": {"chip": "bench_boost"},
               "output": {"status": "ok"}, "success": True}


# ---------------------------------------------------------------------------
# 1. The team id reaches the orchestrator on a COPY; the shared dict is untouched
# ---------------------------------------------------------------------------

def test_team_id_reaches_the_orchestrator_on_a_copy(monkeypatch):
    seen = _stub_orchestrator(monkeypatch, _Result((_squad_entry(), _CHIP_ENTRY)))
    shared = {"elements": [], "teams": [], "events": []}
    obs = _REAL_RUN_ONE(_QUESTION, 0, shared, "key", team_id=68643)
    got = seen["bootstrap"]
    assert got[base.MY_TEAM_ID_KEY] == 68643            # (M2)
    assert got is not shared                            # a copy...
    assert got["elements"] is shared["elements"]        # ...shallow, like harness.ask_v2
    assert obs["team_id_present"] is True


def test_shared_bootstrap_is_never_mutated(monkeypatch):
    """The 118xR runs reuse ONE dict; the key must not leak into it. (M1)"""
    _stub_orchestrator(monkeypatch, _Result((_squad_entry(), _CHIP_ENTRY)))
    shared = {"elements": [], "teams": [], "events": []}
    before = dict(shared)
    _REAL_RUN_ONE(_QUESTION, 0, shared, "key", team_id=68643)
    assert shared == before
    assert base.MY_TEAM_ID_KEY not in shared


def test_without_team_id_the_call_is_unchanged(monkeypatch):
    """No flag: the orchestrator gets the very same object, with no key, and
    the row says so. This is the "0 changes without --team-id" half."""
    seen = _stub_orchestrator(monkeypatch, _Result((_squad_entry("no_team_connected"), _CHIP_ENTRY)))
    shared = {"elements": [], "teams": [], "events": []}
    obs = _REAL_RUN_ONE(_QUESTION, 0, shared, "key")
    assert seen["bootstrap"] is shared
    assert base.MY_TEAM_ID_KEY not in seen["bootstrap"]
    assert obs["team_id_present"] is False


def test_bootstrap_for_call_is_the_one_rule():
    shared = {"a": 1}
    assert base.bootstrap_for_call(shared, None) is shared
    copy = base.bootstrap_for_call(shared, 7)
    assert copy == {"a": 1, base.MY_TEAM_ID_KEY: 7}
    assert shared == {"a": 1}
    # Same key production reads and injects (get_my_squad.py / harness.py).
    assert base.MY_TEAM_ID_KEY == "_my_team_id"


# ---------------------------------------------------------------------------
# 2. my_squad_result is read off the trace -- not the question, not the text
# ---------------------------------------------------------------------------

def test_my_squad_result_squad_when_the_tool_returned_players(monkeypatch):
    _stub_orchestrator(monkeypatch, _Result((_squad_entry(), _CHIP_ENTRY)))
    obs = _REAL_RUN_ONE(_QUESTION, 0, {}, "key", team_id=68643)
    assert obs["my_squad_result"] == "squad"


def test_my_squad_result_no_team_when_the_handler_saw_no_id(monkeypatch):
    _stub_orchestrator(monkeypatch, _Result((_squad_entry("no_team_connected"), _CHIP_ENTRY)))
    obs = _REAL_RUN_ONE(_QUESTION, 0, {}, "key")
    assert obs["my_squad_result"] == "no_team"


def test_my_squad_result_not_called_even_though_the_question_asks_for_a_squad(monkeypatch):
    """(M3) The question says "analizá mi plantilla" and the answer text
    mentions the squad; the trace shows only get_chip_advice ran."""
    _stub_orchestrator(monkeypatch, _Result((_CHIP_ENTRY,)))
    obs = _REAL_RUN_ONE(_QUESTION, 0, {}, "key", team_id=68643)
    assert obs["my_squad_result"] == "not_called"
    assert "plantilla" in obs["question"] and "plantilla" in obs["answer_text"]


def test_my_squad_result_error_is_not_no_team(monkeypatch):
    """A bad id / network failure / empty ok must not be read as "the flag
    did not reach the tool"."""
    for status, players in (("not_found", 0), ("error", 0), ("ok", 0)):
        _stub_orchestrator(monkeypatch, _Result((_squad_entry(status, players),)))
        obs = _REAL_RUN_ONE(_QUESTION, 0, {}, "key", team_id=1)
        assert obs["my_squad_result"] == "error", status


def test_my_squad_result_squad_wins_over_an_earlier_failure(monkeypatch):
    """A retry that fetched the squad after a first failed call: squad."""
    _stub_orchestrator(monkeypatch, _Result((_squad_entry("error"), _squad_entry())))
    obs = _REAL_RUN_ONE(_QUESTION, 0, {}, "key", team_id=68643)
    assert obs["my_squad_result"] == "squad"


def test_exception_row_carries_the_columns_too(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("boom")
    module = types.ModuleType("fpl_grounded_assistant.orchestrator")
    module.ask_orchestrated = _boom
    monkeypatch.setitem(sys.modules, "fpl_grounded_assistant.orchestrator", module)
    monkeypatch.setattr(base, "run_one", _REAL_RUN_ONE)
    obs = _REAL_RUN_ONE(_QUESTION, 0, {}, "key", team_id=68643)
    assert obs["outcome"] == "harness_exception"
    assert obs["team_id_present"] is True
    assert obs["my_squad_result"] == "not_called"


# ---------------------------------------------------------------------------
# 3. The flag and the env var are effective, not decorative
# ---------------------------------------------------------------------------

@pytest.fixture
def out_dir():
    path = Path(tempfile.mkdtemp())
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _stop_at_run_one(monkeypatch):
    seen: dict = {}

    def _stop(*args, **kwargs):
        seen["team_id"] = kwargs.get("team_id", "<not passed>")
        raise RuntimeError("stop before any paid call")

    monkeypatch.setattr(base, "run_one", _stop)
    return seen


def test_team_id_flag_reaches_run_one(monkeypatch, out_dir):
    """(M4)"""
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    seen = _stop_at_run_one(monkeypatch)
    with pytest.raises(RuntimeError, match="stop before any paid call"):
        base.main(["--out", str(out_dir / "o.jsonl"), "--only-id", "cvg-02", "--team-id", "68643"])
    assert seen == {"team_id": 68643}


def test_team_id_env_reaches_run_one(monkeypatch, out_dir):
    """(M5)"""
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv(base.TEAM_ID_ENV, "68643")
    seen = _stop_at_run_one(monkeypatch)
    with pytest.raises(RuntimeError, match="stop before any paid call"):
        base.main(["--out", str(out_dir / "o.jsonl"), "--only-id", "cvg-02"])
    assert seen == {"team_id": 68643}


def test_flag_wins_over_env(monkeypatch):
    monkeypatch.setenv(base.TEAM_ID_ENV, "1")
    assert base.resolve_team_id(68643) == 68643
    assert base.resolve_team_id(None) == 1


def test_no_flag_no_env_means_none(monkeypatch, out_dir):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    seen = _stop_at_run_one(monkeypatch)
    with pytest.raises(RuntimeError, match="stop before any paid call"):
        base.main(["--out", str(out_dir / "o.jsonl"), "--only-id", "cvg-02"])
    assert seen == {"team_id": None}


def test_non_numeric_env_aborts_instead_of_silently_running_without_a_team(monkeypatch):
    monkeypatch.setenv(base.TEAM_ID_ENV, "sixty-eight")
    with pytest.raises(SystemExit):
        base.resolve_team_id(None)


def test_other_scripts_calling_run_one_positionally_are_unaffected(monkeypatch):
    """golden_battery / measure_captain_pool_* / measure_i41_* call
    ``base.run_one(q, rep, bootstrap, api_key)``: still valid, no team."""
    seen = _stub_orchestrator(monkeypatch, _Result((_CHIP_ENTRY,)))
    shared: dict = {"elements": []}
    obs = _REAL_RUN_ONE(_QUESTION, 3, shared, "key")
    assert seen["bootstrap"] is shared
    assert obs["team_id_present"] is False
    assert obs["my_squad_result"] == "not_called"
