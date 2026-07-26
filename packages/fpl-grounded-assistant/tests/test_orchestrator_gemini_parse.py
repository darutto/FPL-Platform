"""
Regression tests for _parse_all_gemini_tool_calls (orchestrator.py).

Bug: Gemini response parts are protobuf messages, so `part.function_call`
is frequently PRESENT-but-default (empty `name`) on text-only / "thought"
parts rather than absent (`None`). The parser's `if fc is None: continue`
guard therefore let an empty-named function call through, which downstream
tripped the "Model selected an unknown tool: ''" hard-stop — making EVERY
open-ended (orchestrator-routed) question fail locally against Gemini with
`outcome=unsupported_intent`, even though the model had actually answered.

Fix: skip any function_call whose `name` is falsy. When every part is empty
the caller correctly falls through to the no-tool text-extraction path (the
model's own prose answer / refusal reaches the user).
"""
from __future__ import annotations

import os as _os
import sys as _sys

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

from fpl_grounded_assistant.orchestrator import _parse_all_gemini_tool_calls  # noqa: E402


class _FC:
    """Minimal stand-in for a Gemini FunctionCall proto."""
    def __init__(self, name, args=None):
        self.name = name
        self.args = args


class _Part:
    def __init__(self, function_call=None):
        # Mirror the protobuf reality: the attribute is always present; an
        # "absent" call is an empty-named FunctionCall, not literal None.
        self.function_call = function_call


class _Content:
    def __init__(self, parts):
        self.parts = parts


class _Candidate:
    def __init__(self, parts):
        self.content = _Content(parts)


class _Response:
    def __init__(self, parts):
        self.candidates = [_Candidate(parts)]


def test_empty_named_function_call_is_skipped():
    """The core regression: an empty-name function_call (protobuf default on a
    text-only part) must NOT be returned as a tool call."""
    resp = _Response([_Part(_FC(name="", args={}))])
    assert _parse_all_gemini_tool_calls(resp) == []


def test_real_function_call_still_parsed():
    """A genuine tool call is unaffected by the empty-name skip."""
    resp = _Response([_Part(_FC(name="find_players", args={"query": "Salah"}))])
    result = _parse_all_gemini_tool_calls(resp)
    assert len(result) == 1
    _call_id, name, args = result[0]
    assert name == "find_players"
    assert args == {"query": "Salah"}


def test_mixed_parts_keeps_only_the_real_call():
    """A response with an empty 'thought' part alongside a real call returns
    only the real one — the exact shape that produced the original crash."""
    resp = _Response([
        _Part(_FC(name="", args={})),                                  # empty thought part
        _Part(_FC(name="rank_players_by_metric", args={"metric": "saves"})),
    ])
    result = _parse_all_gemini_tool_calls(resp)
    assert [name for _cid, name, _a in result] == ["rank_players_by_metric"]


def test_none_function_call_still_skipped():
    """The original `fc is None` guard must still hold for parts with no call."""
    resp = _Response([_Part(function_call=None)])
    assert _parse_all_gemini_tool_calls(resp) == []
