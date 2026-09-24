"""i108 E3 -- the chip answer opens GENERAL, then says the PARTICULAR.

What this file pins
-------------------
A. One catalog entry: ``CHIP_ADVICE_SPEC`` is built from
   ``GET_CHIP_ADVICE_SCHEMA`` (name, description, parameters), the
   build_squad_tool precedent; the description says once that a linked team
   is already evaluated by the tool (no get_my_squad first).
B. The prompts (single-shot and loop) carry ``chip_composition_rule()``,
   which asks the model for the BODY only; the header (verdict + favoured
   group) and the closing particular sentence are composed deterministically
   by ``compose_chip_answer`` at the orchestrator's single exit, after the
   i106 guard. Both parts come from ``chip_two_part`` constants, the same the
   grader imports. The phrases obey the framing rule (0 transaction words).
C. ``particular_outcome`` / ``particular_phrase`` map a tool output to the
   one phrase the answer must carry.
D. The gate grader grades from the text against the executed chip output,
   and puts TC / no-chip-call rows apart, never in the denominator.
E. ``measure_tool_routing`` rows carry the chip output from the trace and the
   whole answer (additive; ``answer_text`` keeps its cap).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import fpl_grounded_assistant  # noqa: F401  (tool self-registration)
from fpl_grounded_assistant.chip_advisor import CHIP_ADVICE_SPEC
from fpl_grounded_assistant.chip_two_part import (
    FORBIDDEN_OPENINGS,
    GENERAL_VERDICT_LABEL,
    PARTICULAR_PHRASE,
    chip_composition_rule,
    compose_chip_answer,
    fold,
    last_chip_output,
    particular_outcome,
    particular_phrase,
)
from fpl_grounded_assistant.opportunity_framing import transaction_hits
from fpl_grounded_assistant.orchestrator import _LOOP_SYSTEM_PROMPT, _SYSTEM_PROMPT
from fpl_grounded_assistant.tool_schema_registry import GET_CHIP_ADVICE_SCHEMA

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"_i108e3_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


grader = _load_script("grade_i108_chip_two_parts")


def _chip(**over: Any) -> dict[str, Any]:
    out = {
        "status": "ok",
        "chip": "bench_boost",
        "recommendation": "conditions_favorable",
        "squad_source": "linked_team",
        "squad_fit": {"held": [1, 2], "missing_count": 2, "verdict": "needs_transfers"},
        "linked_squad_error": None,
        "favoured_teams": [{"team": 14, "team_short": "LIV"}],
        "favoured_players": [{"element": 2, "web_name": "Salah"}],
    }
    out.update(over)
    return out


NAMES = {14: ["LIV", "Liverpool"], 1: ["ARS", "Arsenal"]}


def _row(text: str, chip: dict[str, Any] | None, **over: Any) -> dict[str, Any]:
    row = {"question_id": "cvg-10", "rep": 0, "team_id_present": True,
           "answer_text_full": text, "chip_trace": chip}
    row.update(over)
    return row


GOOD = (
    "Bench Boost: jornada favorable. El grupo favorecido es Liverpool (Salah).\n\n"
    "En tu banco: te faltan 2 jugadores del grupo favorecido para sacarle todo al chip."
)


# ---------------------------------------------------------------------------
# A. One catalog entry
# ---------------------------------------------------------------------------

class TestOneCatalogEntry:
    def test_spec_is_built_from_the_schema(self):
        assert CHIP_ADVICE_SPEC.name == GET_CHIP_ADVICE_SCHEMA.name
        assert CHIP_ADVICE_SPEC.description is GET_CHIP_ADVICE_SCHEMA.description
        assert CHIP_ADVICE_SPEC.parameters is GET_CHIP_ADVICE_SCHEMA.parameters

    def test_description_states_the_composition_once(self):
        d = GET_CHIP_ADVICE_SCHEMA.description
        assert "ALREADY evaluates the user's own squad" in d
        assert "no need to call get_my_squad" in d
        assert d.count("get_my_squad") == 1
        assert "squad_fit" in d
        # The build_squad composition stays.
        assert "call build_squad" in d


# ---------------------------------------------------------------------------
# B. One source for the wording
# ---------------------------------------------------------------------------

class TestPromptCarriesTheRule:
    @pytest.mark.parametrize("prompt", [_SYSTEM_PROMPT, _LOOP_SYSTEM_PROMPT], ids=["single", "loop"])
    def test_rule_is_in_both_prompts(self, prompt):
        assert chip_composition_rule() in prompt

    def test_the_prompt_still_closes_with_output_and_keeps_match_composition(self):
        assert _SYSTEM_PROMPT.rstrip().endswith("OUTPUT: terse, structured, action-oriented. Spanish-first.")
        assert "MATCH_COMPOSITION" in _SYSTEM_PROMPT
        assert _SYSTEM_PROMPT.index("MATCH_COMPOSITION") < _SYSTEM_PROMPT.index("CHIP_COMPOSITION")

    def test_the_rule_asks_for_the_body_only(self):
        rule = chip_composition_rule()
        assert "Write ONLY the body" in rule
        assert "Do NOT write a verdict or title line" in rule
        assert "do NOT write anything about" in rule
        assert "do not call get_my_squad" in rule

    def test_the_phrases_obey_the_framing_rule(self):
        for text in list(PARTICULAR_PHRASE.values()) + list(GENERAL_VERDICT_LABEL.values()):
            assert transaction_hits(text) == [], text


# ---------------------------------------------------------------------------
# B2. The deterministic composition
# ---------------------------------------------------------------------------

TEAM_NAMES = {14: "Liverpool", 8: "Chelsea"}


def _tool_output(**over: Any) -> dict[str, Any]:
    """A get_chip_advice output as the tool emits it (signals nested)."""
    out = {
        "status": "ok", "chip": "bench_boost", "recommendation": "conditions_favorable",
        "signals": {
            "favoured_teams": [{"team": 14, "team_short": "LIV", "fdr": 2, "top_player_count": 1},
                               {"team": 8, "team_short": "CHE", "fdr": 2, "top_player_count": 1}],
            "favoured_players": [{"element": 2, "web_name": "Salah"}, {"element": 6, "web_name": "Johnson"}],
        },
        "squad_source": "linked_team",
        "squad_fit": {"held": [2], "missing_count": 3, "verdict": "needs_transfers"},
        "linked_squad_error": None,
    }
    out.update(over)
    return out


class TestComposition:
    def test_header_body_sentence_in_that_order(self):
        text = compose_chip_answer("El calendario es suave.", _tool_output(), TEAM_NAMES)
        header, body, sentence = text.split("\n\n")
        assert header == ("**Bench Boost \u2014 jornada favorable.** "
                          "Grupo favorecido: Liverpool y Chelsea (Salah, Johnson).")
        assert body == "El calendario es suave."
        assert sentence == "Te faltan 3 jugadores del grupo favorecido para sacarle todo al chip."

    def test_composed_text_passes_the_grader(self):
        chip = _tool_output()
        text = compose_chip_answer("Cuerpo cualquiera.", chip, TEAM_NAMES)
        projected = {k: chip[k] for k in ("status", "chip", "recommendation", "squad_source",
                                          "squad_fit", "linked_squad_error")}
        projected["favoured_teams"] = [{"team": t["team"], "team_short": t["team_short"]}
                                       for t in chip["signals"]["favoured_teams"]]
        projected["favoured_players"] = [{"element": p["element"], "web_name": p["web_name"]}
                                         for p in chip["signals"]["favoured_players"]]
        g = grader.grade_row(_row(text, projected), {14: ["LIV", "Liverpool"], 8: ["CHE", "Chelsea"]})
        assert g["pass"] and g["pass_strict_opening"]

    def test_empty_group_header_has_no_group_sentence(self):
        chip = _tool_output(chip="wildcard", recommendation="conditions_marginal", signals={"favoured_teams": []},
                            squad_fit={"held": [], "missing_count": 0, "verdict": "not_applicable"})
        text = compose_chip_answer("x", chip, TEAM_NAMES)
        assert text.startswith("**Wildcard \u2014 jornada a medias.**\n\n")
        assert text.endswith("Esta jornada no es buena para este chip, ni para ti ni para nadie.")

    def test_no_team_gets_the_invitation_and_fetch_failed_never_does(self):
        invite = compose_chip_answer("x", _tool_output(squad_source=None, squad_fit=None), TEAM_NAMES)
        assert invite.endswith("Enlaza tu equipo y te digo si ya tienes el grupo favorecido.")
        failed = compose_chip_answer(
            "x", _tool_output(squad_source=None, squad_fit=None, linked_squad_error="fetch_failed"), TEAM_NAMES)
        assert failed.endswith("No pude cargar tu plantilla.")
        assert "Enlaza" not in failed

    def test_the_sentence_is_not_repeated_when_the_body_has_it(self):
        body = "Ojo: te faltan 3 jugadores del grupo favorecido para sacarle todo al chip."
        text = compose_chip_answer(body, _tool_output(), TEAM_NAMES)
        assert fold(text).count(fold(PARTICULAR_PHRASE["needs_transfers"].format(n=3))) == 1

    @pytest.mark.parametrize("over", [
        {"chip": "triple_captain"},
        {"status": "error"},
        {"recommendation": "missing_context", "squad_fit": None},
    ])
    def test_nothing_is_added_when_nothing_is_computed(self, over):
        assert compose_chip_answer("cuerpo", _tool_output(**over), TEAM_NAMES) == "cuerpo"

    def test_team_falls_back_to_the_short_code(self):
        text = compose_chip_answer("x", _tool_output(), {})
        assert "Grupo favorecido: LIV y CHE" in text

    def test_last_ok_chip_output_is_used(self):
        first = _tool_output(chip="wildcard")
        trace = ({"name": "get_chip_advice", "output": first},
                 {"name": "get_chip_advice", "output": {"status": "error"}},
                 {"name": "get_chip_advice", "output": _tool_output()},
                 {"name": "get_gameweek_context", "output": {"status": "ok"}})
        assert last_chip_output(trace)["chip"] == "bench_boost"
        assert last_chip_output(()) is None


class TestOrchestratorApplies:
    def _result(self, **over: Any):
        from fpl_grounded_assistant.orchestrator import OUTCOME_OK, OrchestratorResult
        base = dict(question="q", tool_chosen="get_chip_advice", tool_args={}, tool_output={},
                    answer_text="Cuerpo del modelo.", llm_used=True, model="m", outcome=OUTCOME_OK,
                    tool_calls_trace=({"name": "get_chip_advice", "output": _tool_output()},))
        base.update(over)
        return OrchestratorResult(**base)

    def test_ok_chip_turn_is_composed_with_bootstrap_team_names(self):
        from fpl_grounded_assistant.orchestrator import _compose_chip_answer
        out = _compose_chip_answer(self._result(), {"teams": [{"id": 14, "name": "Liverpool"},
                                                              {"id": 8, "name": "Chelsea"}]})
        assert out.answer_text.startswith("**Bench Boost \u2014 jornada favorable.** Grupo favorecido: Liverpool y Chelsea")
        assert "\n\nCuerpo del modelo.\n\n" in out.answer_text

    def test_assembled_context_bootstrap_is_unwrapped(self):
        from fpl_grounded_assistant.orchestrator import _compose_chip_answer
        out = _compose_chip_answer(self._result(), {"bootstrap": {"teams": [{"id": 14, "name": "Liverpool"}]}})
        assert "Grupo favorecido: Liverpool y CHE" in out.answer_text

    def test_guarded_or_failed_turns_are_left_alone(self):
        from fpl_grounded_assistant.orchestrator import _compose_chip_answer
        guarded = self._result(final_text_guard_reason="html", answer_text="No se obtuvo respuesta útil.")
        assert _compose_chip_answer(guarded, {}) is guarded
        failed = self._result(outcome="tool_result_error")
        assert _compose_chip_answer(failed, {}) is failed

    def test_turns_without_a_chip_call_are_left_alone(self):
        from fpl_grounded_assistant.orchestrator import _compose_chip_answer
        r = self._result(tool_calls_trace=({"name": "get_gameweek_context", "output": {"status": "ok"}},))
        assert _compose_chip_answer(r, {}) is r

    def test_it_runs_at_the_public_entry_point_after_the_guard(self):
        import inspect
        from fpl_grounded_assistant import orchestrator
        src = inspect.getsource(orchestrator.ask_orchestrated)
        assert src.index("_guard_final_text(result)") < src.index("_compose_chip_answer(result, bootstrap)")


# ---------------------------------------------------------------------------
# C. Which phrase an output calls for
# ---------------------------------------------------------------------------

class TestParticularPhrase:
    @pytest.mark.parametrize("over, outcome, phrase", [
        ({"squad_fit": {"held": [1, 2, 3, 4], "missing_count": 0, "verdict": "set"}}, "set",
         "ya tienes el grupo favorecido"),
        ({}, "needs_transfers", "te faltan 2 jugadores del grupo favorecido para sacarle todo al chip"),
        ({"squad_fit": {"held": [], "missing_count": 0, "verdict": "not_applicable"}}, "not_applicable",
         PARTICULAR_PHRASE["not_applicable"]),
        ({"squad_source": None, "squad_fit": None}, "invite", PARTICULAR_PHRASE["invite"]),
        ({"squad_source": None, "squad_fit": None, "linked_squad_error": "fetch_failed"}, "fetch_failed",
         "no pude cargar tu plantilla"),
    ])
    def test_each_outcome(self, over, outcome, phrase):
        chip = _chip(**over)
        assert particular_outcome(chip) == outcome
        assert particular_phrase(chip) == phrase

    def test_fetch_failed_is_never_the_invitation(self):
        chip = _chip(squad_source=None, squad_fit=None, linked_squad_error="fetch_failed")
        assert particular_phrase(chip) != PARTICULAR_PHRASE["invite"]

    @pytest.mark.parametrize("over", [
        {"chip": "triple_captain"},
        {"status": "error"},
        {"squad_fit": None},             # members known, no fit computable
    ])
    def test_no_particular_part_expected(self, over):
        assert particular_outcome(_chip(**over)) is None
        assert particular_phrase(_chip(**over)) is None


# ---------------------------------------------------------------------------
# D. The grader
# ---------------------------------------------------------------------------

class TestGrader:
    def test_a_two_part_answer_passes(self):
        g = grader.grade_row(_row(GOOD, _chip()), NAMES)
        assert g["bucket"] == "denominator"
        assert (g["part1"], g["part2"], g["order"], g["pass"]) == (True, True, True, True)

    def test_matching_ignores_accents_case_and_guillemets(self):
        text = GOOD.replace("jornada favorable", "«JORNADA FAVORABLE»").replace("sacarle", "sacárle")
        assert grader.grade_row(_row(text, _chip()), NAMES)["pass"]

    def test_missing_particular_fails_part2(self):
        text = GOOD.split("\n\n")[0]
        g = grader.grade_row(_row(text, _chip()), NAMES)
        assert (g["part1"], g["part2"], g["pass"]) == (True, False, False)

    def test_the_wrong_number_is_not_the_phrase(self):
        text = GOOD.replace("te faltan 2 jugadores", "te faltan 3 jugadores")
        assert grader.grade_row(_row(text, _chip()), NAMES)["part2"] is False

    def test_particular_first_fails_order_and_part1(self):
        text = ("Te faltan 2 jugadores del grupo favorecido para sacarle todo al chip.\n\n"
                "Bench Boost: jornada favorable, grupo favorecido Liverpool.")
        g = grader.grade_row(_row(text, _chip()), NAMES)
        assert g["order"] is False and g["part1"] is False and g["pass"] is False

    def test_particular_before_verdict_in_one_paragraph_fails_on_order_alone(self):
        text = ("Liverpool: te faltan 2 jugadores del grupo favorecido para sacarle todo al chip. "
                "Bench Boost: jornada favorable.")
        g = grader.grade_row(_row(text, _chip()), NAMES)
        assert (g["part1"], g["part2"], g["order"], g["pass"]) == (True, True, False, False)

    def test_the_verdict_must_open_the_answer(self):
        text = ("Liverpool y Salah llegan en forma.\n\n"
                "Bench Boost: jornada favorable. Te faltan 2 jugadores del grupo favorecido para sacarle todo al chip.")
        g = grader.grade_row(_row(text, _chip()), NAMES)
        assert (g["part1"], g["part2"], g["order"]) == (False, True, True)

    def test_the_group_must_be_named_before_the_particular(self):
        text = ("Bench Boost: jornada favorable.\n\n"
                "Te faltan 2 jugadores del grupo favorecido para sacarle todo al chip. Liverpool juega fácil.")
        assert grader.grade_row(_row(text, _chip()), NAMES)["part1"] is False

    def test_a_team_counts_by_full_name_resolved_from_the_id(self):
        text = GOOD.replace("Liverpool (Salah)", "Liverpool")
        chip = _chip(favoured_players=[])
        assert grader.grade_row(_row(text, chip), NAMES)["pass"]

    def test_empty_group_needs_no_name(self):
        chip = _chip(recommendation="conditions_unfavorable", favoured_teams=[], favoured_players=[],
                     squad_fit={"held": [], "missing_count": 0, "verdict": "not_applicable"})
        text = ("Wildcard: jornada poco favorable.\n\n"
                "Esta jornada no es buena para este chip, ni para ti ni para nadie.")
        assert grader.grade_row(_row(text, chip), NAMES)["pass"]

    def test_the_wrong_verdict_label_fails_part1(self):
        text = GOOD.replace("jornada favorable", "jornada poco favorable")
        assert grader.grade_row(_row(text, _chip()), NAMES)["part1"] is False

    @pytest.mark.parametrize("chip, bucket", [
        (None, "no_chip_call"),
        (_chip(chip="triple_captain"), "chip_triple_captain"),
        (_chip(status="error"), "chip_not_ok"),
        (_chip(squad_fit=None), "no_fit_computable"),
    ])
    def test_rows_outside_the_denominator_are_bucketed_not_failed(self, chip, bucket):
        g = grader.grade_row(_row("cualquier texto", chip), NAMES)
        assert g["bucket"] == bucket
        assert "pass" not in g

    def test_forbidden_opening_and_transaction_words_are_flagged(self):
        text = "No puedo evaluar tu equipo. Deberías fichar a Salah."
        g = grader.grade_row(_row(text, None), NAMES)
        assert g["forbidden_opening"] is True
        assert g["transaction_hits"]

    def test_summary_gate_uses_the_denominator_only(self):
        graded = [
            grader.grade_row(_row(GOOD, _chip()), NAMES),
            grader.grade_row(_row("x", None), NAMES),
            grader.grade_row(_row("x", _chip(chip="triple_captain")), NAMES),
        ]
        s = grader.summarize(graded, 0.95)
        assert (s["rows"], s["denominator"], s["pass"], s["gate"]) == (3, 1, 1, True)
        assert s["apart"] == {"no_chip_call": 1, "chip_triple_captain": 1}

    def test_a_heading_then_the_verdict_opens_with_the_verdict(self):
        # Seen on the first measured rows: "## Wildcard — GW1" then the verdict.
        text = ("## Bench Boost — GW2\n\n**Jornada favorable.** Grupo favorecido: Liverpool.\n\n"
                "Te faltan 2 jugadores del grupo favorecido para sacarle todo al chip.")
        g = grader.grade_row(_row(text, _chip()), NAMES)
        assert g["pass"] is True
        assert g["pass_strict_opening"] is False    # the pre-fix definition, reported apart

    def test_a_heading_alone_is_not_the_opening_paragraph(self):
        text = ("## Bench Boost\n\nLiverpool llega bien.\n\n"
                "Jornada favorable. Te faltan 2 jugadores del grupo favorecido para sacarle todo al chip.")
        assert grader.grade_row(_row(text, _chip()), NAMES)["part1"] is False

    def test_transaction_words_are_counted_on_chip_answers_and_apart(self):
        graded = [
            grader.grade_row(_row(GOOD + " Deberías fichar.", _chip()), NAMES),
            grader.grade_row(_row("¿Hago un transfer?", None), NAMES),
        ]
        s = grader.summarize(graded, 0.95)
        assert (s["transaction_hit_rows"], s["transaction_hit_rows_apart"]) == (1, 1)

    def test_forbidden_openings_constant_is_what_the_rule_forbids(self):
        assert fold(FORBIDDEN_OPENINGS[0]) in fold(chip_composition_rule())


# ---------------------------------------------------------------------------
# E. The measurement row
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def measure():
    return _load_script("measure_tool_routing")


class TestMeasureRow:
    def test_chip_trace_is_the_last_chip_output_projected(self, measure):
        first = {"status": "ok", "chip": "wildcard", "recommendation": "conditions_marginal",
                 "signals": {}, "squad_source": None, "squad_fit": None, "linked_squad_error": None}
        last = {"status": "ok", "chip": "bench_boost", "recommendation": "conditions_favorable",
                "signals": {"favoured_teams": [{"team": 14, "team_short": "LIV", "fdr": 2}],
                            "favoured_players": [{"element": 2, "web_name": "Salah", "fdr": 2}],
                            "average_fdr_top10": 2.1},
                "squad_source": "linked_team",
                "squad_fit": {"held": [2], "missing_count": 3, "verdict": "needs_transfers"},
                "linked_squad_error": None, "advice_text": "long"}
        result = SimpleNamespace(tool_calls_trace=(
            {"name": "get_chip_advice", "output": first},
            {"name": "get_my_squad", "output": {"status": "ok"}},
            {"name": "get_chip_advice", "output": last},
        ))
        projected = measure.extract_chip_trace(result)
        assert projected == {
            "status": "ok", "chip": "bench_boost", "recommendation": "conditions_favorable",
            "squad_source": "linked_team",
            "squad_fit": {"held": [2], "missing_count": 3, "verdict": "needs_transfers"},
            "linked_squad_error": None,
            "favoured_teams": [{"team": 14, "team_short": "LIV"}],
            "favoured_players": [{"element": 2, "web_name": "Salah"}],
        }

    def test_no_chip_call_is_none(self, measure):
        result = SimpleNamespace(tool_calls_trace=({"name": "get_gameweek_context", "output": {}},))
        assert measure.extract_chip_trace(result) is None
        assert measure.extract_chip_trace(SimpleNamespace()) is None

    def test_run_one_rows_carry_the_new_fields_on_success_and_on_exception(self, measure, monkeypatch):
        import fpl_grounded_assistant.orchestrator as orch

        long_text = "Bench Boost: jornada favorable. " + "x" * 600
        fake = SimpleNamespace(
            outcome="ok", tool_chosen="get_chip_advice", tool_call_count=1, tool_args={"chip": "bench_boost"},
            tool_output={"status": "ok"}, synthesis_turn=True, answer_text=long_text, rounds_used=1,
            error=None, primary_input_tokens=0, primary_output_tokens=0, primary_cache_read_tokens=0,
            total_tokens=0,
            tool_calls_trace=({"name": "get_chip_advice", "output": {"status": "ok", "chip": "bench_boost", "signals": {}}},),
        )
        monkeypatch.setattr(orch, "ask_orchestrated", lambda *a, **k: fake)
        q = {"id": "cvg-10", "family": "chip", "acceptable_tools": ["get_chip_advice"], "control": False,
             "question": "Fecha 2: ¿bench boost sí o no?"}
        row = measure.run_one(q, 0, {}, "k")
        assert row["answer_text_full"] == long_text
        assert len(row["answer_text"]) == 400
        assert row["chip_trace"]["chip"] == "bench_boost"

        def boom(*a, **k):
            raise RuntimeError("down")
        monkeypatch.setattr(orch, "ask_orchestrated", boom)
        row = measure.run_one(q, 0, {}, "k")
        assert row["answer_text_full"] == "" and row["chip_trace"] is None


# ---------------------------------------------------------------------------
# F. The squad fields never reach the model (the system writes that part)
# ---------------------------------------------------------------------------

_HIDDEN = {"squad_fit", "squad_source", "linked_squad_error"}


class TestSquadFieldsHiddenFromTheModel:
    def test_truncated_payload_drops_them_and_the_real_output_keeps_them(self):
        from fpl_grounded_assistant.orchestrator import _truncate_tool_output
        raw = _tool_output()
        payload = _truncate_tool_output(raw, tool_name="get_chip_advice")
        assert not (_HIDDEN & set(payload))
        assert _HIDDEN <= set(raw)                      # the real output is untouched
        assert payload["signals"] == raw["signals"]     # the general part still reaches it

    @pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
    def test_every_provider_follow_up_serialises_the_filtered_payload(self, provider):
        import json
        from fpl_grounded_assistant.orchestrator import _build_multi_tool_follow_up
        raw = _tool_output()
        response = SimpleNamespace(output=[], content=[], candidates=[SimpleNamespace(content=None)])
        try:
            follow_up = _build_multi_tool_follow_up(provider, [], response,
                                                    [("call_1", "get_chip_advice", {}, raw)])
        except Exception as exc:  # pragma: no cover - provider SDK shape
            pytest.skip(f"{provider} follow-up needs its SDK objects: {exc!r}")
        blob = json.dumps(follow_up, default=repr)
        for key in _HIDDEN:
            assert f'"{key}"' not in blob and f"'{key}'" not in blob, (provider, key)
        assert "favoured_teams" in blob
        assert _HIDDEN <= set(raw)

    def test_other_tools_keep_their_squad_source(self):
        # rank_captain_candidates emits its own squad_source, which the model reads.
        from fpl_grounded_assistant.orchestrator import _truncate_tool_output
        payload = _truncate_tool_output({"status": "ok", "squad_source": "not_connected"},
                                        tool_name="rank_captain_candidates")
        assert payload["squad_source"] == "not_connected"
