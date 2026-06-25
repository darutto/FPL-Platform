"""
worldcup_api_client.openfootball_client
========================================
Knockout-bracket source for World Cup 2026, backed by the openfootball
public-domain dataset.

Why this source
---------------
The FIFA Fantasy feed used by ``wc_client.py`` only ships group-stage rounds
— it carries no knockout fixtures at all (``get_fixtures`` ignores its
``stage`` arg for exactly this reason). So the bracket (Round of 32 → Final)
cannot be answered from that feed.

``https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json``
is a free, public-domain, no-auth JSON file that already contains the FULL
104-match schedule, including a pre-built knockout skeleton. Crucially it
encodes FIFA's official bracket-slot mapping for us: knockout matches start
with placeholder codes — ``2A`` (runner-up of Group A), ``3A/B/C/D/F`` (best
third-placed team among those groups), ``W74`` / ``L101`` (winner/loser of
match 74 / 101) — and the maintainer fills in real team names by hand as the
tournament resolves. So we never hand-encode the bracket structure ourselves.

How it stays fresh ("daily update on our end")
-----------------------------------------------
openfootball is updated by hand roughly once a day (a wiki-style text source
auto-published to JSON via a GitHub Action). We mirror that cadence with a
long in-process TTL (``TTL_BRACKET_S``, default 6 h): each running instance
re-pulls the file a few times a day, automatically — no cron, no Redis, no
secrets. ``clear_bracket_cache()`` forces an immediate refetch (used by tests
and the optional refresh script).

Two-layer slot resolution
--------------------------
1. **Trust openfootball.** Whenever a slot already holds a real team name
   (the maintainer filled it in), we use it verbatim.
2. **Opportunistic early resolution.** For ``<pos><group>`` codes (``1A`` /
   ``2B``) we resolve from group standings computed off this SAME file — but
   ONLY once that group is mathematically decided. FIFA's first three group
   tie-breakers are points → goal difference → goals scored, so when those
   three are distinct the 1st/2nd ordering is definitive; if they tie at the
   relevant boundary we decline to guess (head-to-head/disciplinary/draw are
   not replicated) and leave the slot pending. Best-third-place (``3…``) and
   ``W…`` / ``L…`` codes are never guessed — openfootball fills those.

Every unresolved slot still carries a Spanish human-readable description
(``"2.º del Grupo A"``, ``"Ganador del partido 74"``) so the assistant can
phrase the matchup even before the teams are known.
"""
from __future__ import annotations

import os
import re
import threading
import time
import unicodedata
from typing import Any

import httpx

from .wc_client import WorldCupAPIError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Overridable so the source can be swapped (or pinned to a tag/mirror) without
#: a code change — see WORLDCUP_JSON_URL in worldcup-assistant/.env.template.
_DEFAULT_URL = (
    "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
)

_DEFAULT_TIMEOUT_S: float = 15.0
_RETRY_ATTEMPTS: int = 3
_RETRY_BACKOFF_S: float = 1.5  # multiplied by attempt number

#: openfootball changes at most ~once/day; a 6 h TTL re-pulls a few times a day
#: without ever serving data more than ~6 h stale without a network call.
TTL_BRACKET_S: float = 6 * 60 * 60


def _source_url() -> str:
    return os.environ.get("WORLDCUP_JSON_URL", _DEFAULT_URL)


# ---------------------------------------------------------------------------
# Single-document in-process TTL cache
# ---------------------------------------------------------------------------

_cache: tuple[float, Any] | None = None  # (expires_at_monotonic, payload)
_cache_lock = threading.Lock()


def clear_bracket_cache() -> None:
    """Drop the cached document. Used by tests and the manual refresh script."""
    global _cache
    with _cache_lock:
        _cache = None


def _fetch_bracket_doc() -> dict[str, Any]:
    """GET the openfootball 2026 document (TTL-cached), with retries on
    transport errors / 5xx / 429. Raises ``WorldCupAPIError`` after retries."""
    global _cache
    with _cache_lock:
        if _cache is not None and time.monotonic() < _cache[0]:
            return _cache[1]

    url = _source_url()
    last_err: str | None = None

    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            resp = httpx.get(url, timeout=_DEFAULT_TIMEOUT_S)
            if resp.status_code == 429 or resp.status_code >= 500:
                last_err = f"HTTP {resp.status_code}"
                if attempt < _RETRY_ATTEMPTS:
                    time.sleep(_RETRY_BACKOFF_S * attempt)
                    continue
                break
            if resp.status_code >= 400:
                raise WorldCupAPIError(f"HTTP {resp.status_code} for bracket source")
            payload = resp.json()
            if not isinstance(payload, dict) or "matches" not in payload:
                raise WorldCupAPIError("bracket source returned unexpected shape")
            with _cache_lock:
                _cache = (time.monotonic() + TTL_BRACKET_S, payload)
            return payload
        except WorldCupAPIError:
            raise
        except httpx.TimeoutException:
            last_err = "timeout"
        except httpx.HTTPError as exc:
            last_err = f"{type(exc).__name__}: {exc}"
        except ValueError as exc:  # JSON decode failure
            raise WorldCupAPIError(f"invalid JSON from bracket source: {exc}") from None
        if attempt < _RETRY_ATTEMPTS:
            time.sleep(_RETRY_BACKOFF_S * attempt)

    raise WorldCupAPIError(
        f"bracket source request failed after {_RETRY_ATTEMPTS} attempts: {last_err}"
    )


# ---------------------------------------------------------------------------
# Stage mapping (openfootball round string -> our stage enum)
# ---------------------------------------------------------------------------

#: openfootball "round" -> the stage enum used elsewhere (get_fixtures /
#: get_wc2022_results), so locale_es.STAGE_ES labels apply uniformly.
_ROUND_TO_STAGE: dict[str, str] = {
    "round of 32": "round_of_32",
    "round of 16": "round_of_16",
    "quarter-final": "quarter_final",
    "semi-final": "semi_final",
    "match for third place": "third_place",
    "final": "final",
}

#: Ordering for stable bracket output (R32 first → Final last).
_STAGE_ORDER: dict[str, int] = {
    "round_of_32": 0,
    "round_of_16": 1,
    "quarter_final": 2,
    "semi_final": 3,
    "third_place": 4,
    "final": 5,
}


def _is_group_round(round_str: str) -> bool:
    return round_str.strip().lower().startswith("matchday")


def _stage_for_round(round_str: str) -> str | None:
    return _ROUND_TO_STAGE.get(round_str.strip().lower())


def _norm_stage(stage: str) -> str:
    return stage.strip().lower().replace("-", "_").replace(" ", "_")


# ---------------------------------------------------------------------------
# Group standings (computed from this same document) for slot resolution
# ---------------------------------------------------------------------------

def _group_letter(group_str: str | None) -> str | None:
    if not group_str:
        return None
    token = group_str.strip().split()[-1]  # "Group A" -> "A"
    return token.upper() if len(token) == 1 and token.isalpha() else None


def _compute_group_standings(matches: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-group standings from played group-stage matches in this document.

    Returns ``{letter: {"complete": bool, "ranked": [team,...],
    "keys": [(pts, gd, gf),...]}}`` where ``ranked``/``keys`` are aligned and
    sorted best-first. ``complete`` is True once all 6 group matches are
    played. Only consulted for resolving ``<pos><group>`` slots.
    """
    tables: dict[str, dict[str, dict[str, int]]] = {}
    played: dict[str, int] = {}

    for mt in matches:
        if not _is_group_round(str(mt.get("round", ""))):
            continue
        letter = _group_letter(mt.get("group"))
        if letter is None:
            continue
        tables.setdefault(letter, {})
        played.setdefault(letter, 0)

        ft = (mt.get("score") or {}).get("ft")
        team1, team2 = mt.get("team1"), mt.get("team2")
        if not (isinstance(ft, list) and len(ft) == 2 and team1 and team2):
            continue  # not yet played
        played[letter] += 1
        g1, g2 = ft[0], ft[1]
        for team in (team1, team2):
            tables[letter].setdefault(
                team, {"pts": 0, "gf": 0, "ga": 0}
            )
        t1, t2 = tables[letter][team1], tables[letter][team2]
        t1["gf"] += g1; t1["ga"] += g2
        t2["gf"] += g2; t2["ga"] += g1
        if g1 > g2:
            t1["pts"] += 3
        elif g2 > g1:
            t2["pts"] += 3
        else:
            t1["pts"] += 1; t2["pts"] += 1

    standings: dict[str, dict[str, Any]] = {}
    for letter, table in tables.items():
        rows = [
            (team, row["pts"], row["gf"] - row["ga"], row["gf"])
            for team, row in table.items()
        ]
        # FIFA primary order: points, goal difference, goals for (name only as
        # a deterministic display fallback — never used to break a real tie).
        rows.sort(key=lambda r: (-r[1], -r[2], -r[3], r[0]))
        standings[letter] = {
            "complete": played.get(letter, 0) >= 6,
            "ranked": [r[0] for r in rows],
            "keys": [(r[1], r[2], r[3]) for r in rows],
        }
    return standings


# ---------------------------------------------------------------------------
# Slot (placeholder code) resolution
# ---------------------------------------------------------------------------

#: English (openfootball) team name → FIFA 3-letter code, for the bracket-card
#: abbreviation chips. Keyed on the names openfootball uses (with a few
#: spelling variants). Unmapped names fall back to an accent-stripped
#: first-three-letters code via ``_abbr``.
_TEAM_ABBR: dict[str, str] = {
    # CONMEBOL
    "argentina": "ARG", "brazil": "BRA", "uruguay": "URU", "colombia": "COL",
    "ecuador": "ECU", "paraguay": "PAR", "peru": "PER", "chile": "CHI",
    "bolivia": "BOL", "venezuela": "VEN",
    # UEFA
    "spain": "ESP", "england": "ENG", "france": "FRA", "germany": "GER",
    "netherlands": "NED", "belgium": "BEL", "croatia": "CRO", "switzerland": "SUI",
    "denmark": "DEN", "sweden": "SWE", "norway": "NOR", "poland": "POL",
    "portugal": "POR", "italy": "ITA", "austria": "AUT", "scotland": "SCO",
    "wales": "WAL", "turkey": "TUR", "turkiye": "TUR", "ukraine": "UKR",
    "serbia": "SRB", "czechia": "CZE", "czech republic": "CZE", "slovakia": "SVK",
    "slovenia": "SVN", "romania": "ROU", "hungary": "HUN", "greece": "GRE",
    "finland": "FIN", "republic of ireland": "IRL", "ireland": "IRL",
    "iceland": "ISL", "albania": "ALB", "north macedonia": "MKD",
    "bosnia and herzegovina": "BIH", "montenegro": "MNE", "kosovo": "KVX",
    "georgia": "GEO",
    # CAF
    "morocco": "MAR", "senegal": "SEN", "tunisia": "TUN", "algeria": "ALG",
    "egypt": "EGY", "nigeria": "NGA", "ghana": "GHA", "cameroon": "CMR",
    "ivory coast": "CIV", "cote d'ivoire": "CIV", "côte d'ivoire": "CIV",
    "south africa": "RSA", "cape verde": "CPV", "cabo verde": "CPV",
    "dr congo": "COD", "congo dr": "COD", "mali": "MLI", "burkina faso": "BFA",
    "guinea": "GUI", "gabon": "GAB", "benin": "BEN", "zambia": "ZAM",
    "kenya": "KEN", "mozambique": "MOZ", "angola": "ANG",
    # AFC
    "japan": "JPN", "south korea": "KOR", "korea republic": "KOR",
    "saudi arabia": "KSA", "iran": "IRN", "ir iran": "IRN", "qatar": "QAT",
    "iraq": "IRQ", "jordan": "JOR", "uzbekistan": "UZB",
    "united arab emirates": "UAE", "china": "CHN", "china pr": "CHN",
    "australia": "AUS",
    # OFC
    "new zealand": "NZL",
    # CONCACAF
    "united states": "USA", "usa": "USA", "mexico": "MEX", "canada": "CAN",
    "panama": "PAN", "costa rica": "CRC", "honduras": "HON", "jamaica": "JAM",
    "haiti": "HAI", "curacao": "CUW", "curaçao": "CUW",
    "trinidad and tobago": "TRI", "el salvador": "SLV", "guatemala": "GUA",
    "suriname": "SUR",
}


def _abbr(name: str | None) -> str | None:
    """FIFA-style 3-letter code for a resolved (English) team name. Falls back
    to the accent-stripped, uppercased first three letters when unmapped."""
    if not name:
        return None
    code = _TEAM_ABBR.get(name.strip().lower())
    if code:
        return code
    stripped = "".join(
        c for c in unicodedata.normalize("NFKD", name)
        if not unicodedata.combining(c) and c.isalpha()
    )
    return stripped[:3].upper() if stripped else None


_POS_GROUP = re.compile(r"^([12])([A-L])$")
_THIRD = re.compile(r"^3([A-L](?:/[A-L])*)$")
_WINNER = re.compile(r"^W(\d+)$")
_LOSER = re.compile(r"^L(\d+)$")

_ORDINAL_ES = {1: "1.º", 2: "2.º"}


def _resolve_slot(
    code: Any, standings: dict[str, dict[str, Any]]
) -> tuple[str | None, str | None]:
    """Resolve one ``team1``/``team2`` value.

    Returns ``(team, source)``:
      * ``team``   — the (English) team name if known, else ``None`` (pending).
      * ``source`` — a Spanish description of the slot's origin for placeholder
        codes (``"2.º del Grupo A"``), or ``None`` when the value is already a
        real team name.
    """
    if not isinstance(code, str) or not code.strip():
        return None, None
    code = code.strip()

    m = _POS_GROUP.match(code)
    if m:
        pos, letter = int(m.group(1)), m.group(2)
        source = f"{_ORDINAL_ES[pos]} del Grupo {letter}"
        group = standings.get(letter)
        if group and group["complete"] and len(group["ranked"]) >= pos:
            idx = pos - 1
            keys = group["keys"]
            unambiguous_above = idx == 0 or keys[idx - 1] != keys[idx]
            unambiguous_below = idx == len(keys) - 1 or keys[idx] != keys[idx + 1]
            if unambiguous_above and unambiguous_below:
                return group["ranked"][idx], source
        return None, source

    m = _THIRD.match(code)
    if m:
        letters = "/".join(m.group(1).split("/"))
        return None, f"Mejor 3.º (Grupos {letters})"

    m = _WINNER.match(code)
    if m:
        return None, f"Ganador del partido {m.group(1)}"

    m = _LOSER.match(code)
    if m:
        return None, f"Perdedor del partido {m.group(1)}"

    # Not a placeholder pattern -> a real team name openfootball already filled.
    return code, None


def _score_and_winner(
    match: dict[str, Any], home_team: str | None, away_team: str | None
) -> tuple[int | None, int | None, str | None]:
    """Full-time score + advancing side for a knockout tie, once played.

    Returns ``(home_score, away_score, winner_side)`` where ``winner_side`` is
    ``"home"``/``"away"``/``None``. A draw is broken by the penalty shootout
    score if openfootball recorded one (``score.p``/``pen``/``penalties``).
    Only reported when both sides are confirmed teams — a score against a
    placeholder slot would be meaningless.
    """
    if not (home_team and away_team):
        return None, None, None
    score = match.get("score") or {}
    ft = score.get("ft")
    if not (isinstance(ft, list) and len(ft) == 2):
        return None, None, None
    hs, as_ = ft[0], ft[1]
    if hs > as_:
        return hs, as_, "home"
    if as_ > hs:
        return hs, as_, "away"
    pens = score.get("p") or score.get("pen") or score.get("penalties")
    if isinstance(pens, list) and len(pens) == 2:
        if pens[0] > pens[1]:
            return hs, as_, "home"
        if pens[1] > pens[0]:
            return hs, as_, "away"
    return hs, as_, None


# ---------------------------------------------------------------------------
# Public endpoint
# ---------------------------------------------------------------------------

def get_bracket(stage: str | None = None) -> dict[str, Any]:
    """World Cup 2026 knockout bracket (Round of 32 → Final).

    Each match reports both sides as either a resolved team name (when known)
    or a pending slot with a Spanish description of its origin. ``stage``
    optionally filters to one round (enum: ``round_of_32``, ``round_of_16``,
    ``quarter_final``, ``semi_final``, ``third_place``, ``final``); omit for
    the whole bracket.

    Returns ``{"ties": [...], "count": n, "bracket_complete": bool}`` (plus
    ``"stage"`` echoed when a filter was applied). ``bracket_complete`` is True
    only when every returned slot is resolved to a real team.

    The list key is ``"ties"`` (not ``"matches"``) on purpose: ``"matches"`` is
    a token-budget-truncatable field in the WC tool loop, and the bracket is a
    fixed 32-tie structure that must never be capped to 10 in the card.
    """
    doc = _fetch_bracket_doc()
    all_matches = doc.get("matches") or []
    standings = _compute_group_standings(all_matches)

    stage_filter = _norm_stage(stage) if stage else None

    out: list[dict[str, Any]] = []
    for mt in all_matches:
        match_stage = _stage_for_round(str(mt.get("round", "")))
        if match_stage is None:
            continue  # group-stage match — bracket is knockout-only
        if stage_filter and match_stage != stage_filter:
            continue

        home_team, home_source = _resolve_slot(mt.get("team1"), standings)
        away_team, away_source = _resolve_slot(mt.get("team2"), standings)
        home_score, away_score, winner_side = _score_and_winner(mt, home_team, away_team)
        out.append({
            "match_num": mt.get("num"),
            "stage": match_stage,
            "date": mt.get("date"),
            "time": mt.get("time"),
            "venue_city": mt.get("ground"),
            "home_team": home_team,
            "away_team": away_team,
            "home_abbr": _abbr(home_team),
            "away_abbr": _abbr(away_team),
            "home_source": home_source,
            "away_source": away_source,
            "home_score": home_score,
            "away_score": away_score,
            #: Which side advanced ("home"/"away"), once the tie is played;
            #: None while pending. Drives the winner highlight in the card.
            "winner_side": winner_side,
            "resolved": home_team is not None and away_team is not None,
        })

    out.sort(key=lambda m: (_STAGE_ORDER.get(m["stage"], 99), m["match_num"] or 0))

    result: dict[str, Any] = {
        "ties": out,
        "count": len(out),
        "bracket_complete": bool(out) and all(m["resolved"] for m in out),
    }
    if stage:
        result["stage"] = stage_filter
    return result


__all__ = [
    "TTL_BRACKET_S",
    "clear_bracket_cache",
    "get_bracket",
]
