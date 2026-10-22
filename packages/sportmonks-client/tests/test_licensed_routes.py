"""Routes for the production licensed ingestion (B3 PR 3a). Mock transport only; synthetic records."""
from __future__ import annotations

import pytest

from sportmonks_client.client import EXTRA_ROUTES, SportmonksClient, get_route
from sportmonks_client.config import SportmonksConfig
from sportmonks_client.models import Fixture, SquadMember

from conftest import FakeTransport, response

SCOPE = {"start": "2026-10-20", "end": "2026-11-02", "team_id": 900001}


def _client(*bodies):
    transport = FakeTransport([response(b) for b in bodies])
    return SportmonksClient.offline(transport, config=SportmonksConfig()), transport


@pytest.mark.parametrize("family,path,include", [
    ("licensed_pl_fixtures", "fixtures/between/2026-10-20/2026-11-02",
     "participants;lineups.detailedPosition;formations;state;metadata"),
    ("licensed_team_fixtures", "fixtures/between/2026-10-20/2026-11-02/900001", "participants;state"),
    ("licensed_squads", "squads/teams/900001", "player"),
])
def test_each_route_sends_its_path_and_include(family, path, include):
    client, transport = _client({"data": []})
    assert client.fetch_page(family, scope=SCOPE, params={"filters": "fixtureLeagues:8"}) == ()
    (_method, url, params, _timeout), = transport.calls
    assert url.endswith("/" + path) and params["include"] == include
    assert "api_token" not in params  # offline client


def test_the_matchday_route_keeps_the_nested_lists_whole():
    fixture = {"id": 800001, "league_id": 8, "starting_at": "2026-10-24 14:00:00", "state": {"developer_name": "NS"},
               "participants": [{"id": 900001, "name": "Arsenal", "meta": {"location": "home"}}],
               "lineups": [{"id": 1, "player_id": 700001, "team_id": 900001, "type_id": 11, "formation_field": "2:1",
                            "detailedposition": {"id": 1, "name": "Right Back"}}],
               "formations": [{"participant_id": 900001, "formation": "4-3-3"}],
               "metadata": [{"type_id": 572, "values": {"confirmed": False}}]}
    client, _ = _client({"data": [fixture]})
    (record,) = client.fetch_page("licensed_pl_fixtures", scope=SCOPE)
    assert isinstance(record, Fixture) and record.provider_id == 800001
    assert record.raw_fields == fixture


def test_the_squad_route_keeps_the_player_nested():
    row = {"id": 1, "player_id": 700001, "team_id": 900001, "jersey_number": 2,
           "player": {"id": 700001, "name": "Invented Player", "display_name": "I. Player", "date_of_birth": "1999-01-01"}}
    client, _ = _client({"data": [row]})
    (record,) = client.fetch_page("licensed_squads", scope=SCOPE)
    assert isinstance(record, SquadMember) and record.raw_fields["player"]["date_of_birth"] == "1999-01-01"


def test_the_licensed_routes_are_extras_and_do_not_change_the_fifteen_families():
    assert {"licensed_pl_fixtures", "licensed_team_fixtures", "licensed_squads"} <= set(EXTRA_ROUTES)
    assert get_route("team_fixtures").include is None and get_route("squads").include is None
