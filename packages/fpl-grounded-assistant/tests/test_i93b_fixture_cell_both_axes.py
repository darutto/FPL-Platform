"""
i93-b -- the /fixtures cell tap asks BOTH sides of the match
("...: ¿qué tal pinta ofensivamente y defensivamente para el Spurs?"), so
the composed turn reads the calendar on BOTH axes plus the team snapshot in
ONE round, and the answer is the whole profile of that fixture.

Layers, each asserted from what was produced (never from the phrase sent):

* orchestrator -- a model response with THREE tool_use blocks
  (get_fixture_outlook axis=attack, get_team_snapshot, get_fixture_outlook
  axis=defence -- the snapshot in the middle, the adversarial order)
  executes all three in the single-round path (no loop) and hands the three
  outputs, both axis wordings included, to the synthesis call;
* harness      -- the singular slot of the turn is still a CALENDAR call,
  ``routing_trace.tool_args_sequence`` carries the axis of every executed
  call parallel to ``tool_sequence`` (what the prod check reads), and the
  adapter's intent is ``fixture_outlook``;
* catalog + prompt -- get_fixture_outlook instructs the two-axis pair for
  the both-sides phrase (one axis for a one-side phrase) and MATCH_COMPOSITION
  asks for both sides in the prose; the i101 target_gw text is intact;
* measurement  -- the probe reads ``both_axes`` / ``target_gw_ok`` /
  ``named_def_or_gkp`` off the executed trace, the analyzer's ``full_hit``
  needs both axes on every rep, and the i93 artifacts (no calendar_calls
  field) read as 0 both-axes, not as a crash;
* corpus       -- the generated contract file has ONE cell phrase per cell
  (axis 'both'), the i78-A matrix keeps 20, i93 measures all 24 cells.

Deterministic: fake provider clients only, no network.
"""
from __future__ import annotations

import json
import os as _os
import sys as _sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

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

_SCRIPTS = Path(_PKG) / "scripts"
if str(_SCRIPTS) not in _sys.path:
    _sys.path.insert(0, str(_SCRIPTS))

import fpl_grounded_assistant  # noqa: E402,F401
from fpl_grounded_assistant import harness, harness_adapter, provider_client  # noqa: E402
from fpl_grounded_assistant.harness import ROUTING_TRACE_OPTIONAL_KEYS  # noqa: E402
from fpl_grounded_assistant.orchestrator import (  # noqa: E402
    OUTCOME_OK,
    PROVIDER_OPENAI,
    _SYSTEM_PROMPT,
    ask_orchestrated,
)
from fpl_grounded_assistant.tool_schema_registry import get_tool_schema  # noqa: E402

from test_i93_fixture_cell_composed_analysis import _bootstrap  # noqa: E402

import measure_tool_routing as base  # noqa: E402
import measure_i93_composed_content as probe  # noqa: E402
import analyze_i93_composed_content as analyzer  # noqa: E402
import tool_routing_corpus as corpus  # noqa: E402

QUESTION = "Arsenal vs BHA (a domicilio), J5: ¿qué tal pinta ofensivamente y defensivamente para el Arsenal?"
SYNTHESIS = (
    "J5: Arsenal a domicilio ante Brighton — dificultad ofensiva 3/5 (media), "
    "dificultad para portería a cero 3/5 (media); ventaja Arsenal. "
    "Ataque: Saka (xG 2.88) y Ødegaard (xA 1.3). Defensa: Raya (forma 7.2) y "
    "Gabriel (forma 6.0) como oportunidad en este cruce."
)


class _NetworkForbidden(RuntimeError):
    pass


def _forbidden(*_a, **_k):
    raise _NetworkForbidden("a call boundary was reached: no test here may make a provider call")


@pytest.fixture(autouse=True)
def _single_round_no_network(monkeypatch):
    """Prod shape (loop OFF) and every paid boundary of the probe raised."""
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.setenv("FPL_ORCH_MAX_RETRIES", "0")
    monkeypatch.setattr(provider_client, "_OPENAI_AVAILABLE", True)
    base._configure_imports()
    monkeypatch.setattr(base, "run_one", _forbidden)
    monkeypatch.setattr(base, "_load_env_file", lambda path: None)
    monkeypatch.setattr(base, "require_api_key", lambda provider: "dummy-key")


# ---------------------------------------------------------------------------
# Fake OpenAI client: round 1 = THREE function calls; round 2 = text
# ---------------------------------------------------------------------------

def _call(name: str, call_id: str, **args) -> object:
    return NS(type="function_call", call_id=call_id, name=name, arguments=json.dumps(args))


def _three_tool_response() -> object:
    return NS(output=[
        NS(type="reasoning", id="r-1"),
        _call("get_fixture_outlook", "oai-att", axis="attack", team_query="Arsenal", target_gw=5),
        _call("get_team_snapshot", "oai-snap", team_name="Arsenal", top_n_players=5),
        _call("get_fixture_outlook", "oai-def", axis="defence", team_query="Arsenal", target_gw=5),
    ], output_text="")


def _text_response(text: str) -> object:
    return NS(output_text="", output=[NS(type="message", content=[NS(type="output_text", text=text)])])


class _Client:
    def __init__(self, responses: list[object]) -> None:
        self.responses = self
        self.queue = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.queue.pop(0)


def _run_three(synthesis=SYNTHESIS):
    client = _Client([_three_tool_response(), _text_response(synthesis)])
    result = ask_orchestrated(QUESTION, _bootstrap(), provider=PROVIDER_OPENAI, client=client,
                              api_key="test-key", _eval_client=None)
    return result, client


# ---------------------------------------------------------------------------
# Orchestrator: three tool_use blocks, one round, both axis wordings reach synthesis
# ---------------------------------------------------------------------------

def test_three_tools_in_one_response_all_execute_without_the_loop():
    result, client = _run_three()
    assert result.outcome == OUTCOME_OK
    assert [e["name"] for e in result.tool_calls_trace] == [
        "get_fixture_outlook", "get_team_snapshot", "get_fixture_outlook"]
    assert [e["round"] for e in result.tool_calls_trace] == [1, 1, 1]
    assert result.tool_call_count == 3
    assert len(client.calls) == 2  # one tool round + one synthesis call, no third
    att, snap, dfn = (e["output"] for e in result.tool_calls_trace)
    # Two real calendar reads, one per axis, on the SAME match; the band is
    # the same number (FDR is axis-agnostic) but the wording is the tool's.
    assert att["status"] == "ok" and att["axis"] == "attack"
    assert dfn["status"] == "ok" and dfn["axis"] == "defence"
    assert [g["gameweek"] for g in att["series"]] == [5] == [g["gameweek"] for g in dfn["series"]]
    assert "dificultad ofensiva" in att["verdict"]
    assert "dificultad para portería a cero" in dfn["verdict"]
    assert [p["web_name"] for p in snap["top_players"]][:2] == ["Saka", "Raya"]


def test_synthesis_call_receives_all_three_outputs():
    _result, client = _run_three()
    follow_up = json.dumps(client.calls[1].get("input") or client.calls[1].get("messages"),
                           default=str, ensure_ascii=False)
    assert "dificultad ofensiva" in follow_up
    # The tool payloads are nested JSON strings (ASCII-escaped: "porter\u00eda"),
    # so the defence wording is asserted on its accent-free pieces.
    assert "dificultad para porter" in follow_up and "a cero" in follow_up
    assert "Saka" in follow_up and "top_players" in follow_up


# ---------------------------------------------------------------------------
# Harness: the slot is a calendar call; tool_args_sequence carries the axes
# ---------------------------------------------------------------------------

def _ask_v2_with(monkeypatch, orch_result):
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.ask_orchestrated", lambda *a, **k: orch_result)
    return harness.ask_v2(QUESTION, _bootstrap(), orch_client=object())


def test_both_axes_turn_keeps_a_calendar_call_as_the_singular_slot(monkeypatch):
    orch_result, _client = _run_three()
    out = _ask_v2_with(monkeypatch, orch_result)
    assert out["selected_tool"] == "get_fixture_outlook"
    assert out["tool_input"]["team_query"] == "Arsenal" and out["tool_input"]["target_gw"] == 5
    assert out["tool_input"]["axis"] in ("attack", "defence")
    assert out["raw_output"]["verdict_scope"] == "match"
    assert out["fixture_outlook"] is not None
    assert out["routing_trace"]["composed_primary_tool"] == "get_fixture_outlook"
    assert out["answer_text"] == SYNTHESIS
    from fpl_server import AskRequest
    resp = harness_adapter.to_ask_response(out, AskRequest(question=QUESTION))
    assert resp.intent == "fixture_outlook"
    assert out.get("generic_card") is None


def test_tool_args_sequence_is_parallel_to_tool_sequence_and_carries_the_axes(monkeypatch):
    orch_result, _client = _run_three()
    out = _ask_v2_with(monkeypatch, orch_result)
    rt = out["routing_trace"]
    assert rt["tool_sequence"] == ["get_fixture_outlook", "get_team_snapshot", "get_fixture_outlook"]
    assert len(rt["tool_args_sequence"]) == len(rt["tool_sequence"])
    assert [a.get("axis") for a in rt["tool_args_sequence"]] == ["attack", None, "defence"]
    assert [a.get("target_gw") for a in rt["tool_args_sequence"]] == [5, None, 5]
    assert rt["tool_args_sequence"][1] == {"team_name": "Arsenal", "top_n_players": 5}
    # Copies, not the trace's own dicts.
    rt["tool_args_sequence"][0]["axis"] = "mutated"
    assert orch_result.tool_calls_trace[0]["args"]["axis"] == "attack"


def test_tool_args_sequence_and_composed_primary_tool_are_declared_optional_keys():
    assert {"tool_sequence", "tool_args_sequence", "composed_primary_tool"} <= ROUTING_TRACE_OPTIONAL_KEYS


def test_tool_args_sequence_is_empty_when_no_tool_ran():
    from fpl_grounded_assistant.orchestrator import OrchestratorResult
    orch_result = OrchestratorResult(
        question=QUESTION, tool_chosen=None, tool_args={}, tool_output={}, answer_text="x",
        llm_used=True, model="m", outcome=OUTCOME_OK, tool_call_count=0, tool_calls_trace=(),
        synthesis_turn=False,
    )
    rt: dict = {}
    harness._project_orchestrator_run(rt, orch_result)
    assert rt["tool_sequence"] == [] and rt["tool_args_sequence"] == []


# ---------------------------------------------------------------------------
# Catalog + prompt
# ---------------------------------------------------------------------------

def test_catalog_instructs_the_two_axis_pair_for_the_both_sides_phrase():
    desc = get_tool_schema("get_fixture_outlook").description
    assert "¿qué tal pinta ofensivamente y defensivamente para el Newcastle?" in desc
    assert "call this tool TWICE in the same response" in desc
    assert "once with axis='attack' and once with axis='defence'" in desc
    # A one-side phrase keeps its single axis.
    assert "ofensivo→attack, portería a cero→defence" in desc
    # i93's snapshot pairing and i101's target_gw instruction are intact.
    assert "ALSO call get_team_snapshot(team_name=<the same team>, top_n_players=5) in the SAME response" in desc
    assert "pass target_gw=5" in desc and "Do NOT compute horizon" in desc
    assert "expected_goals_conceded, saves or defensive_contribution" in desc
    snap = get_tool_schema("get_team_snapshot").description
    assert "ofensivamente y defensivamente" in snap
    assert "a DEF/GKP among them carries the defensive side" in snap


def test_system_prompt_asks_for_both_sides_when_both_axes_ran():
    assert "MATCH_COMPOSITION" in _SYSTEM_PROMPT
    assert "When the calendar ran on BOTH axes (attack and defence), the answer has BOTH sides" in _SYSTEM_PROMPT
    assert "dificultad para portería a cero + a DEF/GKP if the snapshot returned one" in _SYSTEM_PROMPT
    assert "if none is among the top_players, say the defensive side rests on the calendar read" in _SYSTEM_PROMPT
    # The boundary is untouched.
    assert "not even to say you are NOT recommending one" in _SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Probe projections (read off the trace)
# ---------------------------------------------------------------------------

def _cal(axis, status="ok", target_gw=5):
    return {"name": "get_fixture_outlook", "args": {"axis": axis, "team_query": "Arsenal", "target_gw": target_gw},
            "output": {"status": status}}


def _snap(*players):
    return {"name": "get_team_snapshot", "output": {"status": "ok",
            "top_players": [{"web_name": n, "position": pos} for n, pos in players]}}


def _trace(*entries):
    return NS(tool_calls_trace=list(entries), answer_text="")


def test_calendar_calls_and_both_axes_are_read_off_the_trace():
    r = _trace(_cal("attack"), _snap(("Saka", "MID")), _cal("defence"))
    calls = probe.calendar_calls(r)
    assert [c["axis"] for c in calls] == ["attack", "defence"]
    assert probe.both_axes_read(calls) is True


@pytest.mark.parametrize("entries", [
    (_cal("attack"), _cal("attack")),              # twice the same axis
    (_cal("attack"),),                             # one axis
    (_cal("attack"), _cal("defence", status="not_found")),  # defence read failed
    (),
])
def test_both_axes_needs_an_ok_read_on_each_axis(entries):
    assert probe.both_axes_read(probe.calendar_calls(_trace(*entries))) is False


def test_target_gw_ok_needs_every_calendar_call_on_the_phrase_gameweek():
    both = probe.calendar_calls(_trace(_cal("attack"), _cal("defence")))
    assert probe.target_gw_ok(both, 5) is True
    assert probe.target_gw_ok(both, 4) is False
    assert probe.target_gw_ok(both, None) is False
    one_off = probe.calendar_calls(_trace(_cal("attack"), _cal("defence", target_gw=None)))
    assert probe.target_gw_ok(one_off, 5) is False
    assert probe.target_gw_ok([], 5) is False


def test_project_carries_positions_and_the_defensive_names():
    r = _trace(_cal("attack"), _snap(("Saka", "MID"), ("Raya", "GKP"), ("Gabriel", "DEF")), _cal("defence"))
    p = probe.project(r, "Ataque: Saka (xG 2.88). Defensa: Raya (forma 7.2).", expected_gw=5)
    assert p["composed"] is True and p["both_axes"] is True and p["target_gw_ok"] is True
    assert p["snapshot_positions"] == {"Saka": "MID", "Raya": "GKP", "Gabriel": "DEF"}
    assert p["named_real_players"] == ["Saka", "Raya"]
    assert p["named_def_or_gkp"] == ["Raya"]
    assert p["transaction_hits"] == []
    assert [c["axis"] for c in p["calendar_calls"]] == ["attack", "defence"]


def test_project_without_expected_gw_reports_target_gw_ok_false_not_a_crash():
    r = _trace(_cal("attack"), _snap(("Saka", "MID")))
    p = probe.project(r, "Saka")
    assert p["target_gw_ok"] is False and p["both_axes"] is False and p["named_def_or_gkp"] == []


# ---------------------------------------------------------------------------
# Analyzer: full_hit needs both axes on every rep; old rows read as 0
# ---------------------------------------------------------------------------

def _row(qid, players, hits, both_axes, rep, positions=None, composed=True):
    return {"question_id": qid, "rep": rep, "exception": None, "cost_usd": 0.001,
            "i93": {"composed": composed, "named_real_players": players, "transaction_hits": hits,
                    "both_axes": both_axes, "target_gw_ok": both_axes,
                    "snapshot_positions": positions or {},
                    "calendar_calls": ([{"axis": "attack"}, {"axis": "defence"}] if both_axes else [{"axis": "attack"}]),
                    "tool_sequence": ["get_fixture_outlook", "get_team_snapshot"]}}


def test_full_hit_needs_both_axes_on_every_rep():
    s = analyzer.summarize([_row("a", ["Saka"], [], True, r) for r in range(3)])
    assert s["hits"] == 1 and s["full_hits"] == 1 and s["both_axes_reps"] == 3
    s = analyzer.summarize([_row("a", ["Saka"], [], r < 2, r) for r in range(3)])
    assert s["hits"] == 1 and s["full_hits"] == 0 and s["both_axes_reps"] == 2


def test_full_hit_is_split_by_synthetic_dgw_like_hit():
    rows = [_row("real", ["Saka"], [], True, r) for r in range(3)]
    rows += [dict(_row("dgw", ["Saka"], [], True, r), i78a={"dgw_synthetic": True}) for r in range(3)]
    s = analyzer.summarize(rows)
    assert s["real_full_hits"] == 1 and s["synthetic_dgw_full_hits"] == 1


def test_def_named_is_reported_from_the_snapshot_position_never_gated():
    rows = [_row("a", ["Saka", "Raya"], [], True, r, positions={"Saka": "MID", "Raya": "GKP"}) for r in range(3)]
    s = analyzer.summarize(rows)
    assert s["def_named_reps"] == 3 and s["full_hits"] == 1
    rows = [_row("a", ["Saka"], [], True, r, positions={"Saka": "MID"}) for r in range(3)]
    s = analyzer.summarize(rows)
    assert s["def_named_reps"] == 0 and s["full_hits"] == 1   # still a full hit


def test_i93_artifacts_without_calendar_calls_read_as_zero_both_axes():
    root = Path(_PKG) / "field-notes" / "artifacts"
    after = analyzer.summarize(analyzer.load(str(root / "i93-composed-content-after.jsonl")))
    assert after["real_hits"] == 12                    # the i93 read-out is unchanged
    assert after["both_axes_reps"] == 0 and after["full_hits"] == 0 and after["def_named_reps"] == 0


# ---------------------------------------------------------------------------
# Corpus: one phrase per cell, both sides in it
# ---------------------------------------------------------------------------

def test_generated_cell_phrases_ask_both_sides_and_are_one_per_cell():
    cells = corpus.i93_fixture_cell_corpus()
    assert len(cells) == 24
    assert len({e["question"] for e in cells}) == 24
    assert all(e["i78a"]["kind"] == "fixtureCellQuestion" and e["i78a"]["axis"] == "both" for e in cells)
    assert all("ofensivamente y defensivamente" in e["question"] for e in cells)
    assert sum(1 for e in cells if not e["i78a"]["dgw_synthetic"]) == 20
    # The user's example phrase is produced verbatim by the UI function.
    by_id = {e["id"]: e["question"] for e in cells}
    assert by_id["fc-tot-cell-j5"] == "Spurs vs AVL (en casa), J5: ¿qué tal pinta ofensivamente y defensivamente para el Spurs?"
    # The routing matrix keeps its base set; the i101 selector still finds its 16.
    assert len(corpus.i78a_fixture_click_corpus()) == 20
    assert len(corpus.i101_target_gw_corpus(current_gw=1)) == 16
    assert not any(corpus._I101_ID_RE.search(e["id"]) for e in corpus.i78a_fixture_click_corpus())


def test_probe_main_measures_every_cell_and_stamps_the_both_axes_flags(tmp_path, monkeypatch):
    from fpl_grounded_assistant import orchestrator as orch_mod

    def fake_ask(question, bootstrap, **kw):
        team = question.split(" vs ")[0]
        gw = int(question.split(", J")[1].split(":")[0].split(" ")[0])
        r = _trace(_cal("attack", target_gw=gw), _snap(("Saka", "MID"), ("Raya", "GKP")), _cal("defence", target_gw=gw))
        r.answer_text = f"J{gw}: {team}. Ataque: Saka (xG 2.88). Defensa: Raya (forma 7.2)."
        return r

    def fake_run_one(question, rep, bootstrap, api_key):
        orch_mod.ask_orchestrated(question["question"], bootstrap)
        return {"question_id": question["id"], "rep": rep, "exception": None, "cost_usd": 0.001}

    monkeypatch.setattr(base, "run_one", fake_run_one)
    monkeypatch.setattr(orch_mod, "ask_orchestrated", fake_ask)
    bs = tmp_path / "bs.json"
    bs.write_text("{}", encoding="utf-8")
    out = tmp_path / "o.jsonl"
    rc = probe.main(["--bootstrap", str(bs), "--out", str(out), "--reps", "1", "--cap-usd", "5"])
    assert rc == 0
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 24
    for r in rows:
        assert r["i93"]["both_axes"] is True and r["i93"]["target_gw_ok"] is True
        assert r["i93"]["named_def_or_gkp"] == ["Raya"]
        assert r["corpus_sha256"]["description_asks_both_axes"] is True
        assert r["corpus_sha256"]["prompt_has_both_sides"] is True
    s = analyzer.summarize(rows)
    assert s["full_hits"] == 24 and s["target_gw_ok_reps"] == 24 and s["def_named_reps"] == 24


# ---------------------------------------------------------------------------
# Measured refinement (2026-09-16 content run) + the committed artifacts
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.opportunity_framing import transaction_hits  # noqa: E402


@pytest.mark.parametrize("text", [
    "44,58 goles esperados concedidos registrados en su ficha.",
    "la ficha de Haaland dice 3.150 minutos",
    "sus fichas muestran forma 7.0",
])
def test_the_noun_ficha_is_a_record_card_not_a_signing(text):
    assert transaction_hits(text) == []


@pytest.mark.parametrize("text,word", [
    ("el City ficha a Haaland", "ficha"),
    ("la ficha a Haaland", "ficha"),
    ("fichar a Saka", "fichar"),
    ("un fichaje redondo", "fichaje"),
    ("Ficha: Saka", "ficha"),
])
def test_the_verb_and_fichaje_are_still_caught(text, word):
    assert transaction_hits(text) == [f"ficha:{word}"]


def test_readout_recomputes_hits_from_answer_text_with_the_current_matcher():
    row = {"question_id": "a", "rep": 0, "exception": None, "cost_usd": 0.0,
           "answer_text": "registrados en su ficha",
           "i93": {"composed": True, "snapshot_web_names": [], "transaction_hits": ["ficha:ficha"]}}
    assert analyzer.rep_verdict(row)["clean"] is True
    row["answer_text"] = "el City ficha a Haaland"
    assert analyzer.rep_verdict(row)["clean"] is False


def test_readout_on_the_committed_i93b_artifacts():
    root = Path(_PKG) / "field-notes" / "artifacts"
    before = analyzer.summarize(analyzer.load(str(root / "i93b-both-axes-before.jsonl")))
    after = analyzer.summarize(analyzer.load(str(root / "i93b-both-axes-after.jsonl")))
    for s in (before, after):
        assert s["phrases"] == 24 and s["rows"] == 72 and s["exceptions"] == 0
        assert s["real_cells"] == 20 and s["synthetic_dgw_cells"] == 4
        # The gate: the cell tap's answer reads BOTH axes from the tool and
        # names a real player, clean, on >= 8/10 of the real cells.
        assert s["real_full_hits"] * 10 >= s["real_cells"] * 8
        assert s["both_axes_reps"] == 72 and s["target_gw_ok_reps"] == 72
        assert s["transaction_hit_reps"] == 0
    # BEFORE = main's backend (i93) with the new phrase: the phrase alone
    # already makes the model read both axes. AFTER = the i93-b catalog +
    # prompt: what it adds is the defensive side having a real GKP/DEF
    # behind it (reported, not gated) and the synthetic DGW cells.
    assert before["real_full_hits"] == 20 and after["real_full_hits"] == 20
    assert before["def_named_reps"] == 53 and after["def_named_reps"] == 70
    assert before["synthetic_dgw_full_hits"] == 0 and after["synthetic_dgw_full_hits"] == 3
    rows_b = analyzer.load(str(root / "i93b-both-axes-before.jsonl"))
    rows_a = analyzer.load(str(root / "i93b-both-axes-after.jsonl"))
    assert all(r["corpus_sha256"]["description_asks_both_axes"] is False for r in rows_b)
    assert all(r["corpus_sha256"]["description_asks_both_axes"] is True for r in rows_a)
    assert all(r["corpus_sha256"]["prompt_has_both_sides"] is True for r in rows_a)
