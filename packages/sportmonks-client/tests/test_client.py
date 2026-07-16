import pytest

from sportmonks_client.client import ENDPOINTS, SportmonksClient
from sportmonks_client.config import SportmonksConfig
from sportmonks_client.errors import (SportmonksAuthenticationError, SportmonksPaginationError,
                                      SportmonksRateLimitError, SportmonksRequestError, SportmonksSchemaError)
from sportmonks_client.models import RawResponseSnapshot
from conftest import FakeTransport, load_fixture, response


def offline(responses, **kwargs):
    config = SportmonksConfig(max_retries=kwargs.pop("max_retries", 3), backoff_seconds=.25, max_pages=kwargs.pop("max_pages", 100))
    return SportmonksClient.offline(FakeTransport(responses), config=config, **kwargs)


def test_every_endpoint_family_parses(endpoint_payloads):
    for family, payload in endpoint_payloads["families"].items():
        client = offline([response(payload)])
        method = "team_fixture_statistics" if family == "team_statistics" else "player_fixture_statistics" if family == "player_statistics" else family
        records = getattr(client, method)()
        assert len(records) == 1 and records[0].source_endpoint == ENDPOINTS[family][0]


def test_unknown_extra_fields_preserved(endpoint_payloads):
    record = offline([response(endpoint_payloads["families"]["players"])]).players()[0]
    assert "date_of_birth" in record.raw_fields


def test_missing_optional_fields(edge_cases):
    assert offline([response(edge_cases["missing_optional"])]).players()[0].provider_id == 1


def test_malformed_required_id():
    with pytest.raises(SportmonksSchemaError): offline([response({"data":[{"name":"x"}]})]).players()


def test_malformed_envelope(edge_cases):
    with pytest.raises(SportmonksSchemaError): offline([response(edge_cases["malformed_envelope"])]).players()


def test_multiple_pages():
    pages = load_fixture("multi_page.json")["pages"]
    client = offline([response(page) for page in pages])
    assert [item.provider_id for item in client.players()] == [1, 2]


def test_empty_page(edge_cases):
    assert offline([response(edge_cases["empty"])]).players() == ()


def test_pagination_loop(edge_cases):
    with pytest.raises(SportmonksPaginationError, match="loop"):
        offline([response(edge_cases["pagination_loop"][0])]).players()


def test_page_limit():
    page = lambda n: {"data":[],"pagination":{"current_page":n,"has_more":True,"next_page":n+1}}
    with pytest.raises(SportmonksPaginationError, match="maximum"):
        offline([response(page(1)), response(page(2))], max_pages=2).players()


def test_timeout_then_success_and_backoff():
    sleeps=[]
    client=offline([SportmonksRequestError("timeout"),response({"data":[]})],sleep=sleeps.append)
    assert client.players()==() and sleeps==[.25]


def test_429_retry_after_then_success():
    sleeps=[]
    client=offline([response({},429,{"Retry-After":"2"}),response({"data":[]})],sleep=sleeps.append)
    assert client.players()==() and sleeps==[2]


def test_429_exhaustion():
    with pytest.raises(SportmonksRateLimitError): offline([response({},429),response({},429)],max_retries=1,sleep=lambda _:None).players()


def test_500_then_success():
    assert offline([response({},500),response({"data":[]})],sleep=lambda _:None).players()==()


def test_non_retryable_400():
    with pytest.raises(SportmonksRequestError): offline([response({},400)]).players()


@pytest.mark.parametrize("status",[401,403])
def test_authentication_fails_immediately(status):
    fake=FakeTransport([response({},status),response({"data":[]})])
    with pytest.raises(SportmonksAuthenticationError): SportmonksClient.offline(fake).players()
    assert len(fake.calls)==1


def test_snapshot_hook_redacts_token():
    snapshots=[]; fake=FakeTransport([response({"data":[]})])
    SportmonksClient(SportmonksConfig(api_token="secret"),transport=fake,snapshot_hook=snapshots.append).players(include="team")
    assert isinstance(snapshots[0],RawResponseSnapshot) and "api_token" not in snapshots[0].requested_parameters
