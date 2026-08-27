"""i18/i19 — Spanish metric phrases resolve, and ranking direction is controllable.

Measured over 26 live calls: routing chose ``rank_players_by_metric`` 26/26, so
the tool choice was never the problem. Eleven of those calls still failed, in
two ways this module pins:

*   **Resolution (i18).** The model emits the user's whole Spanish noun phrase
    ("tiros libres directos", "tiradores de penales"), and the alias map only
    did exact equality plus a prefix relaxation in the direction that cannot
    help — the input being a prefix *of* a key. Every measured failure had the
    opposite shape: the phrase *contains* its alias.
*   **Direction (i19).** There was no sort direction. "Los cinco defensas más
    baratos" got the ten most *expensive* defenders; the model reordered that
    set and answered fluently, naming a £6.0m defender as the league's cheapest
    in both repetitions, while genuinely cheap ones never entered the candidate
    set. Silent and plausible, which is worse than unknown_metric.

The i15 guarantee — invented metrics relay ``unknown_metric`` instead of being
guessed at — is pinned here too, because token containment is exactly the kind
of relaxation that could erode it.
"""

from __future__ import annotations

import pytest

from fpl_grounded_assistant.atomic_tool_cards import compose_rank_players_card
from fpl_grounded_assistant.rank_players_by_metric import (
    _resolve_by_token_containment,
    natural_order,
    rank_players_by_metric,
)
from fpl_grounded_assistant.renderer import render


def _element(player_id: int, name: str, **metrics) -> dict:
    element = {
        "id": player_id,
        "first_name": name,
        "second_name": "Test",
        "web_name": name,
        "team": 1,
        "element_type": 2,
        "status": "a",
        "minutes": 900,
    }
    element.update(metrics)
    return element


@pytest.fixture()
def price_bootstrap() -> dict:
    """Defenders spanning the real price range, cheapest genuinely cheapest."""
    prices = [40, 45, 50, 55, 60, 65, 70, 75, 80, 90, 100, 120]
    return {
        "teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS"}],
        "element_types": [{"id": 2, "singular_name_short": "DEF"}],
        "elements": [
            _element(
                idx, "Def%02d" % idx, now_cost=cost,
                selected_by_percent=str(float(idx)),
                expected_goals_conceded=str(float(idx)),
                transfers_in_event=idx * 10,
                transfers_out_event=idx * 5,
                penalties_order=(idx % 3) + 1,
                direct_freekicks_order=(idx % 2) + 1,
                goals_scored=idx, assists=idx, total_points=idx,
                threat=str(float(idx)),
            )
            for idx, cost in enumerate(prices, start=1)
        ],
    }


# ---------------------------------------------------------------------------
# i18 — every measured failing phrase resolves to the right field
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("phrase", "canonical"),
    [
        # Key is a prefix of the input — the direction the old relaxation missed.
        ("tiros libres directos",                  "direct_freekicks_order"),
        # Key sits mid-phrase.
        ("amenaza ofensiva",                       "threat"),
        ("tiradores de penales",                   "penalties_order"),
        # Wrong-shaped alias: the map only had "transferencias entrantes".
        ("transferencias de entrada",              "transfers_in_event"),
        ("transferencias de entrada esta jornada", "transfers_in_event"),
        # xGC had no Spanish alias at all; these two resolved only by luck.
        ("goles esperados en contra",              "expected_goals_conceded"),
        ("goles esperados concedidos",             "expected_goals_conceded"),
        # No key existed.
        ("propiedad",                              "selected_by_percent"),
    ],
)
def test_measured_spanish_phrases_resolve(price_bootstrap, phrase, canonical):
    result = rank_players_by_metric(phrase, bootstrap=price_bootstrap)

    assert result["status"] == "ok", result
    assert result["metric"] == canonical


@pytest.mark.parametrize(
    ("phrase", "canonical"),
    [
        ("porcentaje de propiedad",  "selected_by_percent"),
        ("transferencias de salida", "transfers_out_event"),
        ("xg en contra",             "expected_goals_conceded"),
        ("puntos por partido",       "points_per_game"),
        ("porterías a cero",         "clean_sheets"),
        ("asistencias esperadas",    "expected_assists"),
        ("tiros libres indirectos",  "corners_and_indirect_freekicks_order"),
        # Framing words the model tacks on carry no metric information.
        ("goles de la temporada",    "goals_scored"),
        ("minutos en la liga",       "minutes"),
    ],
)
def test_added_spanish_aliases_resolve(price_bootstrap, phrase, canonical):
    result = rank_players_by_metric(phrase, bootstrap=price_bootstrap)

    assert result["status"] == "ok", result
    assert result["metric"] == canonical


def test_longest_alias_wins_over_its_own_prefixes():
    """The interaction the brief flagged: "goles esperados en contra" overlaps
    ``goles``, ``goles esperados`` and itself. Most matched tokens must win."""
    assert _resolve_by_token_containment(
        "goles esperados en contra de los defensas",
    ) == "expected_goals_conceded"
    assert _resolve_by_token_containment(
        "goles esperados de los delanteros",
    ) == "expected_goals"
    assert _resolve_by_token_containment(
        "goles de los delanteros",
    ) == "goals_scored"


# ---------------------------------------------------------------------------
# i15 non-regression — invented metrics are still relayed, never guessed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("invented", [
    "chispa ofensiva",
    "garra",
    "vibra",
    "regularidad de gameweek",
    "hambre de gol",
])
def test_invented_metrics_still_return_unknown_metric(price_bootstrap, invented):
    """Verified live under i15. If token containment resolves any of these, the
    design is wrong, not this test."""
    result = rank_players_by_metric(invented, bootstrap=price_bootstrap)

    assert result["status"] == "invalid_argument"
    assert result["code"] == "unknown_metric"
    assert invented in result["message"]
    assert result["valid_metrics"]


def test_ambiguous_phrase_between_two_fields_returns_unknown_metric(price_bootstrap):
    """"goles" and "asistencias" tie at one matched token each and belong to
    different fields — the tool must refuse rather than pick one."""
    assert _resolve_by_token_containment("goles y asistencias") is None

    result = rank_players_by_metric("goles y asistencias", bootstrap=price_bootstrap)

    assert result["status"] == "invalid_argument"
    assert result["code"] == "unknown_metric"


def test_tie_between_aliases_of_the_same_field_still_resolves():
    """"goles" and "goals" are two aliases of one field: not an ambiguity."""
    assert _resolve_by_token_containment("goals y goles del torneo") == "goals_scored"


# ---------------------------------------------------------------------------
# i19 — sort direction
# ---------------------------------------------------------------------------

def test_asc_returns_the_genuinely_cheapest_not_a_reordered_top(price_bootstrap):
    """The measured failure: the cheapest defenders were never in the set."""
    ascending = rank_players_by_metric(
        "precio", top_n=5, order="asc", bootstrap=price_bootstrap,
    )
    descending = rank_players_by_metric(
        "precio", top_n=5, bootstrap=price_bootstrap,
    )

    asc_values = [entry["metric_value"] for entry in ascending["ranked"]]
    assert asc_values == pytest.approx([4.0, 4.5, 5.0, 5.5, 6.0])
    assert ascending["order"] == "asc"

    # Not obtainable by re-sorting the descending page: the sets are disjoint.
    desc_names = {entry["web_name"] for entry in descending["ranked"]}
    asc_names = {entry["web_name"] for entry in ascending["ranked"]}
    assert asc_names.isdisjoint(desc_names)


def test_absent_order_preserves_existing_ranking_exactly(price_bootstrap):
    """Adding the parameter must not move any pre-existing ranking."""
    for metric in ("precio", "propiedad", "goles", "transferencias de entrada"):
        implicit = rank_players_by_metric(metric, top_n=6, bootstrap=price_bootstrap)
        explicit = rank_players_by_metric(
            metric, top_n=6, order="desc", bootstrap=price_bootstrap,
        )

        assert implicit["order"] == "desc"
        assert implicit["ranked"] == explicit["ranked"]
        values = [entry["metric_value"] for entry in implicit["ranked"]]
        assert values == sorted(values, reverse=True)


def test_lower_is_better_metrics_keep_ascending_by_default(price_bootstrap):
    """Set-piece order still ranks 1st-on-the-list first when nothing is asked."""
    result = rank_players_by_metric("penales", top_n=5, bootstrap=price_bootstrap)

    assert result["order"] == "asc"
    assert natural_order("penalties_order") == "asc"
    values = [entry["metric_value"] for entry in result["ranked"]]
    assert values == sorted(values)


def test_explicit_order_overrides_lower_is_better(price_bootstrap):
    result = rank_players_by_metric(
        "penales", top_n=5, order="desc", bootstrap=price_bootstrap,
    )

    assert result["order"] == "desc"
    values = [entry["metric_value"] for entry in result["ranked"]]
    assert values == sorted(values, reverse=True)


@pytest.mark.parametrize("bogus", ["ascending", "", "up", None, 7])
def test_unrecognized_order_falls_back_to_the_natural_direction(price_bootstrap, bogus):
    """A bad value must not silently invert the ranking, and the payload always
    reports the direction that was actually applied."""
    result = rank_players_by_metric(
        "precio", top_n=3, order=bogus, bootstrap=price_bootstrap,
    )

    assert result["order"] == "desc"
    values = [entry["metric_value"] for entry in result["ranked"]]
    assert values == sorted(values, reverse=True)


def test_order_is_reported_even_when_no_bootstrap_is_available():
    result = rank_players_by_metric("precio", order="asc", bootstrap=None)

    assert result["status"] == "ok"
    assert result["order"] == "asc"
    assert result["ranked"] == []


# ---------------------------------------------------------------------------
# Direction must reach the surfaces the user actually reads
# ---------------------------------------------------------------------------

def test_text_renderer_does_not_title_an_inverted_ranking_as_top(price_bootstrap):
    ascending = rank_players_by_metric(
        "precio", top_n=3, order="asc", bootstrap=price_bootstrap,
    )
    descending = rank_players_by_metric("precio", top_n=3, bootstrap=price_bootstrap)

    asc_text = render("rank_players_by_metric", ascending)
    desc_text = render("rank_players_by_metric", descending)

    assert asc_text.startswith("Los 3 jugadores con menor now_cost")
    assert desc_text.startswith("Top 3 jugadores por now_cost")


def test_text_renderer_keeps_top_for_natural_ascending_metrics(price_bootstrap):
    output = rank_players_by_metric("penales", top_n=3, bootstrap=price_bootstrap)

    assert render("rank_players_by_metric", output).startswith("Top 3 jugadores")


def test_card_title_follows_the_ranking_direction(price_bootstrap):
    ascending = rank_players_by_metric(
        "precio", top_n=3, order="asc", bootstrap=price_bootstrap,
    )
    descending = rank_players_by_metric("precio", top_n=3, bootstrap=price_bootstrap)

    assert compose_rank_players_card(ascending).title == "3 CON MENOR · Precio (£m)"
    assert compose_rank_players_card(descending).title == "TOP 3 · Precio (£m)"


def test_card_title_unchanged_for_payloads_without_order(price_bootstrap):
    """Cards must keep rendering payloads produced before ``order`` existed."""
    output = rank_players_by_metric("precio", top_n=3, bootstrap=price_bootstrap)
    output.pop("order")

    assert compose_rank_players_card(output).title == "TOP 3 · Precio (£m)"


def test_order_is_offered_in_both_tool_schemas():
    from fpl_grounded_assistant.rank_players_by_metric import (
        RANK_PLAYERS_BY_METRIC_SPEC,
    )
    from fpl_grounded_assistant.tool_schema_registry import (
        RANK_PLAYERS_BY_METRIC_SCHEMA,
    )

    for schema in (RANK_PLAYERS_BY_METRIC_SPEC, RANK_PLAYERS_BY_METRIC_SCHEMA):
        prop = schema.parameters["properties"]["order"]
        assert prop["enum"] == ["desc", "asc"]
        assert "order" not in schema.parameters["required"]
        assert "asc" in prop["description"]
