"""Narrow provider-neutral remote store and deterministic in-memory test adapter."""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import BinaryIO, Protocol

from .errors import ImmutableConflictError, PointerRaceError, RemoteStoreError


@dataclass(frozen=True)
class ObjectMetadata:
    size: int
    sha256: str
    etag: str


@dataclass
class RemoteObject:
    metadata: ObjectMetadata
    stream: BinaryIO


class ArtifactStore(Protocol):
    def head(self, key: str) -> ObjectMetadata | None: ...
    def open_read(self, key: str) -> RemoteObject: ...
    def put_immutable(self, key: str, data: bytes, sha256: str) -> ObjectMetadata: ...
    def put_pointer(self, key: str, data: bytes, expected_etag: str | None) -> ObjectMetadata: ...


class InMemoryArtifactStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.etags: dict[str, str] = {}
        self.operations: list[tuple[str, str]] = []
        self.declared_sizes: dict[str, int] = {}
        self.fail_on: set[tuple[str, str]] = set()

    def _fail(self, op: str, key: str) -> None:
        if (op, key) in self.fail_on:
            raise RemoteStoreError("remote artifact operation failed")

    def head(self, key: str) -> ObjectMetadata | None:
        self._fail("head", key)
        if key not in self.objects:
            return None
        data = self.objects[key]
        return ObjectMetadata(self.declared_sizes.get(key, len(data)), hashlib.sha256(data).hexdigest(), self.etags[key])

    def open_read(self, key: str) -> RemoteObject:
        self._fail("read", key)
        meta = self.head(key)
        if meta is None:
            raise RemoteStoreError("remote artifact is missing")
        self.operations.append(("read", key))
        return RemoteObject(meta, io.BytesIO(self.objects[key]))

    def put_immutable(self, key: str, data: bytes, sha256: str) -> ObjectMetadata:
        self._fail("write", key)
        if hashlib.sha256(data).hexdigest() != sha256:
            raise RemoteStoreError("caller supplied an invalid content hash")
        if key in self.objects and self.objects[key] != data:
            raise ImmutableConflictError("immutable remote artifact conflicts")
        self.objects.setdefault(key, data)
        self.etags.setdefault(key, hashlib.sha256(data).hexdigest())
        self.operations.append(("write", key))
        return self.head(key)  # type: ignore[return-value]

    def put_pointer(self, key: str, data: bytes, expected_etag: str | None) -> ObjectMetadata:
        self._fail("pointer", key)
        current = self.etags.get(key)
        if current != expected_etag:
            raise PointerRaceError("remote active pointer changed concurrently")
        self.objects[key] = data
        self.etags[key] = hashlib.sha256(data).hexdigest()
        self.operations.append(("pointer", key))
        return self.head(key)  # type: ignore[return-value]


class S3ArtifactStore:
    """Lazy S3-compatible adapter; SDK values and errors never cross this boundary."""
    def __init__(self, config) -> None:
        try:
            import boto3
            from botocore.config import Config
            self._client = boto3.client(
                "s3", endpoint_url=config.endpoint, aws_access_key_id=config.access_key_id,
                aws_secret_access_key=config.secret_access_key, region_name=config.region,
                config=Config(connect_timeout=3, read_timeout=10, retries={"max_attempts": 3, "mode": "standard"},
                              s3={"addressing_style": "path" if config.force_path_style else "virtual"}),
            )
        except Exception as exc:
            raise RemoteStoreError("remote artifact client initialization failed") from None
        self._bucket = config.bucket

    def head(self, key: str) -> ObjectMetadata | None:
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}: return None
            raise RemoteStoreError("remote artifact metadata request failed") from None
        metadata = response.get("Metadata", {})
        return ObjectMetadata(int(response["ContentLength"]), metadata.get("sha256", ""), str(response.get("ETag", "")).strip('"'))

    def open_read(self, key: str) -> RemoteObject:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            meta = ObjectMetadata(int(response["ContentLength"]), response.get("Metadata", {}).get("sha256", ""), str(response.get("ETag", "")).strip('"'))
            return RemoteObject(meta, response["Body"])
        except Exception:
            raise RemoteStoreError("remote artifact download failed") from None

    def put_immutable(self, key: str, data: bytes, sha256: str) -> ObjectMetadata:
        existing = self.head(key)
        if existing is not None:
            if existing.sha256 == sha256 and existing.size == len(data): return existing
            raise ImmutableConflictError("immutable remote artifact conflicts")
        try:
            self._client.put_object(Bucket=self._bucket, Key=key, Body=data, Metadata={"sha256": sha256}, IfNoneMatch="*")
            result = self.head(key)
            if result is None: raise RemoteStoreError("remote artifact write was not observable")
            return result
        except ImmutableConflictError: raise
        except Exception:
            raise RemoteStoreError("remote immutable artifact write failed") from None

    def put_pointer(self, key: str, data: bytes, expected_etag: str | None) -> ObjectMetadata:
        kwargs = {"Bucket": self._bucket, "Key": key, "Body": data, "Metadata": {"sha256": hashlib.sha256(data).hexdigest()}}
        kwargs["IfMatch" if expected_etag else "IfNoneMatch"] = expected_etag or "*"
        try:
            self._client.put_object(**kwargs)
            result = self.head(key)
            if result is None: raise RemoteStoreError("remote pointer write was not observable")
            return result
        except Exception:
            raise PointerRaceError("remote active pointer conditional update failed") from None
