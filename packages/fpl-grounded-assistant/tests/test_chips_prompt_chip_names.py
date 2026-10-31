"""/chips accepts the chip names as words (Triple Captain), es and en."""
from __future__ import annotations

import pytest

from fpl_grounded_assistant.harness import ask_v2


@pytest.mark.parametrize("locale", ["es", "en"])
@pytest.mark.parametrize("arg", [
    "Triple Captain", "triple captain", "Bench Boost", "Free Hit", "Wildcard",
    "triple_captain", "triple-captain", "tc",
])
def test_chip_name_as_typed_is_accepted(bootstrap, locale, arg):
    result = ask_v2(f"/chips {arg}", bootstrap, orch_client=None, locale=locale)
    assert result["outcome"] != "needs_clarification", result["answer_text"]


def test_unknown_chip_still_asks(bootstrap):
    result = ask_v2("/chips Mega Boost", bootstrap, orch_client=None, locale="en")
    assert result["outcome"] == "needs_clarification"
