"""
i106 -- nothing the user cannot read reaches them as the answer.

Production, 2026-09-19: two turns shipped raw payloads as ``final_text`` --
the literal render of a failed web_fetch ("Error (fetch_failed): URL can't
contain control characters. '/en/clubs/ Nottingham-Forest/fixtures'") and a
4 KB HTML page ("Obtenido https://www.bbc.com/... (4111 bytes).\\n<!DOCTYPE
html>..."). Four terminal sites in the orchestrator let a render() be the
last word and the synthesis itself can quote HTML back, so the guard lives
at the ONE choke point every OrchestratorResult passes through
(``orchestrator.ask_orchestrated`` -> ``_guard_final_text``).

Rule (decided in review, not by the builder): raw is what a user cannot
read -- a transport/infra code (``TRANSPORT_CODES``) or an error message
carrying a URL / traceback / control characters / HTML, an HTML document, a
web_fetch dump. A readable catalogue error ("Error (not_found): ...") is the
hint the user needs and passes intact: that is the explicit negative here.

Five routes, one test each, both prod fixtures where the route can carry
them, fake Anthropic-shaped clients only (no network). Every assertion reads
the produced ``answer_text`` / ``guarded_raw_answer_text`` / the written
NDJSON line / the HTTP body -- never the fixture that requested it.
"""
from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

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
    os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

from fpl_grounded_assistant import audit as audit_mod  # noqa: E402
from fpl_grounded_assistant import orchestrator as orch_mod  # noqa: E402
from fpl_grounded_assistant.catalogue import t  # noqa: E402
from fpl_grounded_assistant.evaluator import EvaluatorVerdict  # noqa: E402
from fpl_grounded_assistant.final_text_guard import (  # noqa: E402
    GUARD_REASONS,
    REASON_HTML_DENSE,
    REASON_HTML_DOCUMENT,
    REASON_TRANSPORT_ERROR,
    REASON_UNREADABLE_ERROR,
    REASON_WEB_FETCH_RENDER,
    TRANSPORT_CODES,
    looks_like_raw_payload,
)
from fpl_grounded_assistant.orchestrator import OrchestratorResult, ask_orchestrated  # noqa: E402
from fpl_grounded_assistant.renderer import render  # noqa: E402

# ---------------------------------------------------------------------------
# The two prod fixtures (2026-09-19), literal shapes
# ---------------------------------------------------------------------------

FETCH_FAILED_TEXT = (
    "Error (fetch_failed): URL can't contain control characters. "
    "'/en/clubs/ Nottingham-Forest/fixtures' (found at least ' ')"
)


def _bbc_html(total: int = 4111) -> str:
    head = (
        "Obtenido https://www.bbc.com/sport/football/premier-league (4111 bytes).\n"
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>Premier League - BBC Sport</title><link rel=\"stylesheet\" href=\"/s.css\">"
        "</head><body><div id=\"root\"><nav class=\"gs-u-display-none\"><ul>"
    )
    filler = "<li><a href=\"/sport/football/teams/x\">Team</a></li>"
    body = head
    while len(body) < total - 60:
        body += filler
    return body + "</ul></nav></div><script>window.__x=1</script></body></html>"


BBC_HTML_TEXT = _bbc_html()
READABLE_NOT_FOUND = "Error (not_found): No encontré ningún jugador que coincida con 'Xavi'."
HONEST_PREFIX = "No obtuve una respuesta útil"


@pytest.fixture(autouse=True)
def _no_loop_by_default(monkeypatch):
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    monkeypatch.delenv("FPL_ORCH_MAX_ROUNDS", raising=False)
    monkeypatch.setenv("FPL_ORCH_MAX_RETRIES", "0")


# ---------------------------------------------------------------------------
# The classifier
# ---------------------------------------------------------------------------

def test_prod_fetch_failed_fixture_fires_by_code():
    assert looks_like_raw_payload(FETCH_FAILED_TEXT) == REASON_TRANSPORT_ERROR


def test_prod_fetch_failed_fixture_fires_by_code_only():
    """Measured, not assumed: urllib's "control characters" in the prod turn
    was a SPACE (``found at least ' '``), so the message carries no control
    byte, URL, traceback or tag -- with a readable code it would pass. The
    transport code is the one way in for this fixture; the content route is
    pinned below with a real control byte."""
    swapped = FETCH_FAILED_TEXT.replace("fetch_failed", "not_found")
    assert looks_like_raw_payload(swapped) is None
    with_control_byte = swapped.replace("' '", "'" + chr(0x1F) + "'")
    assert looks_like_raw_payload(with_control_byte) == REASON_UNREADABLE_ERROR


def test_prod_html_fixture_fires():
    assert len(BBC_HTML_TEXT) >= 4000
    assert looks_like_raw_payload(BBC_HTML_TEXT) == REASON_HTML_DOCUMENT


def test_web_fetch_header_fires_even_without_document_opener():
    assert looks_like_raw_payload("Obtenido https://x.com/a (12 bytes).\nhello") == REASON_WEB_FETCH_RENDER


def test_readable_catalogue_error_passes_intact():
    """The explicit negative: a readable tool error is the hint the user needs."""
    assert looks_like_raw_payload(READABLE_NOT_FOUND) is None
    assert looks_like_raw_payload(
        "Error (unknown_metric): Metric 'xx' not recognized. Try: goals, assists, xg"
    ) is None
    assert looks_like_raw_payload("Error (missing_argument): falta el nombre del jugador.") is None


@pytest.mark.parametrize("code", sorted(TRANSPORT_CODES))
def test_every_transport_code_fires(code):
    assert looks_like_raw_payload(f"Error ({code}): whatever the tool said") == REASON_TRANSPORT_ERROR


def test_not_found_is_not_a_transport_code():
    """Mutation pin: putting not_found in the denylist kills this."""
    assert "not_found" not in TRANSPORT_CODES
    assert "unknown_metric" not in TRANSPORT_CODES
    assert "missing_argument" not in TRANSPORT_CODES


@pytest.mark.parametrize("message", [
    "see https://example.com/help",
    "Traceback (most recent call last): ...",
    "bad byte \x07 here",
    "the page said <div class='x'>no</div>",
])
def test_unreadable_content_fires_with_any_code(message):
    assert looks_like_raw_payload(f"Error (invalid_argument): {message}") == REASON_UNREADABLE_ERROR


def test_bare_error_colon_form_needs_unreadable_content():
    assert looks_like_raw_payload("Error: la jornada 99 no existe.") is None
    assert looks_like_raw_payload("Error: fetch https://x.y failed") == REASON_UNREADABLE_ERROR


def test_wrappers_are_looked_under():
    notice = t("orchestrator.raw_render_notice", "es")
    assert looks_like_raw_payload(f"{notice}\n\n{FETCH_FAILED_TEXT}") == REASON_TRANSPORT_ERROR
    assert looks_like_raw_payload(f"Respuesta incompleta (round cap): {FETCH_FAILED_TEXT}") == REASON_TRANSPORT_ERROR
    assert looks_like_raw_payload(f"Respuesta incompleta (round cap): {READABLE_NOT_FOUND}") is None
    assert looks_like_raw_payload(f"{notice}\n\nJornada actual: GW5 (in_progress).") is None


def test_dense_html_fires_only_when_long_and_tag_heavy():
    short = "Calendario: <b>fácil</b> y <i>corto</i>."
    assert looks_like_raw_payload(short) is None
    dense = "<div><span>x</span></div>" * 40
    assert len(dense) >= 400 and "<html" not in dense
    assert looks_like_raw_payload(dense) == REASON_HTML_DENSE
    prose_with_markup = ("Un párrafo largo de análisis del calendario del Newcastle. " * 12) + "<b>ok</b> " * 9
    assert looks_like_raw_payload(prose_with_markup) is None


def test_reasons_are_closed_and_empty_text_is_not_a_payload():
    assert GUARD_REASONS == {
        REASON_TRANSPORT_ERROR, REASON_UNREADABLE_ERROR, REASON_HTML_DOCUMENT,
        REASON_WEB_FETCH_RENDER, REASON_HTML_DENSE,
    }
    assert looks_like_raw_payload("") is None
    assert looks_like_raw_payload(None) is None


# ---------------------------------------------------------------------------
# Clean text passes the choke point untouched: 5 most-used renders + synthesis
# ---------------------------------------------------------------------------

_CLEAN_RENDERS = [
    ("get_current_gameweek", {"status": "ok", "current_gw": 5, "current_state": "in_progress",
                              "next_gw": 6, "next_deadline_utc": "2026-09-27T10:00:00Z"}),
    ("get_player_snapshot", {"status": "not_found", "code": "not_found", "message": "No encontré a 'Xavi'."}),
    ("rank_players_by_metric", {"status": "error", "code": "unknown_metric",
                                "message": "Metric 'xx' not recognized. Try: goals"}),
    ("get_chip_advice", {"status": "error", "code": "missing_argument", "message": "Falta el chip."}),
    ("web_fetch", {"status": "refused", "message": "URL rechazada por la lista de dominios permitidos."}),
]


@pytest.mark.parametrize("tool, output", _CLEAN_RENDERS, ids=[r[0] for r in _CLEAN_RENDERS])
def test_clean_render_passes_choke_point_untouched(tool, output):
    text = render(tool, output)
    r = OrchestratorResult(question="q", tool_chosen=tool, tool_args={}, tool_output=output,
                           answer_text=text, llm_used=True, model="m", outcome="ok")
    g = orch_mod._guard_final_text(r)
    assert g.answer_text == text
    assert g.final_text_guard_reason is None
    assert g.guarded_raw_answer_text is None


def test_clean_synthesis_passes_choke_point_untouched():
    text = "## Newcastle — J6\n\nBuen calendario ofensivo: **Hull (FDR 2)** y Coventry (FDR 2)."
    r = OrchestratorResult(question="q", tool_chosen="get_fixture_outlook", tool_args={}, tool_output={"status": "ok"},
                           answer_text=text, llm_used=True, model="m", outcome="ok", synthesis_turn=True)
    g = orch_mod._guard_final_text(r)
    assert g is r


# ---------------------------------------------------------------------------
# The five exit routes, through ask_orchestrated with fake clients
# ---------------------------------------------------------------------------

def _tool_use(cid: str = "c1") -> NS:
    return NS(content=[NS(type="tool_use", id=cid, name="get_current_gameweek", input={})])


class _SeqClient:
    def __init__(self, responses):
        self.messages = self
        self.queue = list(responses)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return self.queue.pop(0) if self.queue else _tool_use(f"c{self.calls}")


def _raw_render(text: str):
    """Make render() emit the prod payload for whatever tool ran, so the
    route under test is the one that carries it; tool_output stays real."""
    return patch.object(orch_mod, "render", lambda *a, **k: text)


def _assert_guarded(result: OrchestratorResult, raw: str, reason: str, *, expected_outcome: str):
    assert result.answer_text.startswith(HONEST_PREFIX), result.answer_text
    assert "get_current_gameweek" in result.answer_text
    assert raw[:40] not in result.answer_text
    assert result.final_text_guard_reason == reason
    assert result.guarded_raw_answer_text == raw
    assert result.outcome == expected_outcome


def _assert_raw_output_intact(result: OrchestratorResult):
    # Routes (1)-(4): the tool's own output dict and the trace are untouched.
    assert result.tool_output.get("status") == "ok"
    assert result.tool_output.get("gameweek") is not None
    assert result.tool_calls_trace and result.tool_calls_trace[-1]["output"] is not None


def _reject(monkeypatch):
    verdict = EvaluatorVerdict(approved=False, grounded=True, complete=False, safe=True,
                               retry_feedback="be more complete", tokens_used=17)
    monkeypatch.setattr("fpl_grounded_assistant.orchestrator.evaluate_response", lambda **kwargs: verdict)


@pytest.mark.parametrize("raw, reason", [(FETCH_FAILED_TEXT, REASON_TRANSPORT_ERROR),
                                         (BBC_HTML_TEXT, REASON_HTML_DOCUMENT)], ids=["fetch_failed", "html"])
def test_route_1_evaluator_retry_render_is_guarded(monkeypatch, bootstrap, raw, reason):
    """Retry ran a tool, its synthesis returned no text -> render() was the
    last word (orchestrator.py, the i96/i37 retry terminal)."""
    _reject(monkeypatch)
    client = _SeqClient([
        _tool_use("c1"),
        NS(content=[NS(type="text", text="A genuine synthesised answer.")]),
        _tool_use("c2"),
        NS(content=[]),
    ])
    with _raw_render(raw):
        result = ask_orchestrated("What gameweek is it?", bootstrap, client=client, _eval_client=object())
    assert result.retry_attempted is True and result.synthesis_turn is False
    _assert_guarded(result, raw, reason, expected_outcome="ok")
    _assert_raw_output_intact(result)


@pytest.mark.parametrize("raw, reason", [(FETCH_FAILED_TEXT, REASON_TRANSPORT_ERROR),
                                         (BBC_HTML_TEXT, REASON_HTML_DOCUMENT)], ids=["fetch_failed", "html"])
def test_route_2_loop_normal_render_is_guarded(monkeypatch, bootstrap, raw, reason):
    """Loop mode: the round that stopped calling tools carried no text ->
    ``answer = render(selected[1], selected[3])`` (the normal terminal)."""
    monkeypatch.setenv("FPL_ORCH_LOOP_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_MAX_ROUNDS", "3")
    client = _SeqClient([_tool_use("c1"), NS(content=[])])
    with _raw_render(raw):
        result = ask_orchestrated("What gameweek is it?", bootstrap, client=client, _eval_client=None)
    assert result.synthesis_turn is False and result.rounds_exhausted is False
    _assert_guarded(result, raw, reason, expected_outcome="ok")
    _assert_raw_output_intact(result)


@pytest.mark.parametrize("raw, reason", [(FETCH_FAILED_TEXT, REASON_TRANSPORT_ERROR),
                                         (BBC_HTML_TEXT, REASON_HTML_DOCUMENT)], ids=["fetch_failed", "html"])
def test_route_3_loop_partial_render_is_guarded(monkeypatch, bootstrap, raw, reason):
    """Loop mode, round cap hit -> "Respuesta incompleta (...): {rendered}"."""
    monkeypatch.setenv("FPL_ORCH_LOOP_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_MAX_ROUNDS", "1")
    client = _SeqClient([_tool_use("c1"), _tool_use("c2")])
    with _raw_render(raw):
        result = ask_orchestrated("What gameweek is it?", bootstrap, client=client, _eval_client=None)
    assert result.rounds_exhausted is True
    assert result.guarded_raw_answer_text.startswith("Respuesta incompleta (")
    assert result.answer_text.startswith(HONEST_PREFIX)
    assert raw[:40] in result.guarded_raw_answer_text and raw[:40] not in result.answer_text
    assert result.final_text_guard_reason == reason
    assert result.outcome == "ok"
    _assert_raw_output_intact(result)


@pytest.mark.parametrize("raw, reason", [(FETCH_FAILED_TEXT, REASON_TRANSPORT_ERROR),
                                         (BBC_HTML_TEXT, REASON_HTML_DOCUMENT)], ids=["fetch_failed", "html"])
def test_route_4_no_text_synthesis_render_is_guarded(bootstrap, raw, reason):
    """Single-tool path: synthesis and the i46 extra round produced no text
    -> i96 notice + render() (the "no text" terminal). This is also the
    shape of the undiagnosed 1/43 'No pude redactar...' turn: whatever made
    the synthesis empty, a raw render under the notice cannot ship."""
    client = _SeqClient([])  # tool_use on every call
    with _raw_render(raw):
        result = ask_orchestrated("What gameweek is it?", bootstrap, client=client, _eval_client=None)
    assert result.synthesis_turn is False
    notice = t("orchestrator.raw_render_notice", "es")
    assert result.guarded_raw_answer_text.startswith(notice)
    assert result.answer_text.startswith(HONEST_PREFIX)
    assert raw[:40] in result.guarded_raw_answer_text and raw[:40] not in result.answer_text
    assert result.final_text_guard_reason == reason
    assert result.outcome == "ok"
    _assert_raw_output_intact(result)


def test_route_4_readable_render_under_notice_still_ships(bootstrap):
    """The negative through a real route: a readable catalogue error under
    the i96 notice is NOT guarded (the user keeps the hint)."""
    client = _SeqClient([])
    with _raw_render(READABLE_NOT_FOUND):
        result = ask_orchestrated("What gameweek is it?", bootstrap, client=client, _eval_client=None)
    assert result.answer_text.endswith(READABLE_NOT_FOUND)
    assert result.final_text_guard_reason is None
    assert result.guarded_raw_answer_text is None


def test_route_5_synthesis_quoting_html_is_guarded(bootstrap):
    """The model itself wrote the payload: raw_output never held it, so the
    only place it survives is guarded_raw_answer_text."""
    client = _SeqClient([_tool_use("c1"), NS(content=[NS(type="text", text=BBC_HTML_TEXT)])])
    result = ask_orchestrated("What gameweek is it?", bootstrap, client=client, _eval_client=None)
    assert result.synthesis_turn is True
    _assert_guarded(result, BBC_HTML_TEXT, REASON_HTML_DOCUMENT, expected_outcome="ok")
    assert BBC_HTML_TEXT[:60] not in json.dumps(result.tool_output)


def test_route_5_synthesis_quoting_transport_error_is_guarded(bootstrap):
    client = _SeqClient([_tool_use("c1"), NS(content=[NS(type="text", text=FETCH_FAILED_TEXT)])])
    result = ask_orchestrated("What gameweek is it?", bootstrap, client=client, _eval_client=None)
    _assert_guarded(result, FETCH_FAILED_TEXT, REASON_TRANSPORT_ERROR, expected_outcome="ok")


def test_outcome_is_never_changed_by_the_guard(bootstrap):
    """A tool that failed keeps its non-ok outcome; the guard swaps text only."""
    r = OrchestratorResult(question="q", tool_chosen="web_fetch", tool_args={}, tool_output={"status": "error"},
                           answer_text=FETCH_FAILED_TEXT, llm_used=True, model="m", outcome="tool_result_error")
    g = orch_mod._guard_final_text(r)
    assert g.outcome == "tool_result_error"
    assert g.answer_text.startswith(HONEST_PREFIX) and "web_fetch" in g.answer_text


def test_guard_without_a_tool_name_uses_the_generic_sentence():
    r = OrchestratorResult(question="q", tool_chosen=None, tool_args={}, tool_output={},
                           answer_text=BBC_HTML_TEXT, llm_used=True, model="m", outcome="no_tool")
    g = orch_mod._guard_final_text(r)
    assert g.answer_text == t("orchestrator.final_text_guarded", "es")


# ---------------------------------------------------------------------------
# ask_v2 dict -> audit line, both surfaces; never an HTTP contract
# ---------------------------------------------------------------------------

def test_harness_projects_both_fields_on_both_orchestrator_branches():
    from fpl_grounded_assistant.harness import _project_final_text_guard
    guarded = OrchestratorResult(question="q", tool_chosen="web_fetch", tool_args={}, tool_output={},
                                 answer_text="x", llm_used=True, model="m", outcome="ok",
                                 final_text_guard_reason=REASON_HTML_DOCUMENT, guarded_raw_answer_text=BBC_HTML_TEXT)
    clean = OrchestratorResult(question="q", tool_chosen=None, tool_args={}, tool_output={},
                               answer_text="x", llm_used=True, model="m", outcome="no_tool")
    assert _project_final_text_guard(guarded) == {
        "final_text_guard_reason": REASON_HTML_DOCUMENT, "guarded_raw_answer_text": BBC_HTML_TEXT,
    }
    assert _project_final_text_guard(clean) == {"final_text_guard_reason": None, "guarded_raw_answer_text": None}


def _read_lines(log_dir) -> list[dict]:
    files = [p for p in os.listdir(log_dir) if p.endswith(".ndjson")]
    assert len(files) == 1
    with open(os.path.join(log_dir, files[0]), encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_audit_line_carries_reason_and_whole_raw_text(tmp_path):
    entry = audit_mod.make_audit_entry(
        question="q", branch="orchestrator", outcome="ok", final_text="No obtuve una respuesta útil de web_fetch",
        final_text_guard_reason=REASON_HTML_DOCUMENT, guarded_raw_answer_text=BBC_HTML_TEXT,
    )
    audit_mod.write_audit_entry(entry, log_dir=str(tmp_path))
    (line,) = _read_lines(tmp_path)
    assert line["final_text_guard_reason"] == REASON_HTML_DOCUMENT
    assert line["guarded_raw_answer_text"] == BBC_HTML_TEXT           # whole, not a preview
    assert len(line["guarded_raw_answer_text"]) == len(BBC_HTML_TEXT)
    assert line["final_text_preview"].startswith("No obtuve")


def test_audit_line_clean_turn_has_both_fields_null(tmp_path):
    audit_mod.write_audit_entry(
        audit_mod.make_audit_entry(question="q", branch="orchestrator", outcome="ok", final_text="Jornada 5."),
        log_dir=str(tmp_path),
    )
    (line,) = _read_lines(tmp_path)
    assert "final_text_guard_reason" in line and line["final_text_guard_reason"] is None
    assert "guarded_raw_answer_text" in line and line["guarded_raw_answer_text"] is None


def test_http_contracts_do_not_carry_the_fields():
    import fpl_server
    for model in (fpl_server.AskResponse, fpl_server.SessionAskResponse):
        assert "guarded_raw_answer_text" not in model.model_fields
        assert "final_text_guard_reason" not in model.model_fields


def _guarded_ask_v2_dict(question: str) -> dict:
    return {
        "selected_tool": "web_fetch", "tool_input": {"url": "https://www.bbc.com/sport"},
        "raw_output": {"status": "ok", "url": "https://www.bbc.com/sport", "content_length": 4111},
        "answer_text": "No obtuve una respuesta útil de web_fetch para esto. Prueba a reformular o pregunta otra cosa.",
        "outcome": "ok", "kind": "text",
        "orchestrator_provider": "openai", "orchestrator_model": "gpt-5.6-luna",
        "final_text_guard_reason": REASON_HTML_DOCUMENT, "guarded_raw_answer_text": BBC_HTML_TEXT,
        "routing_trace": {"branch": "orchestrator", "decision_kind": "text", "decision_outcome": "fallthrough",
                          "router_hit": False, "classifier_called": False, "classifier_confidence": None,
                          "orchestrator_called": True, "orchestrator_outcome": "ok", "grounded": True,
                          "synthesis_turn": False, "tool_call_count": 1, "tool_sequence": ["web_fetch"],
                          "feature_flag_orch_enabled": True, "feature_flag_football_intelligence_enabled": False},
        "tool_calls_trace": [{"round": 1, "name": "web_fetch", "args": {}, "output": {"status": "ok"}, "success": True}],
        "tokens": {"total": 10},
    }


def test_both_http_surfaces_audit_the_raw_and_never_return_it(monkeypatch):
    """End to end: the ask_v2 dict carries the two keys; /ask and
    /session/{id}/ask write them to the audit line and neither JSON body
    contains the raw text or the keys."""
    from fastapi.testclient import TestClient
    import fpl_server
    from fpl_grounded_assistant import STANDARD_BOOTSTRAP
    from fpl_grounded_assistant.quota import reset_quota

    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._sessions.clear()
    reset_quota()
    written: list = []
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda e: written.append(e))
    client = TestClient(fpl_server.app)

    def _fake(question, bootstrap, *a, **k):
        return _guarded_ask_v2_dict(question)

    with patch("fpl_grounded_assistant.harness.ask_v2", side_effect=_fake):
        ask = client.post("/ask", json={"question": "noticias del Forest", "debug": True})
        sid = client.post("/session").json()["session_id"]
        sess = client.post(f"/session/{sid}/ask", json={"question": "noticias del Forest", "debug": True})

    for resp in (ask, sess):
        assert resp.status_code == 200
        body = resp.json()
        assert body["final_text"].startswith("No obtuve")
        assert "guarded_raw_answer_text" not in body and "final_text_guard_reason" not in body
        assert "<!DOCTYPE" not in resp.text and "bbc.com/sport/football" not in resp.text

    assert len(written) == 2, [e.branch for e in written]
    for e in written:
        assert e.final_text_guard_reason == REASON_HTML_DOCUMENT
        assert e.guarded_raw_answer_text == BBC_HTML_TEXT
    fpl_server._sessions.clear()
    reset_quota()
