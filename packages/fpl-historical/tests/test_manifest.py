"""
tests/test_manifest.py
======================
Tests for fpl_historical.manifest
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpl_historical.manifest import (
    Manifest,
    read_manifest,
    sha256_bytes,
    write_manifest,
)


class TestSha256Bytes:
    def test_stable_for_identical_bytes(self):
        """sha256_bytes returns the same hex string for identical input."""
        data = b"hello world"
        assert sha256_bytes(data) == sha256_bytes(data)

    def test_different_for_different_bytes(self):
        """sha256_bytes returns different hex strings for different input."""
        assert sha256_bytes(b"foo") != sha256_bytes(b"bar")

    def test_known_value(self):
        """sha256_bytes of empty bytes matches known SHA-256 hex."""
        import hashlib
        expected = hashlib.sha256(b"").hexdigest()
        assert sha256_bytes(b"") == expected

    def test_returns_hex_string(self):
        """sha256_bytes returns a lowercase hex string of length 64."""
        result = sha256_bytes(b"test")
        assert isinstance(result, str)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


class TestManifestRoundTrip:
    def _make_manifest(self) -> Manifest:
        return Manifest(
            schema_version=1,
            season="2025-2026",
            status="complete",
            captured_at_utc="2026-05-25T14:22:03Z",
            git_sha="725d4b4",
            fpl_endpoints={
                "bootstrap-static": {
                    "url": "https://fantasy.premierleague.com/api/bootstrap-static/",
                    "status": 200,
                    "bytes": 412034,
                    "sha256": "abc123",
                },
                "fixtures": {
                    "url": "https://fantasy.premierleague.com/api/fixtures/",
                    "status": 200,
                    "bytes": 84221,
                    "sha256": "def456",
                },
                "element-summary": {
                    "count": 712,
                    "failures": [],
                    "sha256_aggregate": "ghi789",
                },
            },
            current_event_id=38,
            elapsed_seconds=187.4,
        )

    def test_round_trip_preserves_all_fields(self, tmp_path):
        """write_manifest + read_manifest round-trip preserves every field."""
        m = self._make_manifest()
        write_manifest(tmp_path, m)
        restored = read_manifest(tmp_path)

        assert restored.schema_version == m.schema_version
        assert restored.season == m.season
        assert restored.status == m.status
        assert restored.captured_at_utc == m.captured_at_utc
        assert restored.git_sha == m.git_sha
        assert restored.fpl_endpoints == m.fpl_endpoints
        assert restored.current_event_id == m.current_event_id
        assert restored.elapsed_seconds == m.elapsed_seconds

    def test_manifest_json_uses_indent2(self, tmp_path):
        """write_manifest produces JSON with indent=2."""
        m = self._make_manifest()
        write_manifest(tmp_path, m)
        raw = (tmp_path / "_manifest.json").read_text(encoding="utf-8")
        # indent=2 means lines start with exactly 2 spaces at first level
        assert '  "season"' in raw

    def test_manifest_file_is_utf8(self, tmp_path):
        """write_manifest writes UTF-8 encoded file."""
        m = self._make_manifest()
        write_manifest(tmp_path, m)
        path = tmp_path / "_manifest.json"
        # Should parse without error when read as UTF-8
        content = path.read_bytes().decode("utf-8")
        data = json.loads(content)
        assert data["season"] == "2025-2026"

    def test_complete_with_gaps_status_round_trips(self, tmp_path):
        """Status literal 'complete_with_gaps' round-trips correctly."""
        m = self._make_manifest()
        m.status = "complete_with_gaps"
        write_manifest(tmp_path, m)
        restored = read_manifest(tmp_path)
        assert restored.status == "complete_with_gaps"

    def test_failed_status_round_trips(self, tmp_path):
        """Status literal 'failed' round-trips correctly."""
        m = self._make_manifest()
        m.status = "failed"
        write_manifest(tmp_path, m)
        restored = read_manifest(tmp_path)
        assert restored.status == "failed"

    def test_none_current_event_id_round_trips(self, tmp_path):
        """current_event_id=None round-trips correctly."""
        m = self._make_manifest()
        m.current_event_id = None
        write_manifest(tmp_path, m)
        restored = read_manifest(tmp_path)
        assert restored.current_event_id is None
