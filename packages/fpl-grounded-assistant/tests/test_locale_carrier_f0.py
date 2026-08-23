"""
tests/test_locale_carrier_f0.py
================================
Language track, Phase F0: the locale carrier.

F0 adds no translation and changes no string. What it adds is a `Locale`
type, a boundary-resolution function that (for now) always returns the
default, and a `locale` parameter threaded through the deterministic text
producers that is (for now) always ignored. These tests pin exactly that
contract: the default is Spanish, the boundary function ignores its inputs,
and a caller-supplied locale actually reaches `renderer.render()` — without
changing what `render()` returns.

Test suites
-----------
A.  Locale type + default
B.  fpl_server.resolve_locale() — boundary, ignores inputs
C.  renderer.render() — accepts locale, output is unaffected by its value
D.  harness.ask() / ask_v2() — locale threads down to render()
E.  AskRequest — no `locale` field (F0 decision: don't accept what we
    don't act on yet)
"""
from __future__ import annotations

import pytest


# ===========================================================================
# A. Locale type + default
# ===========================================================================

class TestLocaleDefault:
    def test_default_locale_is_spanish(self):
        from fpl_grounded_assistant.locale_types import DEFAULT_LOCALE
        assert DEFAULT_LOCALE == "es"

    def test_locale_type_accepts_es_and_en(self):
        # Literal["es", "en"] — not enforced at runtime, but both values must
        # be valid annotations callers can pass without a type-checker error.
        from fpl_grounded_assistant.locale_types import Locale
        import typing
        assert typing.get_args(Locale) == ("es", "en")


# ===========================================================================
# B. fpl_server.resolve_locale() — boundary, ignores inputs
# ===========================================================================

class TestResolveLocaleBoundary:
    def test_returns_default_with_plain_question(self):
        from fpl_server import resolve_locale, AskRequest, DEFAULT_LOCALE
        body = AskRequest(question="¿Quién es Haaland?")
        assert resolve_locale(object(), body) == DEFAULT_LOCALE

    def test_ignores_debug_and_other_fields(self):
        # F0: resolve_locale reads nothing off the request or the body yet —
        # any populated AskRequest must resolve to the same default.
        from fpl_server import resolve_locale, AskRequest, DEFAULT_LOCALE
        body = AskRequest(question="test", debug=True, intent_hint="captain_score")
        assert resolve_locale(object(), body) == DEFAULT_LOCALE

    def test_ignores_the_request_object_entirely(self):
        # Passing None instead of a real Request must not raise — the F0
        # body never touches its arguments.
        from fpl_server import resolve_locale, AskRequest, DEFAULT_LOCALE
        body = AskRequest(question="test")
        assert resolve_locale(None, body) == DEFAULT_LOCALE


# ===========================================================================
# C. renderer.render() — accepts locale, output is unaffected by its value
# ===========================================================================

class TestRenderLocaleNoOp:
    _RAW_OUTPUT = {
        "status": "not_found",
        "code": "player_not_found",
        "message": "No player matches 'zzzznotaplayer'.",
    }

    def test_render_accepts_locale_kwarg(self):
        from fpl_grounded_assistant.renderer import render
        # Must not raise TypeError for the new keyword-only-by-convention arg.
        text = render("resolve_player", self._RAW_OUTPUT, locale="en")
        assert isinstance(text, str) and text

    def test_render_output_identical_across_locales(self):
        from fpl_grounded_assistant.renderer import render
        default_text = render("resolve_player", self._RAW_OUTPUT)
        es_text = render("resolve_player", self._RAW_OUTPUT, locale="es")
        en_text = render("resolve_player", self._RAW_OUTPUT, locale="en")
        assert default_text == es_text == en_text

    def test_unknown_tool_fallback_identical_across_locales(self):
        from fpl_grounded_assistant.renderer import render
        raw = {"code": "unknown_tool", "message": "no renderer"}
        assert render("not_a_real_tool", raw) == render(
            "not_a_real_tool", raw, locale="en"
        )


# ===========================================================================
# D. harness.ask() / ask_v2() — locale threads down to render()
# ===========================================================================

class TestHarnessThreadsLocaleToRenderer:
    def test_ask_forwards_caller_locale_to_render(self, bootstrap, monkeypatch):
        from fpl_grounded_assistant import harness

        seen: dict[str, object] = {}
        real_render = harness.render

        def _spy(tool_name, raw_output, locale):
            seen["locale"] = locale
            return real_render(tool_name, raw_output, locale=locale)

        monkeypatch.setattr(harness, "render", _spy)
        harness.ask("Who is Salah?", bootstrap, locale="en")
        assert seen["locale"] == "en"

    def test_ask_defaults_to_spanish_when_locale_omitted(self, bootstrap, monkeypatch):
        from fpl_grounded_assistant import harness
        from fpl_grounded_assistant.locale_types import DEFAULT_LOCALE

        seen: dict[str, object] = {}
        real_render = harness.render

        def _spy(tool_name, raw_output, locale):
            seen["locale"] = locale
            return real_render(tool_name, raw_output, locale=locale)

        monkeypatch.setattr(harness, "render", _spy)
        harness.ask("Who is Salah?", bootstrap)
        assert seen["locale"] == DEFAULT_LOCALE

    def test_ask_v2_route_branch_forwards_locale_to_render(self, bootstrap, monkeypatch):
        # "Who is Salah?" resolves deterministically via the router (branch
        # "route"), which is the request-path call site wired in F0.
        #
        # ask_v2() re-imports `render` from the renderer module fresh on
        # every call (deferred import, to avoid a circular import at module
        # load time) rather than using harness.py's module-level binding, so
        # the patch target here is the renderer module itself, not `harness`.
        from fpl_grounded_assistant import harness, renderer

        seen: dict[str, object] = {}
        real_render = renderer.render

        def _spy(tool_name, raw_output, locale):
            seen["locale"] = locale
            return real_render(tool_name, raw_output, locale=locale)

        monkeypatch.setattr(renderer, "render", _spy)
        result = harness.ask_v2("Who is Salah?", bootstrap, locale="en")
        assert result["routing_trace"]["branch"] == "route"
        assert seen["locale"] == "en"

    def test_ask_v2_unsupported_branch_locale_does_not_change_text(self, bootstrap):
        # F0 no-op guarantee for the deterministic fallback message: same
        # text regardless of which locale reaches it.
        from fpl_grounded_assistant import harness

        default_result = harness.ask_v2("asdkjhasdkjh nonsense query", bootstrap)
        en_result = harness.ask_v2("asdkjhasdkjh nonsense query", bootstrap, locale="en")
        assert default_result["answer_text"] == en_result["answer_text"]


# ===========================================================================
# E. AskRequest — no `locale` field yet (F0 decision)
# ===========================================================================

class TestAskRequestHasNoLocaleField:
    def test_ask_request_does_not_accept_locale(self):
        # F0 decision: don't add AskRequest.locale until resolve_locale()
        # actually reads it (F2) — accepting a field we don't act on yet
        # would be a lie about the wire contract.
        from fpl_server import AskRequest
        assert "locale" not in AskRequest.model_fields
