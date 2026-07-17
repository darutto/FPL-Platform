import logging
import traceback
from unittest.mock import MagicMock

import pytest
import requests

from sportmonks_client.client import SportmonksClient
from sportmonks_client.config import SportmonksConfig
from sportmonks_client.errors import (SportmonksConfigurationError,
    SportmonksResponseError, SportmonksResponseSizeError)
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
    for name in ("SPORTMONKS_API_TOKEN", "SPORTMONKS_BASE_URL", "SPORTMONKS_TIMEOUT_SECONDS", "SPORTMONKS_MAX_RETRIES", "SPORTMONKS_BACKOFF_SECONDS", "SPORTMONKS_MAX_RESPONSE_BYTES"):
        monkeypatch.delenv(name, raising=False)
    config = SportmonksConfig.from_env()
    assert (config.timeout_seconds, config.max_retries, config.backoff_seconds, config.max_response_bytes) == (15, 3, .5, 4 * 1024 * 1024)


def test_config_environment(monkeypatch):
    monkeypatch.setenv("SPORTMONKS_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("SPORTMONKS_MAX_RETRIES", "4")
    assert SportmonksConfig.from_env().timeout_seconds == 2.5


@pytest.mark.parametrize("name,value", [("SPORTMONKS_TIMEOUT_SECONDS", "bad"), ("SPORTMONKS_MAX_RETRIES", "-1")])
def test_invalid_numeric(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(SportmonksConfigurationError): SportmonksConfig.from_env()


def raw_response(payload=b'{"data": []}', *, headers=None, status=200, chunks=None):
    raw = MagicMock(status_code=status, headers=headers or {})
    raw.iter_content.return_value = iter(chunks if chunks is not None else [payload])
    return raw


def test_requests_transport_query_timeout_and_json():
    raw = raw_response(headers={"X-Test":"yes"})
    session = MagicMock(); session.request.return_value = raw
    result = RequestsTransport(session).request("GET", "https://example.test", params={"x":1}, timeout=7)
    session.request.assert_called_once_with("GET", "https://example.test", params={"x":1}, timeout=7, allow_redirects=False, stream=True)
    assert result.body == {"data": []}
    raw.close.assert_called_once()


def test_transport_non_json_fails_once():
    raw = raw_response(b"not json")
    session = MagicMock(); session.request.return_value = raw
    with pytest.raises(SportmonksResponseError): RequestsTransport(session).request("GET", "x", params={}, timeout=1)


def test_token_only_in_sanctioned_query_and_redacted():
    fake = FakeTransport([response({"data": []})])
    client = SportmonksClient(SportmonksConfig(api_token="TOP-SECRET"), transport=fake)
    client.leagues()
    assert fake.calls[0][2]["api_token"] == "TOP-SECRET"
    assert "TOP-SECRET" not in str(SportmonksConfigurationError("failed"))


def test_transport_disables_redirects_for_authenticated_requests():
    session = MagicMock()
    raw = raw_response()
    session.request.return_value = raw
    RequestsTransport(session).request("GET", "https://host/path", params={"api_token": "SECRET"}, timeout=1)
    assert session.request.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("size", [15, 16])
def test_response_body_at_or_under_limit(size):
    payload = b'"' + (b"x" * (size - 2)) + b'"'
    raw = raw_response(payload)
    session = MagicMock(); session.request.return_value = raw
    assert RequestsTransport(session, max_response_bytes=16).request(
        "GET", "https://host/path", params={}, timeout=1
    ).body == "x" * (size - 2)


def test_streamed_body_one_byte_over_stops_and_closes():
    raw = raw_response(chunks=[b'"1234567', b'890123456', b'"'])
    session = MagicMock(); session.request.return_value = raw
    with pytest.raises(SportmonksResponseSizeError):
        RequestsTransport(session, max_response_bytes=16).request(
            "GET", "https://host/path", params={}, timeout=1
        )
    assert raw.iter_content.return_value.__length_hint__() == 1
    raw.close.assert_called_once()


@pytest.mark.parametrize("headers", [
    {"Content-Length": "99"}, {"Content-Length": "malformed"}, {},
    {"Transfer-Encoding": "chunked"}, {"Content-Length": "1"},
])
def test_declared_missing_chunked_malformed_or_misleading_lengths(headers):
    raw = raw_response(b'{"data":[]}', headers=headers, chunks=[b'{"data":', b'[]}'])
    session = MagicMock(); session.request.return_value = raw
    if headers.get("Content-Length") == "99":
        with pytest.raises(SportmonksResponseSizeError):
            RequestsTransport(session, max_response_bytes=16).request("GET", "x", params={}, timeout=1)
        raw.iter_content.assert_not_called()
    else:
        assert RequestsTransport(session, max_response_bytes=16).request(
            "GET", "x", params={}, timeout=1
        ).body == {"data": []}
    raw.close.assert_called_once()


def test_response_size_error_is_secret_safe_and_not_retried():
    token = "BODY-LIMIT-SECRET"
    raw = raw_response(headers={"Content-Length": "99"})
    session = MagicMock(); session.request.return_value = raw
    transport = RequestsTransport(session, max_response_bytes=16)
    client = SportmonksClient(SportmonksConfig(api_token=token), transport=transport)
    with pytest.raises(SportmonksResponseSizeError) as captured:
        client.leagues()
    assert session.request.call_count == 1
    assert token not in "".join(traceback.format_exception(captured.value))


@pytest.mark.parametrize("value", ["0", "-1", str(64 * 1024 * 1024 + 1)])
def test_response_limit_bounds(monkeypatch, value):
    monkeypatch.setenv("SPORTMONKS_MAX_RESPONSE_BYTES", value)
    with pytest.raises(SportmonksConfigurationError):
        SportmonksConfig.from_env()


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
