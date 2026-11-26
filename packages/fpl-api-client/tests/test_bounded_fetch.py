"""The opt-in bounded fetch, against a real local server: the deadline holds whatever the server does."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest
import requests

from fpl_api_client import fpl_client


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        server = self.server
        server.hits += 1
        mode = server.modes[min(server.hits, len(server.modes)) - 1]
        if mode == "500":
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        if mode == "ok":
            body = json.dumps({"ok": True}).encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        # "trickle": a byte every 0.1 s, so no single read ever times out.
        self.send_header("Content-Length", "100000")
        self.end_headers()
        try:
            while not server.stop.is_set():
                self.wfile.write(b" ")
                self.wfile.flush()
                time.sleep(0.1)
        except OSError:
            server.client_gone.set()


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.daemon_threads = True
    httpd.handle_error = lambda *args: None  # the aborted connection is what the test causes
    httpd.hits, httpd.modes = 0, ["ok"]
    httpd.stop, httpd.client_gone = threading.Event(), threading.Event()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    httpd.url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    yield httpd
    httpd.stop.set()
    httpd.shutdown()
    httpd.server_close()


def _get(server, budget, **kwargs):
    session = requests.Session()
    session.trust_env = False  # no proxy between the test and its own server
    return fpl_client.fetch_json_bounded(server.url, session=session, deadline=time.monotonic() + budget, **kwargs)


def test_returns_the_payload(server):
    assert _get(server, 3.0) == {"ok": True}
    assert server.hits == 1


@pytest.mark.parametrize("protocol", ["HTTP/1.0", "HTTP/1.1"])
def test_a_trickling_body_is_cut_at_the_deadline_and_the_socket_closed(server, protocol, monkeypatch):
    monkeypatch.setattr(_Handler, "protocol_version", protocol)  # closing, and kept alive as FPL serves
    server.modes = ["trickle"]
    started = time.monotonic()
    with pytest.raises(requests.RequestException):
        _get(server, 1.0)
    assert time.monotonic() - started < 2.5
    assert server.client_gone.wait(2.0), "the server never saw the connection close"


def test_a_500_is_retried_once(server):
    server.modes = ["500"]
    with pytest.raises(requests.HTTPError):
        _get(server, 3.0)
    assert server.hits == 2


def test_the_retry_can_succeed(server):
    server.modes = ["500", "ok"]
    assert _get(server, 3.0) == {"ok": True}


def test_a_passed_deadline_sends_nothing(server):
    with pytest.raises(fpl_client.FetchDeadlineExceeded):
        _get(server, -1.0)
    assert server.hits == 0


@pytest.mark.parametrize("call,args", [(fpl_client.get_event_live, (3,)), (fpl_client.get_all_fixtures, ())])
def test_callers_that_do_not_opt_in_keep_the_old_path(call, args):
    with patch.object(fpl_client, "fetch_json", return_value=[]) as old, \
            patch.object(fpl_client, "fetch_json_bounded") as new:
        call(*args)
    assert old.call_count == 1 and old.call_args.kwargs == {}
    new.assert_not_called()


@pytest.mark.parametrize("call,args", [(fpl_client.get_event_live, (3,)), (fpl_client.get_all_fixtures, ())])
def test_session_and_deadline_opt_in(call, args):
    session = object()
    with patch.object(fpl_client, "fetch_json") as old, \
            patch.object(fpl_client, "fetch_json_bounded", return_value=[]) as new:
        call(*args, session=session, deadline=12.0)
    old.assert_not_called()
    assert new.call_args.kwargs == {"session": session, "deadline": 12.0}
