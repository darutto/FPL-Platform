import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from sportmonks_client.client import ENDPOINTS, MAX_RETRY_AFTER_SECONDS, SportmonksClient, route_path
from sportmonks_client.config import SportmonksConfig
from sportmonks_client.errors import (SportmonksAuthenticationError, SportmonksPaginationError,
                                      SportmonksRateLimitError, SportmonksRequestError, SportmonksSchemaError)
from sportmonks_client.models import RawResponseSnapshot
from conftest import FakeTransport, load_fixture, response


def offline(responses, **kwargs):
    config = SportmonksConfig(max_retries=kwargs.pop("max_retries", 3), backoff_seconds=.25, max_pages=kwargs.pop("max_pages", 100))
    return SportmonksClient.offline(FakeTransport(responses), config=config, **kwargs)


SCOPE = {"start": "2026-10-01", "end": "2026-10-14", "season_id": 1, "team_id": 1}


def test_every_endpoint_family_parses(endpoint_payloads):
    from _trial_common import _nest
    for family, payload in endpoint_payloads["families"].items():
        client = offline([response(_nest(family, list(payload["data"])))])
        records = client.fetch_page(family, scope=SCOPE)
        assert len(records) == len(payload["data"]) and records[0].source_endpoint == route_path(family, SCOPE), family
        assert len(client.transport.calls) == 1


def test_a_templated_route_without_its_scope_is_refused_not_guessed():
    with pytest.raises(SportmonksRequestError, match="needs scope"):
        offline([]).fetch_page("squads")


def test_derived_families_ride_one_route_and_differ_by_include():
    window = {ENDPOINTS[f].path for f in ("lineups", "formations", "substitutions", "injuries", "suspensions",
                                         "team_statistics", "player_statistics")}
    assert window == {"fixtures/between/{start}/{end}"}
    assert {f: ENDPOINTS[f].include for f in ("lineups", "formations", "substitutions")} == {
        "lineups": "lineups.detailedPosition", "formations": "formations", "substitutions": "events"}


def test_sidelined_rows_are_split_by_category_and_deduplicated():
    row = lambda i, cat: {"id": i, "fixture_id": 1, "player_id": i, "sideline": {"id": 90 + i, "category": cat}}
    page = {"data": [{"id": 1, "sidelined": [row(1, "injury"), row(2, "suspended")]},
                     {"id": 2, "sidelined": [row(1, "injury")]}]}
    injuries = offline([response(page)]).fetch_page("injuries", scope=SCOPE)
    suspensions = offline([response(page)]).fetch_page("suspensions", scope=SCOPE)
    assert [r.provider_id for r in injuries] == [91] and [r.provider_id for r in suspensions] == [92]


def test_events_keep_only_substitutions():
    page = {"data": [{"id": 1, "events": [{"id": 5, "type_id": 14}, {"id": 6, "type_id": 18}, {"id": 7, "type_id": 19}]}]}
    assert [r.provider_id for r in offline([response(page)]).fetch_page("substitutions", scope=SCOPE)] == [6]


def test_player_statistics_flatten_two_levels():
    page = {"data": [{"id": 1, "lineups": [{"id": 2, "details": [{"id": 3}, {"id": 4}]}, {"id": 5, "details": [{"id": 6}]}]}]}
    assert [r.provider_id for r in offline([response(page)]).fetch_page("player_statistics", scope=SCOPE)] == [3, 4, 6]


def test_page_bound_per_call_raises_instead_of_pretending_complete():
    pages = [response({"data": [], "pagination": {"current_page": n, "has_more": True, "next_page": n + 1}}) for n in (1, 2, 3)]
    with pytest.raises(SportmonksPaginationError, match="maximum"):
        tuple(offline(pages).iter_entities("coaches", max_pages=2))


def test_unknown_extra_fields_preserved(endpoint_payloads):
    record = offline([response(endpoint_payloads["families"]["coaches"])]).coaches()[0]
    assert "name" in record.raw_fields


def test_missing_optional_fields(edge_cases):
    assert offline([response(edge_cases["missing_optional"])]).coaches()[0].provider_id == 1


def test_malformed_required_id():
    with pytest.raises(SportmonksSchemaError): offline([response({"data":[{"name":"x"}]})]).coaches()


def test_malformed_envelope(edge_cases):
    with pytest.raises(SportmonksSchemaError): offline([response(edge_cases["malformed_envelope"])]).coaches()


def test_multiple_pages():
    pages = load_fixture("multi_page.json")["pages"]
    client = offline([response(page) for page in pages])
    assert [item.provider_id for item in client.coaches()] == [1, 2]


def test_empty_page(edge_cases):
    assert offline([response(edge_cases["empty"])]).coaches() == ()


def test_pagination_loop(edge_cases):
    with pytest.raises(SportmonksPaginationError, match="loop"):
        offline([response(edge_cases["pagination_loop"][0])]).coaches()


def test_page_limit():
    page = lambda n: {"data":[],"pagination":{"current_page":n,"has_more":True,"next_page":n+1}}
    with pytest.raises(SportmonksPaginationError, match="maximum"):
        offline([response(page(1)), response(page(2))], max_pages=2).coaches()


def test_timeout_then_success_and_backoff():
    sleeps=[]
    client=offline([SportmonksRequestError("timeout", retryable=True),response({"data":[]})],sleep=sleeps.append)
    assert client.coaches()==() and sleeps==[.25]


def test_429_retry_after_then_success():
    sleeps=[]
    client=offline([response({},429,{"Retry-After":"2"}),response({"data":[]})],sleep=sleeps.append)
    assert client.coaches()==() and sleeps==[2]


@pytest.mark.parametrize(("header", "expected"), [
    ("-2", .25), ("0", 0), ("2.5", 2.5), ("999999", 60),
    ("NaN", .25), ("Infinity", .25), ("-Infinity", .25),
    ("Wed, 21 Oct 2015 07:28:00 GMT", .25), ("malformed", .25), (None, .25),
])
def test_retry_after_is_finite_non_negative_and_bounded(header, expected):
    sleeps=[]; headers={} if header is None else {"Retry-After":header}
    client=offline([response({},429,headers),response({"data":[]})],sleep=sleeps.append)
    assert client.coaches()==()
    assert sleeps == [expected]
    assert 0 <= sleeps[0] <= MAX_RETRY_AFTER_SECONDS


def test_429_exhaustion():
    with pytest.raises(SportmonksRateLimitError): offline([response({},429),response({},429)],max_retries=1,sleep=lambda _:None).coaches()


def test_500_then_success():
    assert offline([response({},500),response({"data":[]})],sleep=lambda _:None).coaches()==()


def test_non_retryable_400():
    with pytest.raises(SportmonksRequestError): offline([response({},400)]).coaches()


@pytest.mark.parametrize("status",[401,403])
def test_authentication_fails_immediately(status):
    fake=FakeTransport([response({},status),response({"data":[]})])
    with pytest.raises(SportmonksAuthenticationError): SportmonksClient.offline(fake).coaches()
    assert len(fake.calls)==1


def test_redirect_is_refused_without_following():
    with pytest.raises(SportmonksRequestError, match="redirect refused"):
        offline([response({}, 302, {"Location": "https://other.invalid/?api_token=SECRET"})]).coaches()


def test_snapshot_hook_redacts_token():
    snapshots=[]; fake=FakeTransport([response({"data":[]})])
    SportmonksClient(SportmonksConfig(api_token="secret"),transport=fake,snapshot_hook=snapshots.append).coaches(include="team")
    assert isinstance(snapshots[0],RawResponseSnapshot) and "api_token" not in snapshots[0].requested_parameters


def test_snapshot_hook_preserves_only_governed_response_headers():
    snapshots=[]
    client=SportmonksClient.offline(
        FakeTransport([response({"data":[]}, headers={
            "Content-Type":"application/json", "X-RateLimit-Remaining":"99",
            "X-Request-ID":"request-1", "Set-Cookie":"secret-cookie",
        })]), config=SportmonksConfig(), snapshot_hook=snapshots.append,
    )
    client.coaches()
    assert snapshots[0].response_metadata == {
        "content-type":"application/json", "x-ratelimit-remaining":"99", "x-request-id":"request-1",
    }


def test_malformed_meta_is_typed_schema_failure():
    with pytest.raises(SportmonksSchemaError, match="malformed meta"):
        offline([response({"data":[], "meta":[]})]).coaches()


def test_next_page_url_is_parsed_to_page_number():
    """Live finding 2026-10-11: next_page is a URL, not an int."""
    url = "https://api.sportmonks.com/v3/football/teams?page=2"
    first = {"data":[{"id":1}],"pagination":{"current_page":1,"has_more":True,"next_page":url,"next_cursor":"x"}}
    last = {"data":[{"id":2}],"pagination":{"current_page":2,"has_more":False,"next_page":None}}
    assert [t.provider_id for t in offline([response(first), response(last)]).coaches()] == [1, 2]


def test_next_page_garbage_is_rejected():
    bad = {"data":[],"pagination":{"current_page":1,"has_more":True,"next_page":"https://x/y?cursor=abc"}}
    with pytest.raises(SportmonksSchemaError):
        offline([response(bad)]).coaches()
