"""Governed provider-neutral season and fixture scheduling keys."""
from __future__ import annotations

import re

_SEASON = re.compile(r"(?:[0-9]{4}(?:-[0-9]{4})?|special-[a-z0-9]+(?:-[a-z0-9]+)*)")
_FIXTURE = re.compile(
    r"(?:league-(?:home|away)-meeting-[12]|"
    r"cup-[a-z0-9]+(?:-[a-z0-9]+)*-(?:leg-[12]|replay-[1-9][0-9]*|single)|"
    r"replacement-[1-9][0-9]*|neutral-[a-z0-9]+(?:-[a-z0-9]+)*)"
)


def validate_edition_key(value: str) -> str:
    if _SEASON.fullmatch(value) is None:
        raise ValueError("invalid season edition key")
    if "-" in value and value[:4].isdigit() and int(value[5:]) != int(value[:4]) + 1:
        raise ValueError("split-year season must contain consecutive years")
    return value


def validate_fixture_key(value: str) -> str:
    if _FIXTURE.fullmatch(value) is None:
        raise ValueError("invalid fixture scheduling key")
    return value
