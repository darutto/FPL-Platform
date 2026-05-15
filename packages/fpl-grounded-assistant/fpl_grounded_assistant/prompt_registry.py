"""
fpl_grounded_assistant.prompt_registry
=======================================
Phase M2 (MCP_architecture): Guided prompt registry.

A prompt is a **typed workflow adapter** over an existing stable
deterministic backend job. It is NOT a free-form text template. Each
``PromptSpec`` declares:

    * argument schema (required, types, per-arg aliases)
    * validation rules (e.g. ``a != b`` for compare)
    * downstream INTENT_* (the deterministic job it satisfies)
    * dispatch mode — ``EXPANSION`` (re-enter route() with canonical text)
                      or ``DISPATCH`` (call run_tool directly so typed
                      args are not lost to text rewriting)

Argument parsing strategy
-------------------------
Each PromptSpec carries a small ``parse`` callable that consumes the raw
``args_text`` from the input normalizer and returns
``(parsed: dict, errors: list[str])``.

Baseline conventions (documented per-prompt below):

    * Single-required-arg prompts (``/capitan``, ``/chips``): the whole
      ``args_text`` (after stripping any ``key=`` flags from the tail)
      becomes the single positional value.

    * Two-required-arg prompts (``/comparar``, ``/transferencia``):
      accept either explicit ``a=X b=Y`` / ``out=X in=Y`` form, or
      positional ``A <connector> B`` where ``<connector>`` is one of
      ``por`` / ``for`` / ``vs`` / ``y`` / ``and`` / ``,``.

    * Optional-arg prompts (``/calendarios``, ``/diferenciales``,
      ``/clasificacion``): accept any ``key=value`` flags interleaved with
      a positional payload. Flags are stripped from the positional payload
      before it is bound to the leading positional argument.

Aliases:
    * Prompt name aliases (e.g. ``/captain`` -> ``/capitan``) live in
      ``intent_aliases.py``.
    * Argument-name aliases live per-``ArgSpec`` in this module
      (e.g. ``out`` accepts ``salida``; ``in`` accepts ``entrada``).

Failure shape
-------------
``validate_and_parse(spec, args_text)`` returns a dict::

    {
        "ok":             bool,
        "args":           dict[str, Any],   # only when ok
        "missing_fields": list[str],        # populated on failure
        "errors":         list[str],        # human-readable hints
    }

The decision router consumes this and translates it into a
``needs_clarification`` outcome on the ``ask_v2()`` response dict.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable

from .dispatcher import (
    INTENT_CAPTAIN_SCORE,
    INTENT_COMPARE_PLAYERS,
    INTENT_TRANSFER_ADVICE,
    INTENT_PLAYER_FIXTURE_RUN,
    INTENT_DIFFERENTIAL_PICKS,
    INTENT_CHIP_ADVICE,
    INTENT_RANK_CANDIDATES,
)


# ---------------------------------------------------------------------------
# Dispatch modes
# ---------------------------------------------------------------------------

MODE_EXPANSION = "expansion"   # build canonical text, re-enter route()
MODE_DISPATCH  = "dispatch"    # call run_tool directly with typed args


# ---------------------------------------------------------------------------
# Argument and prompt specifications
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ArgSpec:
    name:        str
    type:        str                       # "string" | "int" | "float" | "enum"
    required:    bool = False
    aliases:     tuple[str, ...] = ()      # accepted alternate keys for key=value flags
    enum:        tuple[str, ...] | None = None
    min_value:   float | None = None
    max_value:   float | None = None
    default:     Any = None
    description: str = ""


@dataclass(frozen=True)
class PromptSpec:
    name:               str
    label:              str
    argument_schema:    dict[str, ArgSpec]
    validation_rules:   tuple[Callable[[dict[str, Any]], str | None], ...]
    workflow_intent:    str
    mode:               str                  # MODE_EXPANSION | MODE_DISPATCH
    expansion_template: str | None = None    # for MODE_EXPANSION
    parse:              Callable[[str], tuple[dict[str, Any], list[str]]] | None = None
    failure_modes:      frozenset[str] = field(
        default_factory=lambda: frozenset({"needs_clarification"})
    )


# ---------------------------------------------------------------------------
# Helpers — value coercion
# ---------------------------------------------------------------------------

def _nfc_fold(s: str) -> str:
    return unicodedata.normalize("NFC", s).strip().casefold()


def _coerce(value: str, spec: ArgSpec) -> tuple[Any, str | None]:
    """Coerce *value* per *spec*.  Returns ``(coerced_or_None, error_or_None)``."""
    raw = value.strip()
    if spec.type == "string":
        if not raw:
            return None, f"{spec.name}: empty"
        return raw, None
    if spec.type == "int":
        try:
            v = int(raw)
        except ValueError:
            return None, f"{spec.name}: expected integer, got {raw!r}"
        if spec.min_value is not None and v < spec.min_value:
            return None, f"{spec.name}: {v} < min {spec.min_value}"
        if spec.max_value is not None and v > spec.max_value:
            return None, f"{spec.name}: {v} > max {spec.max_value}"
        return v, None
    if spec.type == "float":
        try:
            v = float(raw)
        except ValueError:
            return None, f"{spec.name}: expected float, got {raw!r}"
        if spec.min_value is not None and v < spec.min_value:
            return None, f"{spec.name}: {v} < min {spec.min_value}"
        if spec.max_value is not None and v > spec.max_value:
            return None, f"{spec.name}: {v} > max {spec.max_value}"
        return v, None
    if spec.type == "enum":
        folded = _nfc_fold(raw)
        if spec.enum is None:
            return None, f"{spec.name}: enum spec missing"
        for accepted in spec.enum:
            if _nfc_fold(accepted) == folded:
                return accepted, None
        return None, f"{spec.name}: {raw!r} not in {list(spec.enum)}"
    return raw, None


# ---------------------------------------------------------------------------
# Flag / key=value extraction
# ---------------------------------------------------------------------------

_FLAG_RE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z_0-9]*)\s*=\s*(?P<val>\S+)")


def _extract_flags(
    args_text: str,
    arg_keys: dict[str, str],   # alias_or_name -> canonical_name
) -> tuple[str, dict[str, str], list[str]]:
    """Strip known ``key=value`` flags from *args_text*.

    Returns ``(positional_remainder, flags_by_canonical_name, unknown_keys)``.
    Unknown keys are left in the positional remainder so the caller can
    decide whether to error or ignore.
    """
    flags: dict[str, str] = {}
    unknown: list[str] = []
    kept: list[str] = []
    for token in args_text.split():
        m = _FLAG_RE.fullmatch(token)
        if m is None:
            kept.append(token)
            continue
        key = m.group("key").casefold()
        if key in arg_keys:
            flags[arg_keys[key]] = m.group("val")
        else:
            unknown.append(key)
            kept.append(token)
    return " ".join(kept).strip(), flags, unknown


def _build_arg_key_index(spec: PromptSpec) -> dict[str, str]:
    """Map every accepted key (canonical + aliases, folded) to canonical."""
    idx: dict[str, str] = {}
    for arg in spec.argument_schema.values():
        idx[arg.name.casefold()] = arg.name
        for alias in arg.aliases:
            idx[alias.casefold()] = arg.name
    return idx


# ---------------------------------------------------------------------------
# Parsers (per-prompt). Each returns (parsed_strings, errors).
# Coercion to int/float/enum happens later in validate_and_parse.
# ---------------------------------------------------------------------------

_CONNECTOR_RE = re.compile(
    r"\s+(?:por|for|vs\.?|versus|y|and)\s+|\s*,\s*",
    flags=re.IGNORECASE,
)


def _parse_single_required(arg_name: str):
    """Single-required-arg parser: whole positional payload = the value."""
    def _parser(args_text: str) -> tuple[dict[str, str], list[str]]:
        text = args_text.strip()
        if not text:
            return {}, []
        return {arg_name: text}, []
    return _parser


def _parse_two_required(a_name: str, b_name: str):
    """Two-required-arg parser. Accepts named-form OR positional with connector."""
    def _parser(args_text: str) -> tuple[dict[str, str], list[str]]:
        text = args_text.strip()
        if not text:
            return {}, []
        # Named-form takes precedence: handled later via _extract_flags in the
        # outer validate_and_parse step. This parser only owns the positional
        # split.
        parts = _CONNECTOR_RE.split(text, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            return {a_name: parts[0].strip(), b_name: parts[1].strip()}, []
        # Single token → only first arg present; the missing one will be
        # caught by the required check.
        return {a_name: text}, []
    return _parser


def _parse_positional_then_flags(positional_arg: str | None):
    """Optional-arg parser. After flag extraction, leftover positional bound
    to ``positional_arg`` (if not None)."""
    def _parser(args_text: str) -> tuple[dict[str, str], list[str]]:
        text = args_text.strip()
        if not text:
            return {}, []
        if positional_arg is None:
            return {}, []
        return {positional_arg: text}, []
    return _parser


# ---------------------------------------------------------------------------
# Validation rule helpers
# ---------------------------------------------------------------------------

def _rule_not_equal(field_a: str, field_b: str) -> Callable[[dict[str, Any]], str | None]:
    def _check(args: dict[str, Any]) -> str | None:
        a = args.get(field_a)
        b = args.get(field_b)
        if a is not None and b is not None and _nfc_fold(str(a)) == _nfc_fold(str(b)):
            return f"{field_a} and {field_b} must be different"
        return None
    return _check


# ---------------------------------------------------------------------------
# Registered specs (the seven M2 prompts)
# ---------------------------------------------------------------------------

# /chips enum — includes both Spanish-mode short codes (tc, wc, bb, fh) and
# English full names. Canonicalization is preserved as-typed (matched
# case-insensitively).
_CHIP_ENUM: tuple[str, ...] = (
    "tc", "wc", "bb", "fh",
    "triple_captain", "wildcard", "bench_boost", "free_hit",
)


_CAPITAN = PromptSpec(
    name="capitan",
    label="Capitanía",
    argument_schema={
        "player": ArgSpec(
            name="player", type="string", required=True,
            description="Player name or alias",
        ),
    },
    validation_rules=(),
    workflow_intent=INTENT_CAPTAIN_SCORE,
    mode=MODE_EXPANSION,
    expansion_template="should I captain {player}",
    parse=_parse_single_required("player"),
)


_COMPARAR = PromptSpec(
    name="comparar",
    label="Comparar",
    argument_schema={
        "a": ArgSpec(name="a", type="string", required=True, aliases=("jugador_a", "p1")),
        "b": ArgSpec(name="b", type="string", required=True, aliases=("jugador_b", "p2")),
    },
    validation_rules=(_rule_not_equal("a", "b"),),
    workflow_intent=INTENT_COMPARE_PLAYERS,
    mode=MODE_EXPANSION,
    expansion_template="compare {a} and {b}",
    parse=_parse_two_required("a", "b"),
)


_TRANSFERENCIA = PromptSpec(
    name="transferencia",
    label="Transferencia",
    argument_schema={
        "out": ArgSpec(name="out", type="string", required=True, aliases=("salida", "vender")),
        "in":  ArgSpec(name="in",  type="string", required=True, aliases=("entrada", "comprar")),
    },
    validation_rules=(_rule_not_equal("out", "in"),),
    workflow_intent=INTENT_TRANSFER_ADVICE,
    mode=MODE_EXPANSION,
    expansion_template="should I sell {out} for {in}",
    parse=_parse_two_required("out", "in"),
)


_CALENDARIOS = PromptSpec(
    name="calendarios",
    label="Calendarios",
    argument_schema={
        "player":  ArgSpec(name="player", type="string", required=True),
        "horizon": ArgSpec(
            name="horizon", type="int", required=False,
            min_value=1, max_value=10, default=5,
            aliases=("h", "n",),
            description="Number of upcoming fixtures",
        ),
    },
    validation_rules=(),
    workflow_intent=INTENT_PLAYER_FIXTURE_RUN,
    mode=MODE_DISPATCH,
    expansion_template=None,
    parse=_parse_positional_then_flags("player"),
)


_DIFERENCIALES = PromptSpec(
    name="diferenciales",
    label="Diferenciales",
    argument_schema={
        "threshold": ArgSpec(
            name="threshold", type="float", required=False,
            min_value=0.1, max_value=100.0, default=15.0,
            aliases=("umbral", "owned_under"),
        ),
        "top_n": ArgSpec(
            name="top_n", type="int", required=False,
            min_value=1, max_value=20, default=5,
            aliases=("n", "top"),
        ),
    },
    validation_rules=(),
    workflow_intent=INTENT_DIFFERENTIAL_PICKS,
    mode=MODE_DISPATCH,
    expansion_template=None,
    parse=_parse_positional_then_flags(None),
)


_CHIPS = PromptSpec(
    name="chips",
    label="Chips",
    argument_schema={
        "chip": ArgSpec(
            name="chip", type="enum", required=True,
            enum=_CHIP_ENUM,
            description="One of tc / wc / bb / fh (or full names)",
        ),
    },
    validation_rules=(),
    workflow_intent=INTENT_CHIP_ADVICE,
    mode=MODE_EXPANSION,
    expansion_template="should I use {chip} this week",
    parse=_parse_single_required("chip"),
)


_CLASIFICACION = PromptSpec(
    name="clasificacion",
    label="Clasificación",
    argument_schema={
        "n": ArgSpec(
            name="n", type="int", required=False,
            min_value=1, max_value=20, default=5,
            aliases=("top",),
        ),
    },
    validation_rules=(),
    workflow_intent=INTENT_RANK_CANDIDATES,
    mode=MODE_EXPANSION,
    expansion_template="top captains this week",
    parse=_parse_positional_then_flags(None),
)


_REGISTRY: dict[str, PromptSpec] = {
    "capitan":       _CAPITAN,
    "comparar":      _COMPARAR,
    "transferencia": _TRANSFERENCIA,
    "calendarios":   _CALENDARIOS,
    "diferenciales": _DIFERENCIALES,
    "chips":         _CHIPS,
    "clasificacion": _CLASIFICACION,
}


# Prompt-name aliases. Kept here AND mirrored in intent_aliases.py via
# resolve_prompt() — both surfaces must agree.
_PROMPT_NAME_ALIASES: dict[str, str] = {
    # English aliases
    "captain":     "capitan",
    "compare":     "comparar",
    "transfer":    "transferencia",
    "fixtures":    "calendarios",
    "calendar":    "calendarios",
    "differentials": "diferenciales",
    "chip":        "chips",
    "rank":        "clasificacion",
    "rankings":    "clasificacion",
    "ranking":     "clasificacion",
    "top":         "clasificacion",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_prompts() -> tuple[str, ...]:
    """Return the seven canonical prompt names in registration order."""
    return tuple(_REGISTRY.keys())


def list_prompt_specs() -> tuple[PromptSpec, ...]:
    return tuple(_REGISTRY.values())


def resolve_prompt(name: str) -> str | None:
    """Return the canonical prompt name for *name*, or None.

    Case-insensitive. Leading ``/`` is stripped if present. Consults the
    alias table.
    """
    if not isinstance(name, str):
        return None
    n = name.strip()
    if n.startswith("/"):
        n = n[1:]
    n = n.casefold()
    if not n:
        return None
    if n in _REGISTRY:
        return n
    return _PROMPT_NAME_ALIASES.get(n)


def get_prompt_spec(name: str) -> PromptSpec | None:
    canonical = resolve_prompt(name)
    if canonical is None:
        return None
    return _REGISTRY.get(canonical)


def validate_and_parse(
    spec: PromptSpec,
    args_text: str,
) -> dict[str, Any]:
    """Parse + validate ``args_text`` against ``spec``.

    Returns:

        {
            "ok":              bool,
            "args":            dict[str, Any],    # canonical-typed values
            "missing_fields":  list[str],         # required-but-absent
            "errors":          list[str],         # human-readable issues
        }
    """
    # 1. Extract key=value flags by alias / canonical name from args_text.
    key_index = _build_arg_key_index(spec)
    positional_text, flag_values, unknown_keys = _extract_flags(args_text, key_index)

    # 2. Positional parsing (per-prompt).
    parsed_positional: dict[str, str] = {}
    parse_errors: list[str] = []
    if spec.parse is not None:
        parsed_positional, parse_errors = spec.parse(positional_text)

    # 3. Merge — explicit flags win over positional inference.
    raw_values: dict[str, str] = {}
    for name, val in parsed_positional.items():
        raw_values[name] = val
    for name, val in flag_values.items():
        raw_values[name] = val

    # 4. Required-arg presence check.
    missing: list[str] = []
    for arg_name, arg_spec in spec.argument_schema.items():
        if arg_spec.required and arg_name not in raw_values:
            missing.append(arg_name)

    if missing:
        return {
            "ok":             False,
            "args":           {},
            "missing_fields": missing,
            "errors":         [f"missing required argument: {m}" for m in missing],
        }

    # 5. Coerce per type / enum / range.
    coerced: dict[str, Any] = {}
    coerce_errors: list[str] = []
    invalid_fields: list[str] = []
    for arg_name, arg_spec in spec.argument_schema.items():
        if arg_name in raw_values:
            value, err = _coerce(raw_values[arg_name], arg_spec)
            if err is not None:
                coerce_errors.append(err)
                invalid_fields.append(arg_name)
            else:
                coerced[arg_name] = value
        elif arg_spec.default is not None:
            coerced[arg_name] = arg_spec.default

    if coerce_errors:
        return {
            "ok":             False,
            "args":           {},
            "missing_fields": invalid_fields,
            "errors":         coerce_errors + parse_errors,
        }

    # 6. Run validation rules.
    rule_errors: list[str] = []
    for rule in spec.validation_rules:
        err = rule(coerced)
        if err is not None:
            rule_errors.append(err)

    if rule_errors:
        # Best-effort field-name extraction: rule messages embed the field
        # names so the UI can highlight them.
        invalid: list[str] = []
        for err in rule_errors:
            for arg_name in spec.argument_schema:
                if arg_name in err and arg_name not in invalid:
                    invalid.append(arg_name)
        return {
            "ok":             False,
            "args":           {},
            "missing_fields": invalid,
            "errors":         rule_errors,
        }

    return {
        "ok":             True,
        "args":           coerced,
        "missing_fields": [],
        "errors":         [],
    }


_CHIP_SHORT_TO_LONG: dict[str, str] = {
    "tc": "triple captain",
    "wc": "wildcard",
    "bb": "bench boost",
    "fh": "free hit",
    "triple_captain": "triple captain",
    "wildcard":       "wildcard",
    "bench_boost":    "bench boost",
    "free_hit":       "free hit",
}


def build_expansion(spec: PromptSpec, args: dict[str, Any]) -> str:
    """Build canonical text for MODE_EXPANSION prompts.

    Substitutes ``{arg}`` placeholders in ``spec.expansion_template`` with
    the validated ``args``. Returns the literal template unchanged if no
    placeholders are present (e.g. ``/clasificacion``).
    """
    if spec.expansion_template is None:
        raise ValueError(f"prompt {spec.name!r} has no expansion_template")
    if "{" not in spec.expansion_template:
        return spec.expansion_template
    # /chips: translate short codes into router-recognized natural-language
    # chip phrases so canonical text re-routes deterministically.
    formatted: dict[str, str] = {}
    for k, v in args.items():
        sv = str(v)
        if spec.name == "chips" and k == "chip":
            sv = _CHIP_SHORT_TO_LONG.get(_nfc_fold(sv), sv)
        formatted[k] = sv
    return spec.expansion_template.format(**formatted)
