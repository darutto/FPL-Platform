"""
fpl_grounded_assistant.input_normalizer
========================================
Phase M1 (MCP_architecture): Input normalizer.

`normalize(text) -> NormalizedInput` returns a discriminated-union dict
describing how the input boundary should treat the user's raw string.

The four kinds are:
    * ResourceInput  — `@<resource>` (or aliased variant). Carries the raw
                       alias as typed (for telemetry) plus the canonical
                       resource key (or None when alias is unknown).
    * PromptInput    — `/<prompt> [args...]`. The argument string is
                       carried verbatim — argument parsing is M2's job.
    * TextInput      — plain natural-language text (fall-through to route()).
    * RejectedInput  — empty after trim/normalize, or pathological input
                       the boundary refuses to forward.

Design rules
------------
* Deterministic, LLM-free, side-effect free.
* Trim + NFC unicode normalize.
* Spanish honorific strip (e.g. leading "oye,", "porfa,", "por favor,").
  This is intentionally narrow — it only strips friendly call-outs, not
  semantic content.
* `@` and `/` prefixes are detected only when they appear at position 0
  AFTER honorific strip. A `@` mid-sentence does not trigger resource mode.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Union

from .intent_aliases import resolve_resource


# ---------------------------------------------------------------------------
# Honorific / filler prefixes (Spanish-first, light English)
# ---------------------------------------------------------------------------
# Only strip when followed by punctuation or whitespace so we don't eat
# meaningful tokens (e.g. "oye" inside a player name — none today, but
# defensive). The strip is iterative until no honorific matches.

_HONORIFICS: tuple[str, ...] = (
    "oye",
    "porfa",
    "por favor",
    "porfis",
    "amigo",
    "hola",
    "hey",
    "please",
)


def _strip_honorifics(text: str) -> str:
    s = text
    changed = True
    while changed:
        changed = False
        ls = s.lstrip()
        ls_lower = ls.lower()
        for h in _HONORIFICS:
            if ls_lower.startswith(h):
                # next char (if any) must be punctuation or whitespace
                after_idx = len(h)
                if len(ls) == after_idx or ls[after_idx] in " \t,.;:!?":
                    # consume the honorific and one trailing punctuation char
                    rest = ls[after_idx:]
                    if rest[:1] in (",", ".", ";", ":", "!", "?"):
                        rest = rest[1:]
                    s = rest.lstrip()
                    changed = True
                    break
    return s


# ---------------------------------------------------------------------------
# NormalizedInput discriminated union
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResourceInput:
    kind: str = "resource"
    raw_alias: str = ""           # what the user typed after `@`, NFC + casefolded
    canonical: str | None = None  # canonical resource key, or None if unknown
    original: str = ""            # original input (post trim/NFC, pre-prefix-strip)


@dataclass(frozen=True)
class PromptInput:
    kind: str = "prompt"
    name: str = ""                # prompt name (lowercased, no leading `/`)
    args_text: str = ""           # everything after the prompt name
    original: str = ""            # original normalized input


@dataclass(frozen=True)
class TextInput:
    kind: str = "text"
    text: str = ""                # normalized natural-language text
    original: str = ""            # same as `text` (kept for symmetry)


@dataclass(frozen=True)
class RejectedInput:
    kind: str = "rejected"
    reason: str = ""              # e.g. "empty"


NormalizedInput = Union[ResourceInput, PromptInput, TextInput, RejectedInput]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def normalize(text: str) -> NormalizedInput:
    """Normalize *text* and classify it as resource/prompt/text/rejected."""
    if not isinstance(text, str):
        return RejectedInput(reason="non_string")

    # 1. NFC unicode normalize + trim
    nfc = unicodedata.normalize("NFC", text).strip()
    if not nfc:
        return RejectedInput(reason="empty")

    # 2. Strip Spanish honorifics / friendly call-outs
    cleaned = _strip_honorifics(nfc)
    if not cleaned:
        return RejectedInput(reason="empty_after_honorific_strip")

    # 3. Prefix detection (only at position 0)
    if cleaned.startswith("@"):
        # Tokenize: first whitespace ends the alias. `@resource extra` is
        # treated as an unknown shape: M1 resources are argument-free, so
        # any trailing tokens are ignored (we still resolve the alias).
        body = cleaned[1:].strip()
        if not body:
            return ResourceInput(raw_alias="", canonical=None, original=cleaned)
        # split off optional trailing tokens
        first = body.split()[0]
        canonical = resolve_resource(first)
        return ResourceInput(
            raw_alias=first.casefold(),
            canonical=canonical,
            original=cleaned,
        )

    if cleaned.startswith("/"):
        body = cleaned[1:].strip()
        if not body:
            return PromptInput(name="", args_text="", original=cleaned)
        parts = body.split(None, 1)
        name = parts[0].casefold()
        args_text = parts[1] if len(parts) > 1 else ""
        return PromptInput(name=name, args_text=args_text, original=cleaned)

    return TextInput(text=cleaned, original=cleaned)
