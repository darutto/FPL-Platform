"""
tests/test_owned_store_sync.py
==============================
Unit tests for the startup owned-store R2 sync module
(``fpl_grounded_assistant.owned_store_sync``).

Delivery model under test (FROZEN): startup sync of the owned parquet
store from Cloudflare R2, fail-soft. The server starts even if sync fails;
the fallback stays inert until a successful sync has landed local files.

All R2 / boto3 access is mocked at the ``_make_r2_client`` boundary (or via
``boto3.client``). These tests make NO real network calls and require NO
real R2 credentials.

Scenarios
---------
(a) sync disabled by default            -> sync_enabled() is False
(b) sync-enabled flag parsing            -> truthy/falsy table (parametrized)
(c) sync happy path                      -> ok, 6 files, merged_at, staleness
(d) fail-soft on missing creds           -> ok=False, error set, NO raise
(e) fail-soft on S3 download error       -> ok=False, error set, NO raise
(f) partial parquet missing              -> ok=False (incomplete), NO raise
(g) publish happy path                   -> ok, upload_file per local file
(h) freshness surfaced                   -> staleness_hours from merged_at
"""
from __future__ import annotations

import datetime as _dt
import json
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# sys.path setup (mirror the importlib file-loading pattern used by
# tests/test_fixtures_fallback.py) so cross-package imports inside
# owned_store_sync.py (notably ``fpl_historical.paths``) resolve. We
# deliberately avoid importing the ``fpl_grounded_assistant`` package because
# its __init__.py pulls the whole dispatcher + harness graph that is
# unrelated to this module.
# ---------------------------------------------------------------------------
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))                      # tests/
_PKG  = _os.path.dirname(_HERE)                                           # fpl-grounded-assistant/
_PKGS = _os.path.dirname(_PKG)                                            # packages/
for _pkg in [
    _PKG,
    _os.path.join(_PKGS, "fpl-api-client"),
    _os.path.join(_PKGS, "fpl-data-core"),
    _os.path.join(_PKGS, "fpl-player-registry"),
    _os.path.join(_PKGS, "fpl-query-tools"),
    _os.path.join(_PKGS, "fpl-tool-contract"),
    _os.path.join(_PKGS, "fpl-tool-runner"),
    _os.path.join(_PKGS, "fpl-captain-engine"),
    _os.path.join(_PKGS, "fpl-pipeline"),
    _os.path.join(_PKGS, "fpl-historical"),
]:
    if _pkg not in _sys.path:
        _sys.path.insert(0, _pkg)

import importlib.util as _ilu

_PKG_DIR = _os.path.join(_PKG, "fpl_grounded_assistant")
_MODULE_PATH = _os.path.join(_PKG_DIR, "owned_store_sync.py")

# Skip the whole module cleanly if Implementer A's module is not present yet.
pytestmark = pytest.mark.skipif(
    not _os.path.exists(_MODULE_PATH),
    reason="owned_store_sync.py not yet committed by Implementer A",
)


def _load_module(name: str, filename: str):
    spec = _ilu.spec_from_file_location(name, _os.path.join(_PKG_DIR, filename))
    assert spec is not None and spec.loader is not None
    mod = _ilu.module_from_spec(spec)
    _sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        _sys.modules.pop(name, None)
        raise
    return mod


# Only attempt to load when the file exists; otherwise pytestmark skips all.
if _os.path.exists(_MODULE_PATH):
    mod = _load_module("fpl_grounded_assistant.owned_store_sync", "owned_store_sync.py")
else:  # pragma: no cover - skip guard
    mod = None


# ---------------------------------------------------------------------------
# Constants matching the frozen interface
# ---------------------------------------------------------------------------
_PARQUET_NAMES = ["players", "teams", "events", "fixtures", "player_gw_stats"]
_ALL_ENV = [
    "OWNED_STORE_SYNC_ENABLED",
    "OWNED_STORE_R2_ENDPOINT",
    "OWNED_STORE_R2_BUCKET",
    "OWNED_STORE_R2_ACCESS_KEY_ID",
    "OWNED_STORE_R2_SECRET_ACCESS_KEY",
    "OWNED_STORE_R2_PREFIX",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Clear all OWNED_STORE_* env vars so host env never leaks into a test,
    and reset the module-level last-sync result between tests.
    """
    for var in _ALL_ENV:
        monkeypatch.delenv(var, raising=False)
    # Reset module-level last result if the module exposes it.
    if mod is not None and hasattr(mod, "_LAST_SYNC_RESULT"):
        monkeypatch.setattr(mod, "_LAST_SYNC_RESULT", None)
    yield


@pytest.fixture
def _isolated_root(tmp_path, monkeypatch):
    """Point fpl_historical at an isolated tmp root so any local writes/reads
    happen under tmp_path, never the repo's data dir.
    """
    monkeypatch.setenv("FPL_HISTORICAL_ROOT", str(tmp_path))
    return tmp_path


def _enable_r2(monkeypatch):
    """Set a full, fake R2 env (enabled + creds + endpoint + bucket)."""
    monkeypatch.setenv("OWNED_STORE_SYNC_ENABLED", "1")
    monkeypatch.setenv("OWNED_STORE_R2_ENDPOINT", "https://fake.r2.cloudflarestorage.com")
    monkeypatch.setenv("OWNED_STORE_R2_BUCKET", "fpl-owned")
    monkeypatch.setenv("OWNED_STORE_R2_ACCESS_KEY_ID", "FAKEKEY")
    monkeypatch.setenv("OWNED_STORE_R2_SECRET_ACCESS_KEY", "FAKESECRET")


def _merged_at_str(hours_ago: float = 2.0) -> str:
    """Build a pointer merged_at string ``hours_ago`` hours in the past,
    in the on-disk timestamp format ``%Y-%m-%dT%H-%M-%SZ`` (colons replaced).
    """
    when = _dt.datetime.now(tz=_dt.timezone.utc) - _dt.timedelta(hours=hours_ago)
    return when.strftime("%Y-%m-%dT%H-%M-%SZ")


def _pointer_payload(merged_at: str) -> dict:
    return {
        "merged_at": merged_at,
        "baseline_captured_at": merged_at,
        "incremental_count": 1,
        "row_counts": {"players": 712, "teams": 20, "events": 38},
    }


def _downloading_client(merged_at: str, *, fail_on: set[str] | None = None) -> MagicMock:
    """Build a MagicMock S3 client whose ``download_file(bucket, key, dest)``
    side-effect writes a plausible file at ``dest``.

    The pointer key (ending in ``_owned_latest.json``) is written as JSON with
    the supplied ``merged_at``. Parquet keys are written as small binary stubs.

    ``fail_on`` is a set of object-key substrings; if a downloaded key matches
    any of them the side-effect raises (to simulate a not-found / S3 error).
    """
    fail_on = fail_on or set()
    client = MagicMock(name="s3_client")

    def _download(*args, **kwargs):
        # boto3 signature: download_file(Bucket, Key, Filename) positional
        # or keyword. Be tolerant of both.
        if args:
            # positional: (bucket, key, dest) or client.download_file shape
            if len(args) >= 3:
                key, dest = args[1], args[2]
            else:  # defensive
                key, dest = args[-2], args[-1]
        else:
            key = kwargs.get("Key") or kwargs.get("key")
            dest = kwargs.get("Filename") or kwargs.get("dest") or kwargs.get("filename")
        key = str(key)
        dest = str(dest)

        for token in fail_on:
            if token in key:
                raise RuntimeError(f"simulated S3 download error for key={key}")

        # Ensure parent dir exists, then write the file.
        import os as _o
        _o.makedirs(_o.path.dirname(dest), exist_ok=True)
        if dest.endswith(".json") or key.endswith("_owned_latest.json"):
            with open(dest, "w", encoding="utf-8") as fh:
                json.dump(_pointer_payload(merged_at), fh)
        else:
            with open(dest, "wb") as fh:
                fh.write(b"PAR1-fake-parquet-bytes")

    client.download_file.side_effect = _download
    return client


# ===========================================================================
# (a) sync disabled by default
# ===========================================================================

def test_a_sync_disabled_by_default(monkeypatch):
    """With OWNED_STORE_SYNC_ENABLED unset, sync_enabled() is False.

    The lifespan wiring (Implementer A's fpl_server) gates the startup call
    on this; here we assert the gate itself is closed by default so a server
    started without explicit opt-in never attempts a sync.
    """
    monkeypatch.delenv("OWNED_STORE_SYNC_ENABLED", raising=False)
    assert mod.sync_enabled() is False


# ===========================================================================
# (b) sync-enabled flag parsing
# ===========================================================================

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        ("0", False),
        ("", False),
        ("no", False),
        ("off", False),
    ],
)
def test_b_flag_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("OWNED_STORE_SYNC_ENABLED", raw)
    assert mod.sync_enabled() is expected


# ===========================================================================
# (c) sync happy path
# ===========================================================================

def test_c_sync_happy_path(monkeypatch, _isolated_root):
    _enable_r2(monkeypatch)
    merged_at = _merged_at_str(hours_ago=2.0)
    client = _downloading_client(merged_at)
    monkeypatch.setattr(mod, "_make_r2_client", lambda: client)

    result = mod.sync_owned_store_from_r2()

    assert result.ok is True, f"expected ok, got error={result.error!r}"
    assert result.files_synced == 6, "expected pointer + 5 parquet = 6 files"
    assert result.merged_at is not None
    assert isinstance(result.staleness_hours, float)
    assert result.staleness_hours >= 0.0
    assert result.error is None

    # get_last_sync_result() returns the same result object/value.
    assert mod.get_last_sync_result() == result


# ===========================================================================
# (d) fail-soft on missing creds
# ===========================================================================

def test_d_fail_soft_missing_creds(monkeypatch, _isolated_root):
    """Enabled, but R2 creds/env absent so _make_r2_client raises. The sync
    must return ok=False with an error string and must NOT propagate.
    """
    monkeypatch.setenv("OWNED_STORE_SYNC_ENABLED", "1")
    # Intentionally do NOT set endpoint/bucket/keys.

    def _raise():
        raise RuntimeError("OWNED_STORE_R2_ENDPOINT is not set")

    monkeypatch.setattr(mod, "_make_r2_client", _raise)

    # Must not raise.
    result = mod.sync_owned_store_from_r2()
    assert result.ok is False
    assert result.error is not None and result.error != ""


# ===========================================================================
# (e) fail-soft on S3 download error
# ===========================================================================

def test_e_fail_soft_download_error(monkeypatch, _isolated_root):
    """Pointer download raises -> ok=False, error set, no raise."""
    _enable_r2(monkeypatch)
    merged_at = _merged_at_str()
    # Fail on the pointer object key itself.
    client = _downloading_client(merged_at, fail_on={"_owned_latest.json"})
    monkeypatch.setattr(mod, "_make_r2_client", lambda: client)

    result = mod.sync_owned_store_from_r2()
    assert result.ok is False
    assert result.error is not None and result.error != ""


# ===========================================================================
# (f) partial parquet missing
# ===========================================================================

def test_f_partial_parquet_missing(monkeypatch, _isolated_root):
    """Pointer + 4 parquet succeed; one parquet raises not-found. The
    invariant that matters: NO raise, and ok is False because the sync is
    incomplete.
    """
    _enable_r2(monkeypatch)
    merged_at = _merged_at_str()
    # Fail specifically on the player_gw_stats parquet.
    client = _downloading_client(merged_at, fail_on={"player_gw_stats.parquet"})
    monkeypatch.setattr(mod, "_make_r2_client", lambda: client)

    result = mod.sync_owned_store_from_r2()

    # Hard invariants (resilient to A's exact per-file accounting):
    assert result.ok is False, "incomplete sync must report ok=False"
    assert result.error is not None and result.error != ""
    # files_synced should reflect the successful downloads (pointer + 4 parquet)
    # but never exceed the full set of 6.
    assert 0 <= result.files_synced <= 6


# ===========================================================================
# (g) publish happy path
# ===========================================================================

def test_g_publish_happy_path(monkeypatch, _isolated_root):
    """Create a local pointer + parquet files, mock upload_file, and confirm
    publish uploads once per existing local file and reports ok + merged_at.
    """
    from fpl_historical import paths as _paths

    season = _paths.CURRENT_SEASON
    merged_dir = _paths.merged_parquet_dir(season)
    merged_dir.mkdir(parents=True, exist_ok=True)
    pointer_path = _paths.owned_latest_pointer_path(season)
    pointer_path.parent.mkdir(parents=True, exist_ok=True)

    merged_at = _merged_at_str(hours_ago=1.0)
    pointer_path.write_text(json.dumps(_pointer_payload(merged_at)), encoding="utf-8")
    for name in _PARQUET_NAMES:
        (merged_dir / f"{name}.parquet").write_bytes(b"PAR1-fake-parquet-bytes")

    _enable_r2(monkeypatch)
    client = MagicMock(name="s3_client")
    monkeypatch.setattr(mod, "_make_r2_client", lambda: client)

    result = mod.publish_owned_store_to_r2()

    assert result.ok is True, f"expected ok, got error={result.error!r}"
    assert result.merged_at is not None
    # One upload per existing local file: pointer + 5 parquet = 6.
    expected_local_files = 1 + len(_PARQUET_NAMES)
    assert client.upload_file.call_count == expected_local_files


# ===========================================================================
# (h) freshness surfaced
# ===========================================================================

def test_h_freshness_surfaced(monkeypatch, _isolated_root):
    """After a happy-path sync with merged_at ~2h in the past, staleness_hours
    on the result should be ~2.0 (computed from the pointer's merged_at).
    """
    _enable_r2(monkeypatch)
    merged_at = _merged_at_str(hours_ago=2.0)
    client = _downloading_client(merged_at)
    monkeypatch.setattr(mod, "_make_r2_client", lambda: client)

    result = mod.sync_owned_store_from_r2()

    assert result.ok is True
    assert result.staleness_hours is not None
    # Allow generous tolerance for clock/processing skew.
    assert abs(result.staleness_hours - 2.0) < 0.5, (
        f"staleness_hours={result.staleness_hours} not within 0.5h of 2.0"
    )
