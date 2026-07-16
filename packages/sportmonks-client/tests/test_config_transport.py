import logging
import traceback
from unittest.mock import MagicMock

import pytest
import requests

from sportmonks_client.client import SportmonksClient
from sportmonks_client.config import SportmonksConfig
from sportmonks_client.errors import SportmonksConfigurationError, SportmonksResponseError
from sportmonks_client.transport import RequestsTransport
from conftest import FakeTransport, response


def test_import_and_offline_need_no_token(monkeypatch):
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    client = SportmonksClient.offline(FakeTransport([response({"data": []})]))
    assert client.leagues() == ()


def test_live_client_requires_token(monkeypatch):
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    with pytest.raises(SportmonksConfigurationError, match="API_TOKEN"):
        SportmonksClient(transport=FakeTransport([]))


def test_config_defaults(monkeypatch):
    for name in ("SPORTMONKS_API_TOKEN", "SPORTMONKS_BASE_URL", "SPORTMONKS_TIMEOUT_SECONDS", "SPORTMONKS_MAX_RETRIES", "SPORTMONKS_BACKOFF_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    config = SportmonksConfig.from_env()
    assert (config.timeout_seconds, config.max_retries, config.backoff_seconds) == (15, 3, .5)


def test_config_environment(monkeypatch):
    monkeypatch.setenv("SPORTMONKS_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("SPORTMONKS_MAX_RETRIES", "4")
    assert SportmonksConfig.from_env().timeout_seconds == 2.5


@pytest.mark.parametrize("name,value", [("SPORTMONKS_TIMEOUT_SECONDS", "bad"), ("SPORTMONKS_MAX_RETRIES", "-1")])
def test_invalid_numeric(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(SportmonksConfigurationError): SportmonksConfig.from_env()


def test_requests_transport_query_timeout_and_json():
    raw = MagicMock(status_code=200, headers={"X-Test":"yes"})
    raw.json.return_value = {"data": []}
    session = MagicMock(); session.request.return_value = raw
    result = RequestsTransport(session).request("GET", "https://example.test", params={"x":1}, timeout=7)
    session.request.assert_called_once_with("GET", "https://example.test", params={"x":1}, timeout=7)
    assert result.body == {"data": []}


def test_transport_non_json_fails_once():
    raw = MagicMock(status_code=200, headers={}); raw.json.side_effect = ValueError()
    session = MagicMock(); session.request.return_value = raw
    with pytest.raises(SportmonksResponseError): RequestsTransport(session).request("GET", "x", params={}, timeout=1)


def test_token_only_in_sanctioned_query_and_redacted():
    fake = FakeTransport([response({"data": []})])
    client = SportmonksClient(SportmonksConfig(api_token="TOP-SECRET"), transport=fake)
    client.leagues()
    assert fake.calls[0][2]["api_token"] == "TOP-SECRET"
    assert "TOP-SECRET" not in str(SportmonksConfigurationError("failed"))


def test_transport_exception_chain_traceback_and_logs_redact_token(caplog):
    token = "TRACEBACK-SECRET"
    session = MagicMock()
    session.request.side_effect = requests.ConnectionError(f"failed https://host/path?api_token={token}")
    with caplog.at_level(logging.ERROR):
        try:
            RequestsTransport(session).request("GET", "https://host/path", params={"api_token": token}, timeout=1)
        except Exception as exc:
            logging.exception("captured typed transport failure")
            rendered = "".join(traceback.format_exception(exc))
            assert token not in str(exc)
            assert token not in repr(exc)
            assert token not in repr(exc.__cause__)
            assert token not in repr(exc.__context__)
            assert token not in rendered
        else:
            pytest.fail("transport failure was not wrapped")
    assert token not in caplog.text


@pytest.mark.parametrize("raw_error", [
    requests.TooManyRedirects("https://x?api_token=SECRET"),
    requests.exceptions.ChunkedEncodingError("https://x?api_token=SECRET"),
    requests.exceptions.InvalidURL("https://x?api_token=SECRET"),
])
def test_all_request_exception_subclasses_are_safely_wrapped(raw_error):
    token = "SECRET"
    session = MagicMock(); session.request.side_effect = raw_error
    with pytest.raises(Exception) as captured:
        RequestsTransport(session).request("GET", "https://x", params={"api_token":token}, timeout=1)
    assert type(captured.value).__name__ == "SportmonksRequestError"
    assert captured.value.__cause__ is None and captured.value.__context__ is None
    assert "SECRET" not in "".join(traceback.format_exception(captured.value))
