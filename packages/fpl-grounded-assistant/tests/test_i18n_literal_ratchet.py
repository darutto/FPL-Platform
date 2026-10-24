"""i18n S3b -- the backend Spanish-literal ratchet.

New user-visible Spanish must go through the catalogue (es + en). This fails when
a scanned output module gains a Spanish string literal that is not in
``tests/i18n_literal_baseline.json``. See ``scripts/i18n_literal_ratchet.py``.

To shrink the baseline after moving text to the catalogue:
    python scripts/i18n_literal_ratchet.py --update
"""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "i18n_literal_ratchet.py"
_spec = importlib.util.spec_from_file_location("i18n_literal_ratchet", _SCRIPT)
ratchet = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ratchet)


def test_no_new_spanish_literal_in_the_output_modules():
    fresh = ratchet.new_literals(ratchet.scan(), ratchet.load_baseline())
    assert not fresh, (
        "New Spanish string literal(s) in a module that builds user-visible text. "
        "Put the text in catalogue.py with an English twin (t(key, locale)), or, if it is "
        "genuinely not output, justify it in review and run "
        "`python scripts/i18n_literal_ratchet.py --update`:\n"
        + "\n".join(f"  {rel}: {text!r}" for rel, items in fresh.items() for text in items)
    )


def test_baseline_is_clean_sorted_and_only_for_scanned_modules():
    baseline = ratchet.load_baseline()
    assert set(baseline) <= set(ratchet.SCANNED)
    for rel, literals in baseline.items():
        assert literals == sorted(set(literals)), rel
        assert (ratchet.PKG / rel).exists(), rel


def _scan_source(source: str) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mod.py"
        path.write_text(source, encoding="utf-8")
        return ratchet.scan_module(path)


@pytest.mark.parametrize(
    "literal",
    [
        "partido m\u00e1s f\u00e1cil",
        "\u00bfBuscas consejo de capitan\u00eda?",
        "Prueba con la jornada actual",
        "ventaja para el equipo",
    ],
)
def test_detector_flags_spanish(literal):
    assert _scan_source(f"X = {literal!r}\n") == [literal]


@pytest.mark.parametrize(
    "literal",
    [
        "better form",
        "Are you comparing two players?",
        "Wildcard",
        "no tool found for the player",
        "ok",
    ],
)
def test_detector_ignores_english_and_identifiers(literal):
    assert _scan_source(f"X = {literal!r}\n") == []


def test_detector_skips_docstrings_and_replaced_literal_still_fails():
    src = '"""M\u00f3dulo de prueba con la jornada."""\n\ndef f():\n    """Una funci\u00f3n para el equipo."""\n    return "mejor forma de la jornada"\n'
    assert _scan_source(src) == ["mejor forma de la jornada"]
    baseline = {"m.py": ["mejor forma de la jornada"]}
    # swapping one Spanish literal for a different one is NEW even though the count is unchanged
    assert ratchet.new_literals({"m.py": ["otra frase para la jornada"]}, baseline) == {
        "m.py": ["otra frase para la jornada"]
    }
    assert ratchet.new_literals({"m.py": ["mejor forma de la jornada"]}, baseline) == {}
    assert ratchet.new_literals({}, baseline) == {}
