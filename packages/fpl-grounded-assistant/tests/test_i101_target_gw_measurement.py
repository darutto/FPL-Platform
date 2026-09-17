"""i101: the argument measurement (corpus selector, script, read-out).

No network, ever: an autouse fixture pins the probe module's globals and
replaces both call boundaries (``measure_tool_routing.run_one`` and
``fpl_grounded_assistant.orchestrator.ask_orchestrated``) with raisers. Tests
that want ``main()`` to "run" install their own stub over ``run_one`` and a
fake result over ``ask_orchestrated`` (lesson PR #212: probe scripts mutate
module globals and a later test can sail into a paid call).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import measure_tool_routing as base  # noqa: E402
import tool_routing_corpus as corpus  # noqa: E402
import measure_i101_target_gw_args as probe  # noqa: E402
import analyze_i101_target_gw_args as analyzer  # noqa: E402


class _NetworkForbidden(RuntimeError):
    pass


def _forbidden(*_a, **_k):
    raise _NetworkForbidden("a call boundary was reached: no test here may make a provider call")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    base._configure_imports()
    from fpl_grounded_assistant import orchestrator as orch_mod
    monkeypatch.setattr(base, "PROVIDER", base.PROVIDER)
    monkeypatch.setattr(base, "MODEL", base.MODEL)
    monkeypatch.setattr(base, "run_one", _forbidden)
    monkeypatch.setattr(orch_mod, "ask_orchestrated", _forbidden)
    monkeypatch.setattr(base, "_load_env_file", lambda path: None)
    monkeypatch.setattr(base, "require_api_key", lambda provider: "dummy-key")


# ---------------------------------------------------------------------------
# Corpus selector
# ---------------------------------------------------------------------------

def test_i78a_corpus_keeps_its_base_set_despite_the_i101_cells():
    entries = corpus.i78a_fixture_click_corpus()
    assert len(entries) == 20          # 28 before i93-b (one cell phrase per axis)
    assert not any(corpus._I101_ID_RE.search(e["id"]) for e in entries)


def test_i101_corpus_selects_only_future_cells_at_least_two_ahead():
    entries = corpus.i101_target_gw_corpus(current_gw=1)
    assert len(entries) == 16
    for e in entries:
        assert e["family"] == "fixture_click_target_gw"
        assert e["i78a"]["kind"] == "fixtureCellQuestion"
        assert e["i78a"]["cell_position"] == "future"
        assert e["i101"]["expected_target_gw"] == e["i78a"]["gameweek"]
        assert e["i101"]["lead"] >= 2
        # The number the read-out will compare against comes from the
        # generator's metadata, and it is the one the prose names.
        assert f"J{e['i101']['expected_target_gw']}" in e["question"]
    assert sorted({e["i101"]["expected_target_gw"] for e in entries}) == [3, 4, 5, 6]


def test_i101_corpus_lead_is_measured_from_the_given_current_gw():
    at_1 = {e["id"] for e in corpus.i101_target_gw_corpus(current_gw=1)}
    at_3 = {e["id"] for e in corpus.i101_target_gw_corpus(current_gw=3)}
    at_5 = {e["id"] for e in corpus.i101_target_gw_corpus(current_gw=5)}
    assert at_3 < at_1                      # J3 and J4 drop out (lead < 2)
    assert all(i.endswith(("-j5", "-j6")) for i in at_3)
    assert at_5 == set()                    # nothing is >= J7


def test_i101_corpus_min_lead_is_a_parameter():
    assert len(corpus.i101_target_gw_corpus(current_gw=1, min_lead=5)) == 4  # only J6


# ---------------------------------------------------------------------------
# Script: per-call projection
# ---------------------------------------------------------------------------

def _result(trace):
    return SimpleNamespace(tool_calls_trace=trace)


def test_project_calls_reads_args_and_series_off_the_trace():
    result = _result([
        {"round": 1, "name": "get_gameweek_context", "args": {}, "output": {"status": "ok"}},
        {"round": 1, "name": "get_fixture_outlook",
         "args": {"axis": "attack", "team_query": "Newcastle", "target_gw": 5},
         "output": {"status": "ok", "verdict_scope": "match",
                    "series": [{"gameweek": 5, "band": 2}]}},
    ])
    calls = probe.project_calls(result)
    assert calls == [{
        "round": 1, "target_gw": 5, "horizon": None, "team_query": "Newcastle",
        "axis": "attack", "output_status": "ok", "verdict_scope": "match", "series_gws": [5],
    }]


def test_project_calls_is_empty_when_the_tool_never_ran():
    assert probe.project_calls(_result([{"name": "get_team_schedule", "args": {}, "output": {}}])) == []
    assert probe.project_calls(_result([])) == []


# ---------------------------------------------------------------------------
# Script: main() end to end, no network
# ---------------------------------------------------------------------------

def _bootstrap_next_gw(gw: int) -> dict:
    return {"events": [{"id": gw, "is_next": True}], "teams": [], "team_fixtures": {}}


def test_main_refuses_when_estimate_exceeds_cap(tmp_path):
    bs = tmp_path / "bs.json"
    bs.write_text(json.dumps(_bootstrap_next_gw(1)), encoding="utf-8")
    rc = probe.main(["--bootstrap", str(bs), "--out", str(tmp_path / "o.jsonl"),
                     "--reps", "3", "--cap-usd", "0.0001"])
    assert rc == 2
    assert not (tmp_path / "o.jsonl").exists()


def test_main_refuses_when_no_phrase_is_far_enough_ahead(tmp_path):
    bs = tmp_path / "bs.json"
    bs.write_text(json.dumps(_bootstrap_next_gw(6)), encoding="utf-8")
    rc = probe.main(["--bootstrap", str(bs), "--out", str(tmp_path / "o.jsonl")])
    assert rc == 1


def test_main_writes_one_row_per_call_with_the_projected_trace(tmp_path, monkeypatch):
    bs = tmp_path / "bs.json"
    bs.write_text(json.dumps(_bootstrap_next_gw(1)), encoding="utf-8")
    from fpl_grounded_assistant import orchestrator as orch_mod

    seen: list[str] = []

    def fake_run_one(question, rep, bootstrap, api_key):
        # Stand-in for the paid call: exercise the wrapped ask_orchestrated
        # exactly as the real run_one would, then return a minimal row.
        result = orch_mod.ask_orchestrated(question["question"], bootstrap)
        seen.append(question["id"])
        return {"question_id": question["id"], "rep": rep, "exception": None,
                "cost_usd": 0.001, "tool_sequence": [e["name"] for e in result.tool_calls_trace]}

    def fake_ask(question, bootstrap, **kw):
        gw = int(question.split(", J")[1].split(":")[0])
        return _result([{"round": 1, "name": "get_fixture_outlook",
                         "args": {"target_gw": gw, "axis": "attack"},
                         "output": {"status": "ok", "series": [{"gameweek": gw}]}}])

    monkeypatch.setattr(base, "run_one", fake_run_one)
    monkeypatch.setattr(orch_mod, "ask_orchestrated", fake_ask)
    out = tmp_path / "o.jsonl"
    rc = probe.main(["--bootstrap", str(bs), "--out", str(out), "--reps", "2", "--cap-usd", "5"])
    assert rc == 0
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 16 * 2
    assert len(seen) == 32
    for r in rows:
        assert r["i101"]["calls"][0]["target_gw"] == r["i101"]["expected_target_gw"]
        assert r["corpus_sha256"]["schema_has_target_gw"] is True
    # The capture wrapper is removed again: the boundary is exactly what it
    # was before main() ran (here the fake), not a lingering wrapper.
    assert orch_mod.ask_orchestrated is fake_ask


# ---------------------------------------------------------------------------
# Read-out
# ---------------------------------------------------------------------------

def _row(qid: str, expected: int, target_gw, series, horizon=None, rep=0):
    return {"question_id": qid, "rep": rep, "exception": None, "cost_usd": 0.001,
            "i101": {"expected_target_gw": expected,
                     "calls": [{"target_gw": target_gw, "horizon": horizon, "series_gws": series}]}}


def test_readout_hit_needs_every_rep_arg_and_series_right():
    rows = [_row("a", 5, 5, [5], rep=r) for r in range(3)]
    s = analyzer.summarize(rows)
    assert s["hits"] == 1 and s["phrases"] == 1
    assert s["per_phrase"]["a"]["hit"] is True


def test_readout_right_argument_wrong_series_is_a_miss():
    rows = [_row("a", 5, 5, [1, 2, 3, 4, 5], rep=r) for r in range(3)]
    s = analyzer.summarize(rows)
    assert s["hits"] == 0
    assert s["per_phrase"]["a"]["arg_ok"] == 3 and s["per_phrase"]["a"]["series_ok"] == 0


def test_readout_two_of_three_is_a_miss():
    rows = [_row("a", 5, 5, [5], rep=0), _row("a", 5, 5, [5], rep=1), _row("a", 5, None, [1], horizon=1, rep=2)]
    s = analyzer.summarize(rows)
    assert s["hits"] == 0
    assert s["per_phrase"]["a"]["arg_ok"] == 2


def test_readout_before_shape_horizon_only_is_zero_everywhere():
    rows = [_row("a", 5, None, [1, 2, 3, 4, 5], horizon=5, rep=r) for r in range(3)]
    s = analyzer.summarize(rows)
    assert s["arg_ok_reps"] == 0 and s["series_ok_reps"] == 0 and s["hits"] == 0


def test_readout_unrouted_rep_is_not_a_hit():
    rows = [{"question_id": "a", "rep": 0, "exception": None, "cost_usd": 0,
             "i101": {"expected_target_gw": 5, "calls": []}}]
    s = analyzer.summarize(rows)
    assert s["per_phrase"]["a"]["routed"] == 0 and s["hits"] == 0


def test_readout_on_the_committed_artifacts():
    """The committed before/after files say what the PR says."""
    root = Path(__file__).resolve().parent.parent / "field-notes" / "artifacts"
    before = analyzer.summarize(analyzer.load(str(root / "i101-target-gw-before.jsonl")))
    after = analyzer.summarize(analyzer.load(str(root / "i101-target-gw-after.jsonl")))
    assert before["phrases"] == 16 and before["hits"] == 0 and before["arg_ok_reps"] == 0
    assert after["phrases"] == 16 and after["hits"] == 16 and after["arg_ok_reps"] == 48
    assert all(r["corpus_sha256"]["schema_has_target_gw"] is False
               for r in analyzer.load(str(root / "i101-target-gw-before.jsonl")))
    assert all(r["corpus_sha256"]["schema_has_target_gw"] is True
               for r in analyzer.load(str(root / "i101-target-gw-after.jsonl")))
