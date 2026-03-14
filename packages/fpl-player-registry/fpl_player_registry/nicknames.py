"""
fpl_player_registry.nicknames
==============================
Known nickname / alias table for FPL players.

Source: fpl-video-repurposer/build_fpl_kb.py::KNOWN_NICKNAMES (lines 73-100)
        Predominantly Spanish community nicknames used in video commentary.

Keys are FPL web_names (exact, case-sensitive).
Values are lists of aliases that resolve to that player.

Do not add fuzzy patterns here — see Phase 2+ for fuzzy matching.
To extend: add more web_name → [alias, ...] entries and re-run tests.
"""

from __future__ import annotations

KNOWN_NICKNAMES: dict[str, list[str]] = {
    "Salah":            ["Mo", "el Salah", "el Faraón"],
    "Haaland":          ["Erling", "el Vikingo", "el Haaland"],
    "De Bruyne":        ["KDB", "el De Bruyne"],
    "Palmer":           ["el Palmer", "Cole"],
    "Saka":             ["el Saka", "Bukayo"],
    "Son":              ["Sonny", "el Son", "Heung-Min"],
    "Mbappé":           ["Kylian", "el Mbappé"],
    "Foden":            ["Phil", "el Foden"],
    "Trippier":         ["el Trippier", "Kieran"],
    "Alexander-Arnold": ["TAA", "el Alexander-Arnold", "Trent"],
    "Rashford":         ["el Rashford", "Marcus"],
    "Martinelli":       ["el Martinelli", "Gabi"],
    "Watkins":          ["el Watkins", "Ollie"],
    "Gordon":           ["el Gordon", "Anthony"],
    "Isak":             ["el Isak", "Alexander"],
}


