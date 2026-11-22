"""scripts/eo_smoke.py: three requests, status/timing only (fetch mocked, synthetic ids)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "eo_smoke.py"
spec = importlib.util.spec_from_file_location("eo_smoke", SCRIPT)
eo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eo)

BOOT = {"events": [{"id": 1, "finished": True}, {"id": 2, "finished": True}, {"id": 3, "finished": False}]}
STAND = {"standings": {"results": [{"entry": 111, "player_name": "Secret Name"}]}}


def _fetch(overrides=None, log=None):
    overrides = overrides or {}

    def fetch(url):
        if log is not None:
            log.append(url)
        for key, value in overrides.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        if "bootstrap" in url:
            return 200, BOOT
        if "standings" in url:
            return 200, STAND
        return 200, {"picks": []}

    return fetch


def test_three_requests_and_pass(capsys):
    urls: list[str] = []
    assert eo.run(_fetch(log=urls)) == 0
    assert len(urls) == 3
    assert urls[2].endswith("/entry/111/event/2/picks/")  # last FINISHED gw
    out = capsys.readouterr().out
    assert "PASS" in out and "status=200" in out
    assert "Secret Name" not in out and "111" not in out  # no names or ids logged


def test_failed_standings_skips_picks(capsys):
    urls: list[str] = []
    assert eo.run(_fetch({"standings": (403, None)}, urls)) == 1
    assert len(urls) == 2
    assert "status=403" in capsys.readouterr().out


def test_network_error_is_logged_by_class_only(capsys):
    assert eo.run(_fetch({"bootstrap": ConnectionError("TimeoutError")})) == 1
    out = capsys.readouterr().out
    assert "status=None" in out and "error=TimeoutError" in out
