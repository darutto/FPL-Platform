"""No tool description may promise an argument is omittable when it is required.

``rank_captain_candidates`` claimed both of these in one schema object::

    description=("Rank captain candidates by score (desc). Inputs auto-derived; "
                 "override per candidate. Omit candidates -> auto top-10 by form.")
    "required": ["candidates"]

The runner enforces ``required`` before the handler is reached, so a model that
followed the description got a guaranteed
``status=error, code=missing_argument`` — one wasted round, every time. The
promise was also unfulfillable on its own terms: ``form`` reads 0.0 for every
element in the pre-season bootstrap, so "auto top-10 by form" would rank
nothing even if the argument were optional.

The generic check below covers the whole offered set rather than just that one
tool, so the next instance is caught when it is written. It is pinned in both
directions: a mutation test feeds it the original false description and
requires it to flag it, so a checker that silently stopped matching anything
would fail rather than pass.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PACKAGES = _HERE.parent.parent

for _pkg in sorted(_PACKAGES.iterdir()):
    if _pkg.is_dir() and str(_pkg) not in sys.path:
        sys.path.insert(0, str(_pkg))

from fpl_grounded_assistant.tool_schema_registry import _ALL_SCHEMAS

#: Phrasings that tell a model "you may leave this argument out". ``{arg}`` is
#: substituted with the escaped argument name; ``[^.]{0,N}`` keeps the cue and
#: the argument inside one sentence so unrelated clauses cannot pair up.
_OMITTABILITY_CUES: tuple[str, ...] = (
    r"\bomit(?:s|ted|ting)?\b[^.]{{0,40}}\b{arg}\b",
    r"\b{arg}\b[^.]{{0,40}}\bomit(?:s|ted|ting)?\b",
    r"\bwithout\b[^.]{{0,25}}\b{arg}\b",
    r"\b{arg}\b[^.]{{0,25}}\b(?:is |are )?optional\b",
    r"\boptional\b[^.]{{0,25}}\b{arg}\b",
    r"\bleave\b[^.]{{0,25}}\b{arg}\b[^.]{{0,25}}\b(?:out|blank|empty|unset)\b",
    r"\bif\b[^.]{{0,15}}\b{arg}\b[^.]{{0,25}}"
    r"\b(?:absent|missing|omitted|unset|not (?:given|provided|supplied|set))\b",
)


def _omittability_claims(description: str, required: list[str]) -> list[tuple[str, str]]:
    """Return ``(argument, matched_text)`` for every omittability claim about a
    *required* argument found in ``description``."""
    claims: list[tuple[str, str]] = []
    for arg in required:
        for cue in _OMITTABILITY_CUES:
            pattern = cue.format(arg=re.escape(arg))
            match = re.search(pattern, description, flags=re.IGNORECASE)
            if match:
                claims.append((arg, match.group(0)))
                break
    return claims


# ---------------------------------------------------------------------------
# The checker must actually catch things — pinned before it is trusted
# ---------------------------------------------------------------------------

_ORIGINAL_FALSE_DESCRIPTION = (
    "Rank captain candidates by score (desc). Inputs auto-derived; "
    "override per candidate. Omit candidates → auto top-10 by form."
)


def test_checker_flags_the_description_this_test_was_written_for():
    """Mutation proof: the exact string that shipped must be flagged."""
    claims = _omittability_claims(_ORIGINAL_FALSE_DESCRIPTION, ["candidates"])

    assert claims, "checker no longer catches the defect it exists to catch"
    assert claims[0][0] == "candidates"


@pytest.mark.parametrize(
    "description",
    [
        "Omit candidates to get the top 10.",
        "Works without candidates.",
        "candidates is optional.",
        "The optional candidates list narrows the ranking.",
        "Leave candidates blank for defaults.",
        "If candidates is omitted, the tool picks for you.",
        "If candidates is not provided, defaults apply.",
    ],
)
def test_checker_flags_each_omittability_phrasing(description):
    assert _omittability_claims(description, ["candidates"])


@pytest.mark.parametrize(
    "description",
    [
        "Rank captain candidates by score (desc).",
        "candidates is required: pass the players to rank.",
        # An omittability claim about a *different*, genuinely optional
        # argument must not be flagged.
        "Omit team_query for ALL teams ranked easiest-first.",
        # Nearby but unrelated words must not pair up across sentences.
        "Inputs auto-derived; override optional. Pass candidates to rank.",
    ],
)
def test_checker_does_not_flag_truthful_descriptions(description):
    assert not _omittability_claims(description, ["candidates"])


# ---------------------------------------------------------------------------
# The defect, and the whole offered set
# ---------------------------------------------------------------------------

def test_rank_captain_candidates_no_longer_claims_candidates_is_omittable():
    schema = next(s for s in _ALL_SCHEMAS if s.name == "rank_captain_candidates")

    assert "candidates" in schema.parameters["required"], (
        "the fix keeps candidates required; auto-derivation was explicitly not "
        "implemented (it would duplicate rank_players_by_metric and be built on "
        "form, which is 0.0 for every element pre-season)"
    )
    assert not _omittability_claims(schema.description, schema.parameters["required"])
    assert "auto top-10 by form" not in schema.description


@pytest.mark.parametrize("schema", _ALL_SCHEMAS, ids=lambda s: s.name)
def test_no_description_promises_a_required_argument_is_omittable(schema):
    required = schema.parameters.get("required", []) or []
    claims = _omittability_claims(schema.description, required)

    assert not claims, (
        f"{schema.name}: description says {claims!r} but the runner enforces "
        f"required={required!r}, so a model that believes it gets "
        f"status=error/missing_argument"
    )


def test_the_offered_set_is_actually_being_checked():
    """Guards against the parametrised test above passing because the schema
    list is empty or the descriptions are blank."""
    assert len(_ALL_SCHEMAS) >= 30
    with_required = [s for s in _ALL_SCHEMAS if s.parameters.get("required")]
    assert len(with_required) >= 20
    assert all(s.description.strip() for s in _ALL_SCHEMAS)
