"""i18n S0 -- the locale reaches every layer of the orchestrated path.

Decision D1 = B (Leo, 2026-10-23): the es prompts stay byte-identical (they keep
``respond_lang = user_lang``), the en locale appends one line, and the mismatch
(es locale + English question) is documented and counted, not fixed.

What this file pins:

* the sha256 of the es orchestrator and evaluator system prompts -- Spanish
  cannot drift without someone editing this number on purpose;
* request capture: a fake provider records every message the orchestrator and
  the evaluator actually send (primary round, synthesis, evaluator, retry), for
  the four combinations of question language x selected locale;
* the deterministic fallbacks and composers follow the locale;
* ``AskRequest.locale`` -> ``resolve_locale``, the quota text, ``question_lang``
  and its /healthz counter.

No network, no paid call.
"""
from __future__ import annotations

import hashlib
import json
import socket
from types import SimpleNamespace as NS

import pytest

from conftest import BOOTSTRAP
from fpl_grounded_assistant import evaluator as evaluator_mod
from fpl_grounded_assistant import orchestrator as orch_mod
from fpl_grounded_assistant.orchestrator import ask_orchestrated, static_system_prompt
from fpl_grounded_assistant.question_lang import detect_question_lang, locale_mismatch

# ---------------------------------------------------------------------------
# 1. The es prompts are pinned
# ---------------------------------------------------------------------------

#: sha256 of the pre-i18n prompts. Changing a prompt means changing these ON
#: PURPOSE, with a Spanish regression run (D1 option A) behind it.
ES_ORCH_PROMPT_SHA256 = "8f20176f66bc9d9731b17edc1f85ff9066db0e8f51e40f589de876becfd76efd"
ES_ORCH_LOOP_PROMPT_SHA256 = "66cbccc14a8e0baa60530535676de5a92c0c5cd3201e4aaecc8e2f972fc28005"
ES_EVALUATOR_PROMPT_SHA256 = "82efcffa20f74632ce9e023ab49115f3e208dff00dbac668f2fbd30617726707"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_es_orchestrator_prompts_are_byte_identical():
    assert _sha(orch_mod._SYSTEM_PROMPT) == ES_ORCH_PROMPT_SHA256
    assert _sha(orch_mod._LOOP_SYSTEM_PROMPT) == ES_ORCH_LOOP_PROMPT_SHA256


def test_es_evaluator_prompt_is_byte_identical():
    assert _sha(evaluator_mod._EVALUATOR_SYSTEM_PROMPT) == ES_EVALUATOR_PROMPT_SHA256


def test_es_locale_sends_the_pinned_prompt_and_no_en_line():
    assert _sha(static_system_prompt("es")) == ES_ORCH_PROMPT_SHA256
    assert _sha(evaluator_mod.evaluator_system_prompt("es")) == ES_EVALUATOR_PROMPT_SHA256
    assert "LOCALE=en" not in static_system_prompt("es")
    assert "LOCALE=en" not in evaluator_mod.evaluator_system_prompt("es")


def test_en_locale_appends_exactly_one_line():
    en = static_system_prompt("en")
    assert en.startswith(orch_mod._SYSTEM_PROMPT)
    assert en[len(orch_mod._SYSTEM_PROMPT):] == orch_mod._EN_LOCALE_LINE
    assert "LOCALE=en" in en
    ev = evaluator_mod.evaluator_system_prompt("en")
    assert ev.startswith(evaluator_mod._EVALUATOR_SYSTEM_PROMPT)
    assert "LOCALE=en" in ev


def test_default_locale_is_es_everywhere():
    assert static_system_prompt() == static_system_prompt("es")
    assert evaluator_mod.evaluator_system_prompt() == evaluator_mod.evaluator_system_prompt("es")


# ---------------------------------------------------------------------------
# 2. Request capture: what the providers are actually sent
# ---------------------------------------------------------------------------

QUESTIONS = {
    "es": "¿A quién debo capitanear esta jornada?",
    "en": "Who should I captain this gameweek?",
}
GW_CONTEXT_OUTPUT = {
    "status": "ok",
    "current_gameweek": {"id": 5, "finished": True},
    "next_gameweek": {"id": 6, "deadline_time": "2026-10-03T10:00:00Z"},
}


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    _real_connect = socket.socket.connect

    def _loopback_only(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"S0 tests must not touch the network: {address!r}")
        return _real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _loopback_only)
    for var in ("FPL_JEV_MODE", "FPL_ORCH_LOOP_ENABLED", "FPL_EVAL_DISABLED", "FPL_ORCH_LOOP_PROMPT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(
        orch_mod, "run_tool", lambda name, args, bootstrap: json.loads(json.dumps(GW_CONTEXT_OUTPUT))
    )
    locale_mismatch.reset()


def _usage() -> NS:
    return NS(input_tokens=100, output_tokens=10, cache_read_input_tokens=0)


def _tool_use(name: str, cid: str) -> NS:
    return NS(content=[NS(type="tool_use", id=cid, name=name, input={})], stop_reason="tool_use", usage=_usage())


def _text(text: str) -> NS:
    return NS(content=[NS(type="text", text=text)], stop_reason="end_turn", usage=_usage())


def _flatten_system(system) -> str:
    if isinstance(system, str):
        return system
    return "".join(b.get("text", "") for b in system or [] if isinstance(b, dict))


class _RecordingClient:
    """Anthropic-shaped primary client: primary tool round, synthesis, then the
    evaluator retry round (recognised by its "Previous attempt feedback:" question).
    Records every ``create`` call's system prompt and first user message."""

    def __init__(self) -> None:
        self.messages = self
        self.calls: list[dict] = []
        self._primary = [_tool_use("get_gameweek_context", "c1"), _text("Respuesta del modelo.")]
        self._retry = [_text("Retry answer.")]

    def create(self, **kwargs):
        first = (kwargs.get("messages") or [{}])[0]
        content = first.get("content") if isinstance(first, dict) else None
        is_retry = isinstance(content, str) and content.startswith("Previous attempt feedback:")
        self.calls.append(
            {"system": _flatten_system(kwargs.get("system")), "retry": is_retry, "first": content}
        )
        queue = self._retry if is_retry else self._primary
        return queue.pop(0) if queue else _text("")


class _RecordingEvaluatorClient:
    """Anthropic-shaped evaluator client that rejects once (forcing the retry)."""

    def __init__(self) -> None:
        self.messages = self
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append({"system": _flatten_system(kwargs.get("system"))})
        verdict = {
            "grounded": False, "complete": True, "safe": True,
            "retry_feedback": "Cite the concrete values.",
        }
        return NS(content=[NS(type="text", text=json.dumps(verdict))], usage=NS(input_tokens=5, output_tokens=5))


@pytest.mark.parametrize("question_lang", ["es", "en"])
@pytest.mark.parametrize("locale", ["es", "en"])
def test_every_provider_message_carries_the_locale(locale, question_lang):
    """primary + synthesis + evaluator + retry, for all four combinations."""
    client, eval_client = _RecordingClient(), _RecordingEvaluatorClient()
    result = ask_orchestrated(
        QUESTIONS[question_lang], BOOTSTRAP,
        client=client, _eval_client=eval_client, locale=locale,
    )

    assert result.retry_attempted is True, "the scenario must exercise the retry round"
    kinds = [c["retry"] for c in client.calls]
    assert kinds.count(False) >= 2, "primary tool round + synthesis"
    assert kinds.count(True) >= 1, "evaluator retry round"
    assert eval_client.calls, "the evaluator was called"

    has_line = lambda text: "LOCALE=en" in text  # noqa: E731
    for call in client.calls:
        assert has_line(call["system"]) is (locale == "en"), call
        if locale == "es":
            assert call["system"].startswith(orch_mod._SYSTEM_PROMPT)
        else:
            assert call["system"].startswith(orch_mod._SYSTEM_PROMPT + orch_mod._EN_LOCALE_LINE)
    for call in eval_client.calls:
        assert has_line(call["system"]) is (locale == "en"), call
        if locale == "es":
            assert call["system"] == evaluator_mod._EVALUATOR_SYSTEM_PROMPT
    # The question itself is never rewritten by the locale.
    assert client.calls[0]["first"] == QUESTIONS[question_lang]


def test_locale_arg_is_keyword_only_with_es_default():
    import inspect

    for fn in (orch_mod.ask_orchestrated, orch_mod._ask_orchestrated_impl):
        param = inspect.signature(fn).parameters["locale"]
        assert param.default == "es"
        assert param.kind is inspect.Parameter.KEYWORD_ONLY


# ---------------------------------------------------------------------------
# 3. Deterministic text inside the orchestrator path follows the locale
# ---------------------------------------------------------------------------

class _NoToolClient:
    def __init__(self) -> None:
        self.messages = self

    def create(self, **kwargs):
        return NS(content=[], stop_reason="end_turn", usage=_usage())


@pytest.mark.parametrize(
    "locale,expected",
    [
        ("es", "No encontré una herramienta para responder a esto."),
        ("en", "I couldn't find a tool to answer that."),
    ],
)
def test_no_tool_fallback_follows_locale(locale, expected):
    result = ask_orchestrated("hola", BOOTSTRAP, client=_NoToolClient(), _eval_client=None, locale=locale)
    assert result.answer_text == expected


def _guarded_result(answer: str):
    return orch_mod.OrchestratorResult(
        question="q", tool_chosen="get_player_snapshot", tool_args={}, tool_output={},
        answer_text=answer, llm_used=True, model="m", outcome=orch_mod.OUTCOME_OK,
    )


def test_final_text_guard_follows_locale():
    raw = "<html><body>Error 500</body></html>"
    es = orch_mod._guard_final_text(_guarded_result(raw), "es")
    en = orch_mod._guard_final_text(_guarded_result(raw), "en")
    assert es.final_text_guard_reason is not None and es.final_text_guard_reason == en.final_text_guard_reason
    assert es.answer_text.startswith("No obtuve una respuesta útil")
    assert en.answer_text.startswith("I couldn't get a useful answer")
    assert orch_mod._guard_final_text(_guarded_result(raw)).answer_text == es.answer_text  # default is es


def test_catalogue_keys_added_in_s0_are_paired():
    from fpl_grounded_assistant.catalogue import t

    for key, params in (
        ("orchestrator.no_tool_found", {}),
        ("orchestrator.tool_call_failed", {}),
        ("orchestrator.tool_call_failed_reason", {"reason": "x"}),
        ("orchestrator.incomplete_answer", {"reason": "x", "rendered": "R"}),
    ):
        es, en = t(key, "es", **params), t(key, "en", **params)
        assert es and en and es != en, key
    # es wording is what the inline literals said before the move
    assert t("orchestrator.tool_call_failed_reason", "es", reason="r") == (
        "No se pudo completar una llamada de herramienta correctamente (r)."
    )
    assert t("orchestrator.incomplete_answer", "es", reason="r", rendered="R") == "Respuesta incompleta (r): R"


CAPTAIN_OUTPUT = {
    "status": "ok",
    "squad_source": "connected",
    "time_context": {"evaluated_gameweek": 7},
    "presentation": {"owned_top": [1, 2]},
    "ranked_candidates": [
        {"player_id": 1, "web_name": "Haaland", "team_short": "MCI", "position": "FWD", "captain_score": 7.25},
        {"player_id": 2, "web_name": "Saka", "team_short": "ARS", "position": "MID", "captain_score": 6.5},
    ],
}


def test_captain_list_follows_locale():
    from fpl_grounded_assistant.captain_list import captain_list, compose_captain_answer

    es = captain_list(CAPTAIN_OUTPUT, "top 2")
    assert es.startswith("**Tus mejores opciones de capitán — GW7**")
    assert "7.2" in es or "7.3" in es  # decimal point in Spanish too (Latin American audience)
    assert "7,2" not in es and "7,3" not in es
    assert captain_list(CAPTAIN_OUTPUT, "top 2", "es") == es
    en = captain_list(CAPTAIN_OUTPUT, "top 2", "en")
    assert en.startswith("**Your best captain options — GW7**")
    assert "7.2" in en or "7.3" in en
    assert compose_captain_answer("body", CAPTAIN_OUTPUT, "top 2", "en").endswith("body")


def test_chip_composition_follows_locale():
    """S3 translated the header and the particular sentence (S0 returned the bare
    body for en); es is untouched and en now composes both parts."""
    from fpl_grounded_assistant.chip_two_part import compose_chip_answer

    out = {
        "status": "ok", "chip": "bench_boost", "recommendation": "conditions_favorable",
        "squad_source": None, "signals": {"favoured_teams": [{"team": 1}], "favoured_players": []},
    }
    names = {1: "Arsenal"}
    en = compose_chip_answer("English body.", out, names, "en")
    assert en.startswith("**Bench Boost — favourable gameweek.** Favoured group: Arsenal.")
    assert en.endswith("Link your team and I'll tell you whether you already have the favoured group.")
    es = compose_chip_answer("Cuerpo.", out, names)
    assert es == compose_chip_answer("Cuerpo.", out, names, "es")
    assert es.startswith("**Bench Boost — jornada favorable.** Grupo favorecido: Arsenal.")


# ---------------------------------------------------------------------------
# 4. The wire: AskRequest.locale -> resolve_locale, quota text, audit
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value,expected",
    [(None, "es"), ("es", "es"), ("en", "en"), ("EN", "en"), (" en ", "en"), ("fr", "es"), ("", "es"), ("en-GB", "es")],
)
def test_resolve_locale_reads_the_body_field(value, expected):
    from fpl_server import AskRequest, resolve_locale

    body = AskRequest(question="x", locale=value)
    assert resolve_locale(object(), body) == expected


def test_resolve_locale_ignores_accept_language():
    from fpl_server import AskRequest, resolve_locale

    request = NS(headers={"accept-language": "en-GB,en;q=0.9"})
    assert resolve_locale(request, AskRequest(question="x")) == "es"


def test_quota_upgrade_text_follows_locale():
    from fpl_server import _quota_upgrade_text

    qc = NS(upgrade_prompt_es="Llegaste a tu límite.", upgrade_prompt_en="You've reached your limit.")
    assert _quota_upgrade_text(qc, "es") == "Llegaste a tu límite."
    assert _quota_upgrade_text(qc) == "Llegaste a tu límite."
    assert _quota_upgrade_text(qc, "en") == "You've reached your limit."
    empty = NS(upgrade_prompt_es=None, upgrade_prompt_en=None)
    assert "límite" in _quota_upgrade_text(empty, "es")
    assert "limit" in _quota_upgrade_text(empty, "en")


def test_audit_line_carries_locale_only_when_given():
    import tempfile
    from pathlib import Path

    from fpl_grounded_assistant.audit import make_audit_entry, write_audit_entry

    with tempfile.TemporaryDirectory() as tmp:
        plain = make_audit_entry(question="q", branch="route", outcome="ok")
        write_audit_entry(plain, log_dir=tmp)
        tagged = make_audit_entry(question="q", branch="route", outcome="ok", locale="en", question_lang="es")
        write_audit_entry(tagged, log_dir=tmp)
        lines = [
            json.loads(line)
            for f in Path(tmp).glob("*.ndjson")
            for line in f.read_text(encoding="utf-8").splitlines()
        ]
    assert "locale" not in lines[0] and "question_lang" not in lines[0]
    assert lines[1]["locale"] == "en" and lines[1]["question_lang"] == "es"


# ---------------------------------------------------------------------------
# 5. question_lang + the /healthz mismatch counter
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Should I captain Haaland this gameweek?", "en"),
        ("Who are the best differentials for next gameweek", "en"),
        ("What is the price of Saka", "en"),
        ("¿A quién debo fichar para la jornada 12?", "es"),
        ("dame los mejores delanteros baratos", "es"),
        ("Cuántos puntos tiene Saka", "es"),
        ("Haaland", "unknown"),
        ("/capitan Haaland", "unknown"),
        ("@injuries", "unknown"),
        ("compare Salah vs Palmer", "unknown"),
        ("top 5 xG", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_detect_question_lang(text, expected):
    assert detect_question_lang(text) == expected


def test_mismatch_counter_snapshot():
    locale_mismatch.record("es", "es")
    locale_mismatch.record("es", "en")
    locale_mismatch.record("en", "en")
    locale_mismatch.record("en", "unknown")
    snap = locale_mismatch.snapshot()
    assert snap["counts"] == {"es:es": 1, "es:en": 1, "en:en": 1, "en:unknown": 1}
    assert snap["known_turns"] == 3
    assert snap["mismatch"] == 1
    assert snap["mismatch_rate"] == round(1 / 3, 4)
    locale_mismatch.reset()
    assert locale_mismatch.snapshot()["mismatch_rate"] is None


def test_note_locale_turn_records_and_never_raises(monkeypatch):
    import fpl_server

    assert fpl_server._note_locale_turn("es", "Should I captain Haaland this gameweek?") == "en"
    assert locale_mismatch.snapshot()["counts"] == {"es:en": 1}

    def _boom(_text):
        raise RuntimeError("detector down")

    monkeypatch.setattr(fpl_server, "detect_question_lang", _boom)
    assert fpl_server._note_locale_turn("es", "anything") == "unknown"
