"""
i151b: the injury surfaces show the status badge text in Spanish.

Presentation boundaries only: ``InjuryEntry.status_label`` (the tool/API
value) stays English; the generic_card cell and the @injuries resource row
carry the catalogue's Spanish. Unmapped values pass through unchanged.
"""
from __future__ import annotations

import pytest

from fpl_grounded_assistant.final_response import InjuryEntry, InjuryListMeta
from fpl_grounded_assistant.generic_card import compose_injury_list
from fpl_grounded_assistant.resource_registry import _resource_injuries

ES = {"Injured": "Lesionado", "Doubtful": "Dudoso",
      "Suspended": "Suspendido", "Unavailable": "No disponible"}


def _entry(label: str) -> InjuryEntry:
    return InjuryEntry(web_name="X", team_short="ARS", position="MID",
                       status_label=label)


@pytest.mark.parametrize("english, spanish", sorted(ES.items()))
def test_generic_card_status_cell_is_spanish(english, spanish):
    meta = InjuryListMeta(injured=(_entry(english),), doubtful=(), other=(),
                          total=1)
    card = compose_injury_list(meta)
    assert card.rows[0][3] == spanish


def test_generic_card_unmapped_status_passes_through():
    meta = InjuryListMeta(injured=(_entry("WEIRD"),), doubtful=(), other=(),
                          total=1)
    assert compose_injury_list(meta).rows[0][3] == "WEIRD"


def test_tool_value_stays_english():
    e = _entry("Injured")
    assert e.status_label == "Injured"   # the dataclass is not translated


def test_injuries_resource_rows_are_spanish():
    bs = {
        "teams": [{"id": 1, "short_name": "ARS"}],
        "elements": [
            {"web_name": "A", "team": 1, "element_type": 3, "status": "i",
             "news": "", "news_added": "2026-10-01T10:00:00Z"},
            {"web_name": "B", "team": 1, "element_type": 3, "status": "d",
             "chance_of_playing_this_round": 75, "news": "",
             "news_added": "2026-10-02T10:00:00Z"},
            {"web_name": "C", "team": 1, "element_type": 3, "status": "s",
             "news": "", "news_added": "2026-10-03T10:00:00Z"},
            {"web_name": "D", "team": 1, "element_type": 3, "status": "u",
             "news": "", "news_added": "2026-10-04T10:00:00Z"},
            {"web_name": "E", "team": 1, "element_type": 3, "status": "a"},
        ],
    }
    rows = {r["web_name"]: r["status_label"] for r in _resource_injuries(bs).rows}
    assert rows == {"A": "Lesionado", "B": "Dudoso",
                    "C": "Suspendido", "D": "No disponible"}
