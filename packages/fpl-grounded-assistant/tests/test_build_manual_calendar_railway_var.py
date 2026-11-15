"""The Raw Editor line for the European layer: one line, quotes escaped, read back unchanged. Synthetic data only."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_manual_calendar_railway_var.py"
_spec = importlib.util.spec_from_file_location("_railway_var", _SCRIPT)
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)


def test_the_line_is_one_line_with_escaped_quotes_and_reads_back():
    value = json.dumps({"provenance": "manual_curated", "matches": [{"opponent": "Equipo Uno Ş"}]},
                       ensure_ascii=False, separators=(",", ":"))
    line = rv.env_line(value)
    assert line.startswith('FPL_MANUAL_CALENDAR_JSON="{\\"provenance\\":') and line.endswith('"') and "\n" not in line
    assert rv.read_env_line(line) == value


@pytest.mark.parametrize("value", ['{"a":"x\\y"}', '{"a":"x\ny"}'])
def test_a_value_that_needs_more_than_quote_escaping_is_refused(value):
    with pytest.raises(ValueError):
        rv.env_line(value)
