import json
from pathlib import Path

from football_identity_registry.corpus import validate_extract


CORPUS_DIR = Path(__file__).parents[1] / "corpus"


def test_committed_real_name_report_reproduces_from_sanitized_extract():
    extract = json.loads((CORPUS_DIR / "owned_names.json").read_text(encoding="utf-8"))
    report = json.loads((CORPUS_DIR / "report.json").read_text(encoding="utf-8"))
    assert validate_extract(extract) == report


def test_real_corpus_denominators_have_no_exclusions():
    report = json.loads((CORPUS_DIR / "report.json").read_text(encoding="utf-8"))
    assert report["denominator_rule"].endswith("no exclusions")
    assert report["results"]["understat"]["total_source_identities"] >= 400
    assert report["results"]["vaastav"]["total_source_identities"] >= 700
