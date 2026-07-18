"""Environment-driven server-side configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass

from .errors import SportmonksConfigurationError


@dataclass(frozen=True)
class SportmonksConfig:
    api_token: str | None = None
    base_url: str = "https://api.sportmonks.com/v3/football"
    timeout_seconds: float = 15.0
    max_retries: int = 3
    backoff_seconds: float = 0.5
    max_pages: int = 100
    max_response_bytes: int = 4 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "SportmonksConfig":
        def number(name: str, default: str, cast):
            try:
                value = cast(os.getenv(name, default))
            except ValueError as exc:
                raise SportmonksConfigurationError(f"invalid numeric configuration: {name}") from exc
            if value < 0:
                raise SportmonksConfigurationError(f"configuration must be non-negative: {name}")
            return value
        max_response_bytes = number("SPORTMONKS_MAX_RESPONSE_BYTES", str(4 * 1024 * 1024), int)
        if not 1 <= max_response_bytes <= 64 * 1024 * 1024:
            raise SportmonksConfigurationError(
                "SPORTMONKS_MAX_RESPONSE_BYTES must be between 1 and 67108864"
            )
        return cls(
            api_token=os.getenv("SPORTMONKS_API_TOKEN") or None,
            base_url=os.getenv("SPORTMONKS_BASE_URL", cls.base_url).rstrip("/"),
            timeout_seconds=number("SPORTMONKS_TIMEOUT_SECONDS", "15", float),
            max_retries=number("SPORTMONKS_MAX_RETRIES", "3", int),
            backoff_seconds=number("SPORTMONKS_BACKOFF_SECONDS", "0.5", float),
            max_response_bytes=max_response_bytes,
        )

    def require_token(self) -> str:
        if not self.api_token:
            raise SportmonksConfigurationError("SPORTMONKS_API_TOKEN is required for live authenticated requests")
        return self.api_token
