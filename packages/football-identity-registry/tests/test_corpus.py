import json
from pathlib import Path

from football_identity_registry.matcher import match_player
from football_identity_registry.models import CandidatePlayer, SourcePlayer


def test_sanitized_corpus_reports_rates():
    payload = json.loads((Path(__file__).parent / "fixtures" / "corpus.json").read_text())
    candidates = [CandidatePlayer(**row) for row in payload["candidates"]]
    rates = {}
    for provider in ("understat", "vaastav"):
        results = [match_player(SourcePlayer(**row), candidates) for row in payload[provider]]
        rates[provider] = sum(result.matched for result in results) / len(results)
    assert rates == {"understat": 1.0, "vaastav": 2 / 3}
