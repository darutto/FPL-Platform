"""Sportmonks provider adapter boundary (FI-3, live assumptions unverified)."""

from .client import SportmonksClient
from .config import SportmonksConfig
from .errors import SportmonksResponseSizeError

__all__ = ["SportmonksClient", "SportmonksConfig", "SportmonksResponseSizeError"]
