"""Registry messages name commands in the turn's language; es is unchanged."""
from __future__ import annotations

from fpl_grounded_assistant.harness import ask_v2


def _text(bootstrap, q, locale):
    return ask_v2(q, bootstrap, orch_client=None, locale=locale)["answer_text"]


def test_en_unknown_prompt_lists_english_names(bootstrap):
    text = _text(bootstrap, "/foo", "en")
    assert "/captain, /compare, /transfer, /fixtures, /differentials, /chips, /rankings" in text
    assert "/capitan" not in text


def test_es_unknown_prompt_is_unchanged(bootstrap):
    text = _text(bootstrap, "/foo", "es")
    assert "/capitan, /comparar, /transferencia, /calendarios, /diferenciales, /chips, /clasificacion" in text


def test_en_missing_argument_uses_english_command(bootstrap):
    assert "Prompt '/captain' needs more information" in _text(bootstrap, "/captain", "en")
    assert "Prompt '/capitan' needs more information" in _text(bootstrap, "/captain", "es")


def test_en_bad_chip_has_no_internal_codes(bootstrap):
    text = _text(bootstrap, "/chips Mega Boost", "en")
    assert "'tc'" not in text and "[" not in text
    assert "Triple Captain" in text


def test_es_bad_chip_is_unchanged(bootstrap):
    assert "not in ['tc'" in _text(bootstrap, "/chips Mega Boost", "es")
