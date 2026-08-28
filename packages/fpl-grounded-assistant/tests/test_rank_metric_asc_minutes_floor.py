"""i44 — an explicit ``order="asc"`` must not rank "has not played" as best.

`order` shipped in #181 and the model reaches for it unprompted (6/6 live calls
emitted ``asc``). But under `asc` every accumulating metric puts players with no
minutes first: zero minutes means zero xGC, zero goals, zero cards, and zero
sorts to the top. Live, *"¿Qué porteros conceden menos goles esperados?"*
returned ten keepers tied at 0.0 xGC, none of whom had played — literally
correct, practically useless.

**Step 1 was tried first and measured.** Hardening the `min_minutes`/`order`
schema descriptions was re-measured with the existing probe against a
pre-registered rule (>=5 of 6 calls emitting ``min_minutes >= 60``). It scored
**2/6**, so the floor below is Step 2, not a first guess. The baseline it
replaces is worse than it looks: the model's unprompted value is
``min_minutes=1``, which filters nothing at all.

The floor is deliberately narrow, and every boundary here is a requirement
rather than an implementation detail:

*   only on an **explicit** ``asc`` — a metric that merely sorts ascending by
    nature is untouched;
*   never for ``now_cost`` (a 4.0m player with no minutes is legitimate bench
    fodder) or the set-piece orders (they already drop non-takers);
*   never above a caller's own larger ``min_minutes``;
*   never silent — it is reported in ``min_minutes_filter``;
*   ``desc`` is byte-for-byte unchanged.
"""

from __future__ import annotations

import pytest

from fpl_grounded_assistant.atomic_tool_cards import compose_rank_players_card
from fpl_grounded_assistant.rank_players_by_metric import (
    _ASC_MIN_MINUTES_FLOOR,
    rank_players_by_metric,
)
from fpl_grounded_assistant.renderer import render


#: The grounding payload spells minutes ``minutes_played_season``, so these
#: tests read the real value off each returned player rather than trusting the
#: filter argument alone.
_MINUTES_KEY = "minutes_played_season"

NEVER_PLAYED = {"P01", "P02", "P03", "P04", "P05"}
REGULARS     = {"P06", "P07", "P08", "P09", "P10"}


def _element(player_id: int, minutes: int, cost: int, **metrics) -> dict:
    element = {
        "id": player_id,
        "first_name": "P%02d" % player_id,
        "second_name": "Test",
        "web_name": "P%02d" % player_id,
        "team": 1,
        "element_type": 2,
        "status": "a",
        "minutes": minutes,
        "now_cost": cost,
    }
    element.update(metrics)
    return element


@pytest.fixture()
def mixed_bootstrap() -> dict:
    """Half the league has never played; the players who have are more
    expensive and have accumulated real values. That is the shape that makes an
    ascending sort pick exactly the wrong people."""
    elements = []
    # Never played: cheap, and zero on every accumulating metric.
    for idx in range(1, 6):
        elements.append(_element(
            idx, minutes=0, cost=40,
            expected_goals_conceded="0.0", goals_scored=0, saves=0,
            yellow_cards=0, selected_by_percent="0.1",
            penalties_order=0, total_points=0,
        ))
    # Regulars: full seasons, real values, higher prices.
    for offset, idx in enumerate(range(6, 11), start=1):
        elements.append(_element(
            idx, minutes=900, cost=50 + offset * 10,
            expected_goals_conceded=str(float(offset)), goals_scored=offset,
            saves=offset * 2, yellow_cards=offset,
            selected_by_percent=str(float(offset)),
            penalties_order=offset, total_points=offset * 10,
        ))
    return {
        "teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS"}],
        "element_types": [{"id": 2, "singular_name_short": "DEF"}],
        "elements": elements,
    }


# ---------------------------------------------------------------------------
# The defect itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("metric", [
    "goles esperados en contra",
    "goles",
    "tarjetas amarillas",
    "paradas",
    "propiedad",
    "puntos",
])
def test_asc_excludes_players_who_have_not_played(mixed_bootstrap, metric):
    """The measured failure: ten keepers tied at 0.0, none of whom had played."""
    result = rank_players_by_metric(
        metric, top_n=10, order="asc", bootstrap=mixed_bootstrap,
    )

    assert result["status"] == "ok", result
    assert result["ranked"], "the floor must not empty the ranking"
    returned = {entry["web_name"] for entry in result["ranked"]}
    assert returned <= REGULARS, sorted(returned & NEVER_PLAYED)
    assert all(entry[_MINUTES_KEY] >= _ASC_MIN_MINUTES_FLOOR
               for entry in result["ranked"])


def test_floor_is_reported_in_the_payload_not_only_in_the_result(mixed_bootstrap):
    """A hidden default is precisely what this must not be."""
    result = rank_players_by_metric(
        "goles esperados en contra", order="asc", bootstrap=mixed_bootstrap,
    )

    assert result["min_minutes_filter"] == _ASC_MIN_MINUTES_FLOOR


def test_floor_reaches_both_reader_facing_surfaces(mixed_bootstrap):
    """Reported in the payload is not enough — the user has to see it."""
    result = rank_players_by_metric(
        "goles esperados en contra", top_n=3, order="asc",
        bootstrap=mixed_bootstrap,
    )

    assert "min. minutos: 60" in render("rank_players_by_metric", result)
    assert "min. minutos: 60" in (compose_rank_players_card(result).subtitle or "")


# ---------------------------------------------------------------------------
# The exemptions — each one is a use case the floor would break
# ---------------------------------------------------------------------------

def test_price_asc_still_returns_cheap_players_with_no_minutes(mixed_bootstrap):
    """Bench fodder is a real answer to "los defensas más baratos"."""
    result = rank_players_by_metric(
        "precio", top_n=5, order="asc", bootstrap=mixed_bootstrap,
    )

    assert result["min_minutes_filter"] == 0
    assert [entry["metric_value"] for entry in result["ranked"]] == pytest.approx(
        [4.0, 4.0, 4.0, 4.0, 4.0]
    )
    assert {entry["web_name"] for entry in result["ranked"]} == NEVER_PLAYED
    assert all(entry[_MINUTES_KEY] == 0 for entry in result["ranked"])


def test_minutes_metric_asc_still_returns_players_who_have_not_played(
    mixed_bootstrap,
):
    """When the metric IS participation, zeros are the data rather than noise —
    the same reasoning that exempts now_cost.

    Decisive in practice: ``max(min_minutes, 60)`` cannot distinguish an omitted
    argument from an explicit 0, so a floor here would leave no way to ask the
    question at all. "Who is playing the fewest minutes" and "who has not played
    at all" are rotation and injury questions, and the tool must keep answering
    them."""
    result = rank_players_by_metric(
        "minutos", top_n=5, order="asc", bootstrap=mixed_bootstrap,
    )

    assert result["metric"] == "minutes"
    assert result["min_minutes_filter"] == 0
    assert {entry["web_name"] for entry in result["ranked"]} == NEVER_PLAYED
    assert all(entry[_MINUTES_KEY] == 0 for entry in result["ranked"])


def test_minutes_metric_desc_is_unaffected_too(mixed_bootstrap):
    result = rank_players_by_metric("minutos", top_n=5, bootstrap=mixed_bootstrap)

    assert result["min_minutes_filter"] == 0
    assert {entry["web_name"] for entry in result["ranked"]} == REGULARS


def test_set_piece_orders_are_unchanged_by_the_floor(mixed_bootstrap):
    """They already exclude non-takers by dropping values <= 0."""
    explicit = rank_players_by_metric(
        "penales", top_n=5, order="asc", bootstrap=mixed_bootstrap,
    )
    natural = rank_players_by_metric("penales", top_n=5, bootstrap=mixed_bootstrap)

    assert explicit["min_minutes_filter"] == 0
    assert explicit["ranked"] == natural["ranked"]


def test_natural_ascending_metric_does_not_trigger_the_floor(mixed_bootstrap):
    """The floor keys off an EXPLICIT asc, not off the direction that ends up
    applied — otherwise every set-piece ranking would silently gain a floor."""
    result = rank_players_by_metric("penales", top_n=5, bootstrap=mixed_bootstrap)

    assert result["order"] == "asc"
    assert result["min_minutes_filter"] == 0


# ---------------------------------------------------------------------------
# Boundaries
# ---------------------------------------------------------------------------

def test_caller_min_minutes_above_the_floor_is_respected(mixed_bootstrap):
    result = rank_players_by_metric(
        "goles", order="asc", min_minutes=500, bootstrap=mixed_bootstrap,
    )

    assert result["min_minutes_filter"] == 500


def test_caller_min_minutes_below_the_floor_is_raised(mixed_bootstrap):
    """min_minutes=1 is the value the model reaches for unprompted, and it
    filters nothing: one minute still leaves ~0 in every accumulating metric."""
    result = rank_players_by_metric(
        "goles", order="asc", min_minutes=1, bootstrap=mixed_bootstrap,
    )

    assert result["min_minutes_filter"] == _ASC_MIN_MINUTES_FLOOR
    assert all(entry[_MINUTES_KEY] >= _ASC_MIN_MINUTES_FLOOR
               for entry in result["ranked"])


def test_desc_is_identical_with_and_without_the_change(mixed_bootstrap):
    """Byte-for-byte parity on the descending path, which is the default and
    covers every pre-existing caller."""
    for metric in ("goles", "goles esperados en contra", "precio", "propiedad",
                   "puntos", "paradas", "tarjetas amarillas"):
        implicit = rank_players_by_metric(
            metric, top_n=8, bootstrap=mixed_bootstrap,
        )
        explicit = rank_players_by_metric(
            metric, top_n=8, order="desc", bootstrap=mixed_bootstrap,
        )

        assert implicit["min_minutes_filter"] == 0, metric
        assert explicit["min_minutes_filter"] == 0, metric
        assert implicit == explicit, metric


def test_floor_is_visible_without_a_bootstrap(mixed_bootstrap):
    """The early return must report the same floor the real path would apply."""
    result = rank_players_by_metric(
        "goles", order="asc", bootstrap=None,
    )

    assert result["status"] == "ok"
    assert result["min_minutes_filter"] == _ASC_MIN_MINUTES_FLOOR


def test_floor_reaches_the_tool_runner_handler(mixed_bootstrap):
    """The handler passes `order` through, so the floor must apply there too."""
    from fpl_grounded_assistant.rank_players_by_metric import (
        _rank_players_by_metric_handler,
    )

    result = _rank_players_by_metric_handler(
        {"metric": "goles esperados en contra", "order": "asc", "top_n": 5},
        mixed_bootstrap,
    )

    assert result["min_minutes_filter"] == _ASC_MIN_MINUTES_FLOOR
    assert all(entry[_MINUTES_KEY] >= _ASC_MIN_MINUTES_FLOOR
               for entry in result["ranked"])
