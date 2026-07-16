"""Provider-neutral, deterministic name normalization."""
from __future__ import annotations

import re
import unicodedata

_SPECIALS = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "ß": "ss"})


def normalize_name(value: str) -> str:
    """NFKD-fold accents, case and punctuation, then collapse whitespace."""
    folded = unicodedata.normalize("NFKD", value.translate(_SPECIALS).casefold())
    unaccented = "".join(c for c in folded if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w]+", " ", unaccented, flags=re.UNICODE).split())


def surname(value: str) -> str:
    parts = normalize_name(value).split()
    return parts[-1] if parts else ""
