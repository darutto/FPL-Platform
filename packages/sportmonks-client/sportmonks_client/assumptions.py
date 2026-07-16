"""Machine-readable registry of documentation-derived live assumptions."""
from __future__ import annotations

ASSUMPTIONS = (
    ("SM-AUTH-001", "v3 football base URL and api_token query authentication", "Sportmonks public API authentication docs", "edge_cases.json"),
    ("SM-ENDPOINT-001", "endpoint paths and include syntax used by client methods", "Sportmonks football API endpoint docs", "endpoint_payloads.json"),
    ("SM-PAGE-001", "pagination current_page/has_more/next_page shape", "Sportmonks pagination docs/examples", "multi_page.json"),
    ("SM-LINEUP-001", "lineup, formation, grid and detailed-position nesting", "Sportmonks lineups documentation examples", "endpoint_payloads.json"),
    ("SM-AVAIL-001", "injury and suspension payload shapes", "Sportmonks injuries/suspensions documentation examples", "endpoint_payloads.json"),
    ("SM-STATS-001", "team/player fixture statistics names and nesting", "Sportmonks statistics documentation examples", "endpoint_payloads.json"),
    ("SM-RATE-001", "Retry-After and rate-limit response headers", "Sportmonks rate-limit documentation", "edge_cases.json"),
    ("SM-CORRECTION-001", "post-full-time correction and update behavior", "not established by public examples", "endpoint_payloads.json"),
)


def assumption_registry() -> tuple[dict[str, object], ...]:
    return tuple({
        "assumption_id": item[0], "description": item[1], "documentation_source": item[2],
        "status": "unverified_against_live", "fixture_reference": item[3], "live_validation_required": True,
    } for item in ASSUMPTIONS)
