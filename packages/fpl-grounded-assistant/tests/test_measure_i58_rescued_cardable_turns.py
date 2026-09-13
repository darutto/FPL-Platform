"""measure_i58_rescued_cardable_turns: the count is read from disk, the cap
is enforced in the loop, and nothing here can reach a provider.

Every test runs under an autouse fixture that (1) snapshots and restores the
module globals ``main()`` reads (PROVIDER/MODEL and the corpus), (2) replaces
``run_one`` -- the only function that makes a paid call -- with a raiser, and
(3) no-ops the .env loader so a developer's key never reaches the script. A
test that wants ``main()`` to "run" installs its own stub over the raiser.
This is the PR #212 lesson: a probe-script test once made ~40 real calls
through module globals another test had left mutated.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parent.parent
_SCRIPTS = _PKG / "scripts"
for _p in (str(_PKG), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import measure_tool_routing as base  # noqa: E402
import measure_i46_synthesis_instrument as inst  # noqa: E402
import measure_i58_rescued_cardable_turns as m  # noqa: E402

CARDABLE = "rank_players_by_metric"
OTHER = "get_player_snapshot"


@pytest.fixture(autouse=True)
def no_paid_calls(monkeypatch):
    def _forbidden(*args, **kwargs):
        raise AssertionError(
            "run_one reached: no test in this module may make a provider call"
        )

    for mod in (m, inst, base):
        monkeypatch.setattr(mod, "PROVIDER", mod.PROVIDER)
        monkeypatch.setattr(mod, "MODEL", mod.MODEL)
    monkeypatch.setattr(m, "CORPUS", list(m.CORPUS))
    monkeypatch.setattr(m, "run_one", _forbidden)
    monkeypatch.setattr(base, "run_one", _forbidden)
    monkeypatch.setattr(inst, "run_one", _forbidden)
    monkeypatch.setattr(base, "_load_env_file", lambda path: None)
    monkeypatch.setattr(base, "_configure_imports", lambda: None)
    # The provider-event check aborts on an empty capture; a stubbed run has
    # no events, so it is neutralised here and re-asserted in its own test.
    monkeypatch.setattr(m, "verify_provider", lambda events, provider, model: None)
    for var in ("OPENAI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def _row(qid: str, rep: int, *, count: int, seq: list[str], cardable: bool,
         chosen: str = CARDABLE, cost: float = 0.005, exception=None) -> dict:
    from fpl_grounded_assistant.atomic_tool_cards import is_single_distinct_tool_turn
    single = is_single_distinct_tool_turn(chosen, count, seq)
    return {
        "question_id": qid, "rep": rep, "tool_chosen": chosen,
        "tool_sequence": seq, "tool_call_count": count, "cardable": cardable,
        "single_distinct_tool": single,
        "would_card_old": count == 1 and cardable,
        "would_card_new": single and cardable,
        "rescued_cardable": count == 2 and cardable and single,
        "count2_cardable_multi_tool": count == 2 and cardable and not single,
        "extra_round_fired": count >= 2, "synthesis_turn": True,
        "cost_usd": cost, "exception": exception,
    }


def _write(path: Path, rows: list[dict], header: dict | None = None,
           trailer: dict | None = None) -> None:
    with path.open("w", encoding="utf-8") as fh:
        if header is not None:
            fh.write(json.dumps({"_header": header}) + "\n")
        for r in rows:
            fh.write(json.dumps(r) + "\n")
        if trailer is not None:
            fh.write(json.dumps(trailer) + "\n")


# --------------------------------------------------------------------------
# summarise() counts from the file
# --------------------------------------------------------------------------

def test_summarise_counts_rescued_cardable_from_disk(tmp_path, capsys):
    path = tmp_path / "obs.jsonl"
    rows = [
        _row("i46-p03", 0, count=1, seq=[CARDABLE], cardable=True),             # old + new card
        _row("i46-p03", 1, count=2, seq=[CARDABLE, CARDABLE], cardable=True),   # RESCUED
        _row("i46-p10", 0, count=2, seq=[CARDABLE, OTHER], cardable=True),      # refused: multi-tool
        _row("i46-p10", 1, count=2, seq=[CARDABLE, CARDABLE], cardable=False),  # one tool, not cardable
        _row("i46-p50", 0, count=2, seq=[CARDABLE, CARDABLE], cardable=True),   # RESCUED
        _row("i46-p50", 1, count=1, seq=[CARDABLE], cardable=True, cost=0.0,
             exception="RuntimeError('x')"),                                   # excepted: not scored
    ]
    _write(path, rows, header={"provider": "openai", "model": "gpt-5.6-luna",
                               "max_tokens": 1024, "reps": 2},
           trailer={"_stopped_by_cap": {"calls_done": 6, "spend_usd": 0.025}})

    summary = m.summarise(path)
    total = summary["total"]
    assert total["observations"] == 6          # the _stopped_by_cap row is not one
    assert total["exceptions"] == 1
    assert total["scored"] == 5
    assert total["rescued_cardable"] == 2
    assert total["count2_cardable_multi_tool"] == 1
    assert total["would_card_old"] == 1
    assert total["would_card_new"] == 3
    assert total["spend_usd"] == pytest.approx(0.025)
    assert summary["by_question"]["i46-p10"]["rescued_cardable"] == 0
    assert summary["by_question"]["i46-p50"]["rescued_cardable"] == 1
    out = capsys.readouterr().out
    assert "RESCUED CARDABLE TURNS (count==2, one distinct tool, cardable output): 2 / 5" in out


def test_classify_uses_product_predicates():
    """The row fields come from atomic_tool_cards, not a re-typed rule."""
    from fpl_grounded_assistant.orchestrator import OrchestratorResult, OUTCOME_OK

    def _res(count, names, output):
        return OrchestratorResult(
            question="q", tool_chosen=CARDABLE, tool_args={}, tool_output=output,
            answer_text="t", llm_used=True, model="m", outcome=OUTCOME_OK,
            tool_call_count=count,
            tool_calls_trace=tuple({"name": n, "args": {}, "output": {}} for n in names),
        )

    ranked = {"status": "ok", "metric": "form", "top_n": 1, "ranked": [
        {"rank": 1, "web_name": "P", "team_short": "MCI", "position": "FWD", "metric_value": 1.0},
    ]}
    rescued = m._classify(_res(2, [CARDABLE, CARDABLE], ranked))
    assert rescued["rescued_cardable"] is True
    assert rescued["would_card_old"] is False and rescued["would_card_new"] is True
    assert rescued["tool_sequence"] == [CARDABLE, CARDABLE]
    assert rescued["distinct_tools"] == [CARDABLE]

    multi = m._classify(_res(2, [CARDABLE, OTHER], ranked))
    assert multi["rescued_cardable"] is False
    assert multi["count2_cardable_multi_tool"] is True

    not_cardable = m._classify(_res(2, [CARDABLE, CARDABLE], {"status": "invalid_argument"}))
    assert not_cardable["cardable"] is False and not_cardable["rescued_cardable"] is False


# --------------------------------------------------------------------------
# main(): key gate, cap, and the number read back from the file
# --------------------------------------------------------------------------

def test_main_aborts_without_key_before_any_call(tmp_path, capsys):
    rc = m.main(["--out", str(tmp_path / "o.jsonl"), "--yes",
                 "--bootstrap", str(tmp_path / "missing.json")])
    assert rc == 2
    assert "OPENAI_API_KEY not set" in capsys.readouterr().err
    assert not (tmp_path / "o.jsonl").exists()


def test_main_summarise_only_makes_no_call(tmp_path):
    path = tmp_path / "obs.jsonl"
    _write(path, [_row("i46-p03", 0, count=2, seq=[CARDABLE, CARDABLE], cardable=True)])
    assert m.main(["--summarise-only", str(path)]) == 0


def test_main_writes_rows_and_reports_the_count_from_the_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    boot = tmp_path / "boot.json"
    boot.write_text("{}", encoding="utf-8")
    out = tmp_path / "o.jsonl"

    calls: list[tuple[str, int]] = []

    def _stub(question, rep, bootstrap, api_key, max_tokens=m.MAX_TOKENS):
        calls.append((question["id"], rep))
        count = 2 if question["id"] == "i46-p50" else 1
        return _row(question["id"], rep, count=count, seq=[CARDABLE] * count, cardable=True)

    monkeypatch.setattr(m, "run_one", _stub)
    rc = m.main(["--out", str(out), "--yes", "--reps", "2", "--bootstrap", str(boot)])
    assert rc == 0
    # Rep-major, fixed order: every arm once per rep.
    assert calls == [("i46-p03", 0), ("i46-p10", 0), ("i46-p50", 0),
                     ("i46-p03", 1), ("i46-p10", 1), ("i46-p50", 1)]
    header, rows = m.read_jsonl(out)
    assert header["corpus"] == ["i46-p03", "i46-p10", "i46-p50"]
    assert "gw-04" in header["excluded_cases"]
    assert header["max_tokens"] == inst.PROD_MAX_TOKENS
    assert len(rows) == 6
    assert sum(1 for r in rows if r["rescued_cardable"]) == 2
    assert "RESCUED CARDABLE TURNS (count==2, one distinct tool, cardable output): 2 / 6" \
        in capsys.readouterr().out


def test_main_spend_cap_stops_the_loop(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    boot = tmp_path / "boot.json"
    boot.write_text("{}", encoding="utf-8")
    out = tmp_path / "o.jsonl"
    n = {"calls": 0}

    def _stub(question, rep, bootstrap, api_key, max_tokens=m.MAX_TOKENS):
        n["calls"] += 1
        return _row(question["id"], rep, count=1, seq=[CARDABLE], cardable=True, cost=0.04)

    monkeypatch.setattr(m, "run_one", _stub)
    # 3 arms x 10 reps = 30 planned at ~$0.0044 est ($0.13 < cap $0.10? no --
    # so use a cap the estimate clears but the real cost crosses).
    rc = m.main(["--out", str(out), "--yes", "--reps", "10", "--bootstrap", str(boot),
                 "--max-spend-usd", "0.15"])
    assert rc == 0
    # 0.04 per call: after 3 calls spend=0.12; 0.12 + 0.0044 < 0.15 -> a 4th
    # call runs (0.16); 0.16 + 0.0044 > 0.15 -> stop. Never 30.
    assert n["calls"] == 4
    assert "STOPPED by spend cap after 4/30 calls" in capsys.readouterr().err
    header, rows = m.read_jsonl(out)
    assert len(rows) == 4


def test_main_refuses_when_estimate_exceeds_cap(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    boot = tmp_path / "boot.json"
    boot.write_text("{}", encoding="utf-8")
    rc = m.main(["--out", str(tmp_path / "o.jsonl"), "--yes", "--reps", "1000",
                 "--bootstrap", str(boot), "--max-spend-usd", "2.0"])
    assert rc == 2
    assert "Estimate exceeds the cap" in capsys.readouterr().err
    assert not (tmp_path / "o.jsonl").exists()


def test_provider_verification_is_the_instruments(monkeypatch):
    """Restore the real check and prove it aborts on an empty capture."""
    monkeypatch.setattr(m, "verify_provider", inst._verify_provider)
    with pytest.raises(SystemExit):
        m.verify_provider([], m.PROVIDER, m.MODEL)
    with pytest.raises(SystemExit):
        m.verify_provider([{"provider": "gemini", "model": "x"}], m.PROVIDER, m.MODEL)
    m.verify_provider([{"provider": "openai", "model": "gpt-5.6-luna"}], m.PROVIDER, m.MODEL)


def test_pinned_pair_is_the_production_pair():
    assert (m.PROVIDER, m.MODEL) == ("openai", "gpt-5.6-luna")
    assert m.MAX_TOKENS == 1024
