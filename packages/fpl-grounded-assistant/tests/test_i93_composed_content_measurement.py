"""i93: the content measurement (projection, script, read-out) -- no network.

An autouse fixture pins the probe module's globals and replaces both call
boundaries (``measure_tool_routing.run_one`` and
``fpl_grounded_assistant.orchestrator.ask_orchestrated``) with raisers; the
end-to-end test installs its own fakes over them (lesson PR #212).
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
import measure_i93_composed_content as probe  # noqa: E402
import analyze_i93_composed_content as analyzer  # noqa: E402


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


def _trace(*entries):
    return SimpleNamespace(tool_calls_trace=list(entries), answer_text="")


def _snap(*names):
    return {"name": "get_team_snapshot", "output": {"status": "ok",
            "top_players": [{"web_name": n} for n in names]}}


_OUTLOOK = {"name": "get_fixture_outlook", "output": {"status": "ok", "series": [{"gameweek": 5}]}}


# ---------------------------------------------------------------------------
# Projection: names count only when the tool returned them
# ---------------------------------------------------------------------------

def test_snapshot_web_names_come_from_the_trace_only():
    assert probe.snapshot_web_names(_trace(_OUTLOOK, _snap("Saka", "Ødegaard"))) == ["Saka", "Ødegaard"]
    assert probe.snapshot_web_names(_trace(_OUTLOOK)) == []


def test_named_real_players_is_accent_folded_substring_match():
    names = ["Saka", "Ødegaard", "A.Becker"]
    assert probe.named_real_players("Odegaard y Saka llegan finos; A.Becker sostiene", names) == names
    assert probe.named_real_players("Haaland es el mejor", names) == []   # not returned -> not real


def test_project_reports_composition_names_and_framing():
    r = _trace(_snap("Saka"), _OUTLOOK)
    p = probe.project(r, "Oportunidad: Saka (xG 2.88). Cómpralo.")
    assert p["composed"] is True
    assert p["tool_sequence"] == ["get_team_snapshot", "get_fixture_outlook"]
    assert p["named_real_players"] == ["Saka"]
    assert p["transaction_hits"] == ["compra:compralo"]


def test_project_single_tool_turn_is_not_composed():
    p = probe.project(_trace(_OUTLOOK), "J5: Arsenal a domicilio ante Brighton.")
    assert p["composed"] is False and p["named_real_players"] == [] and p["transaction_hits"] == []


# ---------------------------------------------------------------------------
# Script main(): no network
# ---------------------------------------------------------------------------

def test_main_refuses_when_estimate_exceeds_cap(tmp_path):
    rc = probe.main(["--out", str(tmp_path / "o.jsonl"), "--reps", "3", "--cap-usd", "0.0001"])
    assert rc == 2
    assert not (tmp_path / "o.jsonl").exists()


def test_main_writes_one_row_per_call_with_the_projection(tmp_path, monkeypatch):
    from fpl_grounded_assistant import orchestrator as orch_mod

    def fake_ask(question, bootstrap, **kw):
        team = question.split(" vs ")[0]
        r = _trace(_OUTLOOK, _snap("Saka"))
        r.answer_text = f"J5: {team}. Oportunidad: Saka (forma 7.5)."
        return r

    def fake_run_one(question, rep, bootstrap, api_key):
        orch_mod.ask_orchestrated(question["question"], bootstrap)
        return {"question_id": question["id"], "rep": rep, "exception": None, "cost_usd": 0.001}

    monkeypatch.setattr(base, "run_one", fake_run_one)
    monkeypatch.setattr(orch_mod, "ask_orchestrated", fake_ask)
    bs = tmp_path / "bs.json"
    bs.write_text("{}", encoding="utf-8")
    out = tmp_path / "o.jsonl"
    rc = probe.main(["--bootstrap", str(bs), "--out", str(out), "--reps", "2", "--cap-usd", "5"])
    assert rc == 0
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 20 * 2                      # the 20 fixtureCellQuestion phrases
    for r in rows:
        assert r["i78a"]["kind"] == "fixtureCellQuestion"
        assert r["i93"]["composed"] is True
        assert r["i93"]["named_real_players"] == ["Saka"]
        assert r["i93"]["transaction_hits"] == []
        assert r["corpus_sha256"]["description_asks_snapshot"] is True
        assert r["corpus_sha256"]["prompt_has_match_composition"] is True
    assert orch_mod.ask_orchestrated is fake_ask   # capture wrapper removed


# ---------------------------------------------------------------------------
# Read-out
# ---------------------------------------------------------------------------

def _row(qid, players, hits, composed=True, rep=0):
    return {"question_id": qid, "rep": rep, "exception": None, "cost_usd": 0.001,
            "i93": {"composed": composed, "named_real_players": players, "transaction_hits": hits,
                    "tool_sequence": ["get_fixture_outlook", "get_team_snapshot"] if composed else ["get_fixture_outlook"]}}


def test_readout_hit_needs_every_rep_named_and_clean():
    s = analyzer.summarize([_row("a", ["Saka"], [], rep=r) for r in range(3)])
    assert s["hits"] == 1 and s["named_reps"] == 3 and s["clean_reps"] == 3


def test_readout_named_but_not_clean_is_a_miss():
    s = analyzer.summarize([_row("a", ["Saka"], ["compra:compralo"], rep=r) for r in range(3)])
    assert s["hits"] == 0 and s["transaction_hit_reps"] == 3


def test_readout_two_of_three_named_is_a_miss():
    rows = [_row("a", ["Saka"], [], rep=0), _row("a", ["Saka"], [], rep=1), _row("a", [], [], composed=False, rep=2)]
    s = analyzer.summarize(rows)
    assert s["hits"] == 0 and s["per_phrase"]["a"]["named"] == 2


def test_readout_before_shape_is_zero_named_and_all_clean():
    s = analyzer.summarize([_row("a", [], [], composed=False, rep=r) for r in range(3)])
    assert s["hits"] == 0 and s["named_reps"] == 0 and s["clean_reps"] == 3


def test_readout_splits_synthetic_dgw_cells_and_reports_majority():
    rows = [_row("real", ["Saka"], [], rep=r) for r in range(3)]
    rows += [dict(_row("dgw", ["Saka"] if r < 2 else [], [], rep=r), i78a={"dgw_synthetic": True}) for r in range(3)]
    s = analyzer.summarize(rows)
    assert s["real_cells"] == 1 and s["real_hits"] == 1
    assert s["synthetic_dgw_cells"] == 1 and s["synthetic_dgw_hits"] == 0
    assert s["hits"] == 1 and s["majority_hits"] == 2


def test_readout_on_the_committed_artifacts():
    root = Path(__file__).resolve().parent.parent / "field-notes" / "artifacts"
    before = analyzer.summarize(analyzer.load(str(root / "i93-composed-content-before.jsonl")))
    after = analyzer.summarize(analyzer.load(str(root / "i93-composed-content-after.jsonl")))
    assert before["phrases"] == 20 and before["named_reps"] == 0 and before["composed_reps"] == 0
    assert after["phrases"] == 20
    # The plan's gate (>= 8/10 phrases name a real player with a real number,
    # every run clean) is asserted on the cells whose data matches the
    # phrase. The corpus's synthetic DGW cells (a second fixture the frozen
    # bootstrap does not have, kept from i78-A for routing) are reported,
    # not gated: the model explaining a contradiction instead of naming
    # players is not the failure this card is about.
    assert after["real_cells"] == 12
    assert after["real_hits"] * 10 >= after["real_cells"] * 8
    assert after["transaction_hit_reps"] == 0
    assert after["synthetic_dgw_cells"] == 8
    assert all(r["corpus_sha256"]["description_asks_snapshot"] is False
               for r in analyzer.load(str(root / "i93-composed-content-before.jsonl")))
    assert all(r["corpus_sha256"]["description_asks_snapshot"] is True
               for r in analyzer.load(str(root / "i93-composed-content-after.jsonl")))
