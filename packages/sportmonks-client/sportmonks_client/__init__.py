"""Sportmonks provider adapter boundary (FI-3, live assumptions unverified)."""

from .client import SportmonksClient
from .config import SportmonksConfig

__all__ = ["SportmonksClient", "SportmonksConfig"]
