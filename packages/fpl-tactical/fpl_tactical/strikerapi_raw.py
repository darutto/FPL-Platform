"""
fpl_tactical.strikerapi_raw
===========================
Never pay twice: every response the shot source is paid for is kept, as it
arrived, BEFORE anything reads it. Whatever parsing or validation says later,
a response that is kept here is never requested again.

Local: ``seasons/<season>/strikerapi/raw/<name>.json`` (git-ignored).
R2 (when given): ``<prefix>tactical/<season>/strikerapi/raw/<name>.json`` --
private. Neither the publish step nor the server's sync ever touches ``raw/``.

Names: ``<game_id>``, ``team_<CODE>``, ``list_games_<offset>``.

To force ONE refetch on purpose (for example the source answered a match with
no shots), delete that file, both on R2 and locally; it costs its credits again.

A cache that cannot be read or written is an error, never a miss: treating it
as a miss would pay again.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from fpl_tactical.paths import SOURCE_STRIKERAPI, source_dir

_PROBE = "_writable"


class RawCacheError(RuntimeError):
    """The raw cache could not be read or written; nothing may be fetched."""


def raw_name(tool: str, request: dict) -> str:
    if tool == "list_games":
        return f"list_games_{int(request.get('offset') or 0)}"
    if "game_id" in request:
        return str(request["game_id"])
    return f"team_{request['team']}"


def _is_missing(exc: Exception) -> bool:
    if isinstance(exc, FileNotFoundError):
        return True
    code = str((getattr(exc, "response", None) or {}).get("Error", {}).get("Code", ""))
    return code in ("404", "NoSuchKey", "NotFound")


class RawCache:
    """Kept responses for one season. *r2* is a boto3-like client, or None for local only."""

    def __init__(self, season: str, r2: object | None = None, bucket: str = "", key_base: str = ""):
        self.dir: Path = source_dir(season, SOURCE_STRIKERAPI) / "raw"
        self.r2, self.bucket, self.key_base = r2, bucket, key_base

    def _path(self, name: str) -> Path:
        if not name.replace("_", "").isalnum():
            raise RawCacheError(f"unsafe raw cache name {name!r}")
        return self.dir / f"{name}.json"

    def _upload(self, path: Path) -> None:
        try:
            self.r2.upload_file(str(path), self.bucket, self.key_base + path.name)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            raise RawCacheError(f"could not keep {path.name} on R2: {type(exc).__name__}") from None

    def _write_local(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(str(tmp), str(path))

    def get(self, name: str) -> dict | None:
        """The kept envelope ``{fetched_at, tool, request, body}``, or None when never fetched."""
        path = self._path(name)
        if path.exists():
            if self.r2 is not None and name != _PROBE:
                self._upload(path)  # heals an earlier upload that failed
        elif self.r2 is None:
            return None
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.part")
            try:
                self.r2.download_file(self.bucket, self.key_base + path.name, str(tmp))  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001
                if _is_missing(exc):
                    return None
                raise RawCacheError(f"could not read {path.name} from R2: {type(exc).__name__}") from None
            os.replace(str(tmp), str(path))
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            raise RawCacheError(f"kept response {path.name} is not readable; fix or delete it") from None

    def put(self, tool: str, request: dict, body: str, fetched_at: datetime) -> None:
        """Keep a response verbatim: local first, then R2 (which must succeed)."""
        path = self._path(raw_name(tool, request))
        self._write_local(path, json.dumps(
            {"fetched_at": fetched_at.isoformat(), "tool": tool, "request": request, "body": body}))
        if self.r2 is not None:
            self._upload(path)

    def check_writable(self) -> None:
        """Called before the first paid request: never buy what cannot be kept."""
        path = self._path(_PROBE)
        try:
            self._write_local(path, "{}")
        except OSError as exc:
            raise RawCacheError(f"raw cache is not writable: {type(exc).__name__}") from None
        if self.r2 is not None:
            self._upload(path)
