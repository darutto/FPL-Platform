"""Live-trial adapter: a frozen capture of live Sportmonks reads -> FI-4a replay sources and a v2 context.

FI-9 builds canonical stores from live reads for the trial's own analysis. Nothing
here publishes: every store it writes is stamped ``live_trial_local`` and every
publishing or serving path refuses that stamp (``football_intelligence.provenance``).

Input is one JSON capture (``live_capture.py`` in ``sportmonks-client``) and no
network. The adapter's own decisions, each of which a reviewer should be able to
find and argue with, are:

* **Teams.** The 20 Premier League clubs and every opponent get trial-local seeds
  (status ``trial-local-unverified``) with registry keys
  ``jurisdiction|club|men|senior`` slugged from the provider's name and the core
  API's country. No fuzzy matching: two provider ids that slug to the same key
  stop the build. The FPL crosswalk of a Premier League club is the one its
  identity pairs vote for unanimously (at least 3 pairs).
* **Players.** Identity is the mapping run's pairs and nothing else. A provider
  player with no pair is quarantined by the unchanged FI-4a normalizer.
* **Appearances.** A lineup row exists only for a player who took the field
  (started, or came on and played minutes), in a completed fixture. An unused
  substitute is not an appearance. Minutes are the provider's own minutes-played
  detail (type 119); a player on the field without it is dropped and counted.
* **Fixture keys.** ``league-home-meeting-N`` with N the chronological meeting
  number of the pair in the competition; ``cup-<stage>-leg-1|2|single``.
* **Schedule knowledge.** The provider gives no history of what was known when.
  A scheduled snapshot is dated ``SCHEDULE_PUBLISHED_AT``; a completed one is
  dated kickoff + ``RESULT_KNOWN_AFTER_HOURS``. The cutoff logic of FI-5b is
  therefore exact about *this* assumption and blind to postponements.
* **Not built:** standings (every league band is ``unknown``), injuries and
  suspensions (availability reaches M1 as an explicit input), statistics, coaches
  and referees (none is read by M1-M3).
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from football_data_contract import (canonical_competition_id, canonical_fixture_id, canonical_player_id,
                                    canonical_season_id, canonical_team_id)

from football_intelligence.provenance import LIVE_TRIAL_LOCAL

from .team_registry import TeamCrosswalk, TeamRegistry, TeamSeed

CAPTURE_SCHEMA_VERSION = 1
REPLAY_VERSION = "fi9-live-trial-replay-v1"
TRIAL_SEED_STATUS = "trial-local-unverified"
TRIAL_SEED_PROVENANCE = "trial-local; generated from live Sportmonks reads; never governed"
SEASON_EDITION = "2026-2027"
SEASON_LABEL = "2026/27"
#: Dates the registry crosswalks are valid from; a season-long trial store.
SEED_VALID_FROM = "2026-07-01"
#: Assumption (see module docstring): when a fixture list is taken to have been known.
SCHEDULE_PUBLISHED_AT = "2026-06-01T00:00:00Z"
#: Assumption: a final result is taken to be known this long after kickoff.
RESULT_KNOWN_AFTER_HOURS = 3
MINUTES_DETAIL_TYPE = 119
STARTER_TYPE = 11
SUBSTITUTION_EVENT = 18
CLUB_CROSSWALK_MIN_PAIRS = 3

#: Sportmonks league id -> governed-looking competition identity. Trial-local.
COMPETITIONS: dict[int, dict[str, str]] = {
    8: dict(governing_body="the-fa", registry_key="premier-league", category="men", name="Premier League",
            tier="league", context_tier="league", country="England"),
    2: dict(governing_body="uefa", registry_key="champions-league", category="men", name="Champions League",
            tier="continental", context_tier="continental", country="Europe"),
    5: dict(governing_body="uefa", registry_key="europa-league", category="men", name="Europa League",
            tier="continental", context_tier="continental", country="Europe"),
    2286: dict(governing_body="uefa", registry_key="conference-league", category="men",
               name="Europa Conference League", tier="continental", context_tier="continental", country="Europe"),
    1328: dict(governing_body="uefa", registry_key="super-cup", category="men", name="UEFA Super Cup",
               tier="continental", context_tier="continental", country="Europe"),
    24: dict(governing_body="the-fa", registry_key="fa-cup", category="men", name="FA Cup",
             tier="domestic_cup", context_tier="domestic_cup", country="England"),
    27: dict(governing_body="english-football-league", registry_key="efl-cup", category="men", name="Carabao Cup",
             tier="domestic_cup", context_tier="domestic_cup", country="England"),
}

STATUS_MAP = {
    "NS": "scheduled", "TBA": "scheduled", "PENDING": "scheduled", "DELAYED": "scheduled",
    "FT": "completed", "AET": "completed", "FT_PEN": "completed", "AWARDED": "completed", "WO": "completed",
    "INPLAY_1ST_HALF": "live", "INPLAY_2ND_HALF": "live", "INPLAY_ET": "live", "INPLAY_PENALTIES": "live",
    "HT": "live", "BREAK": "live", "EXTRA_TIME_BREAK": "live", "PEN_BREAK": "live", "INT": "live",
    "POSTPONED": "postponed", "CANCELLED": "cancelled", "CANC": "cancelled", "ABANDONED": "abandoned",
    "SUSPENDED": "postponed",
}
#: Provider stage name (casefolded) -> canonical-context competition stage.
#: Where the closed vocabulary has no word for a stage (numbered domestic rounds,
#: the knockout play-off) it is ``unknown``, on purpose and visibly.
STAGE_MAP = {
    "regular season": "league", "league stage": "league_phase",
    "preliminary round": "qualification", "1st qualifying round": "qualification",
    "2nd qualifying round": "qualification", "3rd qualifying round": "qualification",
    "round of 32": "round_of_32", "round of 16": "round_of_16", "8th finals": "round_of_16",
    "quarter-finals": "quarter_final", "quarter finals": "quarter_final",
    "semi-finals": "semi_final", "semi finals": "semi_final", "final": "final",
}


class LiveTrialAdapterError(ValueError):
    """The capture cannot be turned into a store without guessing."""


# ------------------------------------------------------------------ small helpers

_SPECIALS = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "ß": "ss", "ð": "d", "þ": "th", "ł": "l", "đ": "d"})


def slug(value: str) -> str:
    folded = unicodedata.normalize("NFKD", str(value).translate(_SPECIALS).casefold())
    ascii_only = "".join(ch for ch in folded if not unicodedata.combining(ch))
    out = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    if not out:
        raise LiveTrialAdapterError(f"cannot slug {value!r}")
    return out


def _utc(value: str) -> str:
    """'2026-08-22 14:00:00' (UTC) -> '2026-08-22T14:00:00Z'."""
    parsed = datetime.strptime(value[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _plus_hours(iso: str, hours: float) -> str:
    parsed = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=hours)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _location(fixture: Mapping[str, Any], where: str) -> dict[str, Any]:
    found = [p for p in fixture["participants"] if (p.get("meta") or {}).get("location") == where]
    if len(found) != 1:
        raise LiveTrialAdapterError(f"fixture {fixture['id']} has no unique {where} participant")
    return found[0]


def fixture_status(fixture: Mapping[str, Any]) -> str:
    return STATUS_MAP.get((fixture.get("state") or {}).get("developer_name", ""), "unknown")


def context_stage(fixture: Mapping[str, Any]) -> str:
    return STAGE_MAP.get(((fixture.get("stage") or {}).get("name") or "").casefold(), "unknown")


# ------------------------------------------------------------------ teams

def _team_key(country_name: str, club_name: str, gender: str) -> str:
    category = {"male": "men", "female": "women"}.get(gender)
    if category is None:
        raise LiveTrialAdapterError(f"unknown club gender {gender!r}")
    return f"{slug(country_name)}|{slug(club_name)}|{category}|senior"


def club_crosswalk(capture: Mapping[str, Any]) -> dict[int, int]:
    """Sportmonks club id -> FPL team id, from the identity pairs, unanimous or not at all."""
    element_team = {int(e["id"]): int(e["team"]) for e in capture["fpl"]["elements"]}
    player_club = {str(p["id"]): p.get("squad_team_id") for p in capture["players"]}
    votes: dict[int, Counter] = defaultdict(Counter)
    for pair in capture["identity_pairs"]:
        club = player_club.get(str(pair["sportmonks_id"]))
        if club is not None and int(pair["fpl_id"]) in element_team:
            votes[int(club)][element_team[int(pair["fpl_id"])]] += 1
    mapping = {}
    for club, counter in votes.items():
        if len(counter) == 1 and sum(counter.values()) >= CLUB_CROSSWALK_MIN_PAIRS:
            mapping[club] = next(iter(counter))
    return mapping


def build_team_registry(capture: Mapping[str, Any]) -> tuple[TeamRegistry, dict[int, str]]:
    """Trial-local seeds for every club in the capture. Returns the registry and sportmonks id -> canonical id."""
    countries = {int(k): v for k, v in capture["countries"].items()}
    pl_ids = {int(t["id"]) for t in capture["teams"]}
    clubs: dict[int, dict[str, Any]] = {}
    for team in capture["teams"]:
        clubs[int(team["id"])] = {"name": team["name"], "country_id": team.get("country_id"), "gender": team.get("gender", "male")}
    for fixture in capture["team_fixtures"]:
        for participant in fixture["participants"]:
            clubs.setdefault(int(participant["id"]), {"name": participant["name"],
                                                       "country_id": participant.get("country_id"),
                                                       "gender": participant.get("gender", "male")})
    fpl_of = club_crosswalk(capture)
    missing = sorted(pl_ids - set(fpl_of))
    if missing:
        raise LiveTrialAdapterError(f"no unanimous FPL club for Sportmonks clubs {missing}")
    seeds: dict[str, TeamSeed] = {}
    crosswalks: list[TeamCrosswalk] = []
    index: dict[int, str] = {}
    owners: dict[str, int] = {}
    for sm_id, club in sorted(clubs.items()):
        country = countries.get(int(club["country_id"])) if club.get("country_id") is not None else None
        if country is None:
            raise LiveTrialAdapterError(f"club {sm_id} has no known country")
        key = _team_key(country, club["name"], club["gender"])
        if key in owners and owners[key] != sm_id:
            raise LiveTrialAdapterError(f"two provider clubs share the registry key {key}: {owners[key]} and {sm_id}")
        owners[key] = sm_id
        canonical = canonical_team_id(key)
        index[sm_id] = canonical
        jurisdiction, club_key, category, level = key.split("|")
        seeds[canonical] = TeamSeed(
            canonical_team_id=canonical, registry_key=key, display_name=club["name"], jurisdiction=jurisdiction,
            category=category, squad_level=level, valid_from=SEED_VALID_FROM, valid_to=None,
            provenance=TRIAL_SEED_PROVENANCE, status=TRIAL_SEED_STATUS,
            notes="Display name is an alias, never an identity key.")
        crosswalks.append(TeamCrosswalk("sportmonks", str(sm_id), canonical, SEED_VALID_FROM, None, TRIAL_SEED_PROVENANCE))
        if sm_id in fpl_of:
            crosswalks.append(TeamCrosswalk("fpl", str(fpl_of[sm_id]), canonical, SEED_VALID_FROM, None, TRIAL_SEED_PROVENANCE))
    return TeamRegistry(tuple(seeds.values()), tuple(crosswalks)), index


# ------------------------------------------------------------------ fixtures

def derive_fixture_keys(fixtures: Sequence[Mapping[str, Any]]) -> dict[int, str]:
    """The governed scheduling key of every fixture of one competition (see docstring)."""
    keys: dict[int, str] = {}
    by_pair: dict[frozenset, list[Mapping[str, Any]]] = defaultdict(list)
    for fixture in fixtures:
        if fixture["league_id"] == 8:
            pair = frozenset((_location(fixture, "home")["id"], _location(fixture, "away")["id"]))
            by_pair[pair].append(fixture)
        else:
            stage = slug((fixture.get("stage") or {}).get("name") or "")
            leg = fixture.get("leg") or "1/1"
            suffix = {"1/1": "single", "1/2": "leg-1", "2/2": "leg-2"}.get(leg)
            if suffix is None:
                raise LiveTrialAdapterError(f"unsupported leg {leg!r} on fixture {fixture['id']}")
            keys[int(fixture["id"])] = f"cup-{stage}-{suffix}"
    for pair, members in by_pair.items():
        ordered = sorted(members, key=lambda f: (f["starting_at"], f["id"]))
        if len(ordered) > 2:
            raise LiveTrialAdapterError(f"more than two league meetings for one pair: {sorted(pair)}")
        for number, fixture in enumerate(ordered, 1):
            keys[int(fixture["id"])] = f"league-home-meeting-{number}"
    return keys


def _competition(league_id: int) -> dict[str, str]:
    if league_id not in COMPETITIONS:
        raise LiveTrialAdapterError(f"competition {league_id} is not in the trial's governed-looking list")
    return COMPETITIONS[league_id]


def competition_ids(league_id: int, edition: str = SEASON_EDITION) -> tuple[str, str]:
    meta = _competition(league_id)
    competition_id = canonical_competition_id(meta["governing_body"], meta["registry_key"], meta["category"])
    return competition_id, canonical_season_id(competition_id, edition)


def canonical_fixtures(capture: Mapping[str, Any], index: Mapping[int, str]) -> list[dict[str, Any]]:
    """Every capture fixture with its canonical identity, status and tier, in a stable order."""
    by_league: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for fixture in capture["team_fixtures"]:
        by_league[int(fixture["league_id"])].append(fixture)
    out: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for league_id, members in sorted(by_league.items()):
        meta = _competition(league_id)
        competition_id, season_id = competition_ids(league_id)
        keys = derive_fixture_keys(members)
        for fixture in sorted(members, key=lambda f: (f["starting_at"], f["id"])):
            home, away = _location(fixture, "home"), _location(fixture, "away")
            fixture_id = canonical_fixture_id(competition_id, season_id, index[int(home["id"])],
                                              index[int(away["id"])], keys[int(fixture["id"])])
            if fixture_id in seen:
                raise LiveTrialAdapterError(
                    f"fixtures {seen[fixture_id]} and {fixture['id']} share one canonical identity")
            seen[fixture_id] = int(fixture["id"])
            out.append({
                "fixture_id": fixture_id, "provider_id": int(fixture["id"]), "league_id": league_id, "season_provider_id": int(fixture["season_id"]),
                "competition_id": competition_id, "season_id": season_id,
                "home_sm": int(home["id"]), "away_sm": int(away["id"]),
                "home_team_id": index[int(home["id"])], "away_team_id": index[int(away["id"])],
                "fixture_key": keys[int(fixture["id"])], "kickoff_utc": _utc(fixture["starting_at"]),
                "status": fixture_status(fixture), "context_stage": context_stage(fixture),
                "context_tier": meta["context_tier"],
                "gameweek": int(fixture["round"]["name"]) if league_id == 8 and (fixture.get("round") or {}).get("name", "").isdigit() else None,
            })
    return out


# ------------------------------------------------------------------ replay source for one competition

def _owned_players(capture: Mapping[str, Any]) -> list[dict[str, Any]]:
    nominal = {1: "goalkeeper", 2: "defender", 3: "midfielder", 4: "forward"}
    rows = []
    for element in capture["fpl"]["elements"]:
        rows.append({
            "fpl_id": str(element["id"]),
            "full_name": f"{element['first_name']} {element['second_name']}".strip(),
            "known_name": element["web_name"], "birth_date": (element.get("birth_date") or "")[:10] or None,
            "nationality": None, "positions": [nominal.get(element["element_type"], "unknown")]})
    return rows


def replay_source(capture: Mapping[str, Any], fixtures: Sequence[Mapping[str, Any]], league_id: int, *,
                  captured_at: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The FI-4a replay source for one competition, and the adapter's own aggregate report."""
    meta = _competition(league_id)
    mine = [f for f in fixtures if f["league_id"] == league_id]
    sm_clubs = sorted({f["home_sm"] for f in mine} | {f["away_sm"] for f in mine})
    teams_by_id = {int(t["id"]): t for t in capture["teams"]}
    names = {}
    for fixture in capture["team_fixtures"]:
        for participant in fixture["participants"]:
            names[int(participant["id"])] = participant
    team_rows = []
    for club in sm_clubs:
        source = teams_by_id.get(club) or names[club]
        team_rows.append({"id": club, "name": source["name"], "short_code": source.get("short_code") or slug(source["name"])[:3].upper()})
    report: dict[str, Any] = {"competition": meta["registry_key"], "fixtures": len(mine),
                              "completed": sum(1 for f in mine if f["status"] == "completed"), "clubs": len(sm_clubs)}
    source: dict[str, Any] = {
        "_fixture": {"version": REPLAY_VERSION, "captured_at": captured_at, "assumption_status": LIVE_TRIAL_LOCAL,
                     "source": "live Sportmonks reads, local trial capture"},
        "competition": {"id": league_id, "name": meta["name"], "governing_body": meta["governing_body"],
                        "registry_key": meta["registry_key"], "category": meta["category"], "tier": meta["tier"],
                        "country": meta["country"]},
        "season": {"id": int(mine[0]["season_provider_id"]) if mine else 0, "edition_key": SEASON_EDITION, "label": SEASON_LABEL},
        "teams": team_rows,
        "owned_players": [], "player_crosswalks": [], "players": [],
        "fixtures": [{"id": f["provider_id"], "home_team_id": f["home_sm"], "away_team_id": f["away_sm"],
                      "fixture_key": f["fixture_key"], "kickoff": f["kickoff_utc"], "status": f["status"],
                      "gameweek": f["gameweek"]} for f in mine],
        "squads": [], "lineups": [], "formations": [], "substitutions": [], "injuries": [], "suspensions": [],
        "coaches": [], "referees": [], "team_statistics": [], "player_statistics": [],
    }
    if league_id != 8:
        return source, report

    source["owned_players"] = _owned_players(capture)
    source["player_crosswalks"] = [{"sportmonks_id": str(p["sportmonks_id"]), "fpl_id": str(p["fpl_id"])}
                                   for p in capture["identity_pairs"]]
    source["players"] = [{"id": int(p["id"]), "name": p["name"]} for p in capture["players"]]
    source["squads"] = [{"id": int(s["id"]), "team_id": int(s["team_id"]), "player_id": int(s["player_id"]),
                         "valid_from": s["start"], "valid_to": s.get("end")} for s in capture["squads"]]
    completed = {f["provider_id"]: f for f in mine if f["status"] == "completed"}
    dropped = Counter()
    for detail in capture["match_detail"]:
        fixture = completed.get(int(detail["id"]))
        if fixture is None:
            continue
        formation_of = {int(r["participant_id"]): r["formation"] for r in detail.get("formations") or []}
        for team, formation in formation_of.items():
            source["formations"].append({"id": _formation_id(detail, team),
                                         "fixture_id": fixture["provider_id"], "team_id": team, "formation": formation,
                                         "source_timestamp": fixture["kickoff_utc"]})
        for row in detail.get("lineups") or []:
            started = row["type_id"] == STARTER_TYPE
            minutes = next((d["data"]["value"] for d in row.get("details") or [] if d["type_id"] == MINUTES_DETAIL_TYPE), None)
            if not started and not (minutes and minutes > 0):
                dropped["unused_substitute"] += 1
                continue
            if minutes is None:
                dropped["on_field_without_minutes"] += 1
                continue
            if int(row["team_id"]) not in formation_of:
                dropped["no_team_formation"] += 1
                continue
            position = (row.get("detailedposition") or {}).get("name")
            source["lineups"].append({
                "id": int(row["id"]), "fixture_id": fixture["provider_id"], "team_id": int(row["team_id"]),
                "player_id": int(row["player_id"]), "started": started, "minutes": int(minutes),
                "formation": formation_of[int(row["team_id"])], "grid_slot": row.get("formation_field"),
                "position": position})
        for event in detail.get("events") or []:
            if event["type_id"] != SUBSTITUTION_EVENT or not event.get("related_player_id"):
                continue
            source["substitutions"].append({
                "id": int(event["id"]), "fixture_id": fixture["provider_id"], "team_id": int(event["participant_id"]),
                "player_off_id": int(event["related_player_id"]), "player_on_id": int(event["player_id"]),
                "minute": int(event["minute"])})
    report["lineup_rows"] = len(source["lineups"])
    report["dropped_lineup_rows"] = dict(sorted(dropped.items()))
    report["substitutions"] = len(source["substitutions"])
    return source, report


def _formation_id(detail: Mapping[str, Any], team: int) -> int:
    for row in detail["formations"]:
        if int(row["participant_id"]) == team:
            return int(row["id"])
    raise LiveTrialAdapterError("formation row vanished")


# ------------------------------------------------------------------ context v2

def context_payload(capture: Mapping[str, Any], fixtures: Sequence[Mapping[str, Any]], index: Mapping[int, str], *,
                    captured_at: str) -> dict[str, Any]:
    """The canonical-context-v2 source: all competitions, scheduling knowledge per the module docstring."""
    trace = {"source_provider": "sportmonks", "source_timestamp": captured_at, "assumption_status": LIVE_TRIAL_LOCAL}
    leagues = sorted({f["league_id"] for f in fixtures})
    competitions = [{"competition_id": competition_ids(lid)[0], **trace} for lid in leagues]
    seasons = [{"season_id": competition_ids(lid)[1], "competition_id": competition_ids(lid)[0], **trace} for lid in leagues]
    clubs = sorted({f["home_sm"] for f in fixtures} | {f["away_sm"] for f in fixtures})
    teams = [{"team_id": index[c], **trace} for c in clubs]
    memberships, seen = [], set()
    for f in fixtures:
        for club in (f["home_sm"], f["away_sm"]):
            key = (f["competition_id"], f["season_id"], index[club])
            if key in seen:
                continue
            seen.add(key)
            memberships.append({"competition_id": f["competition_id"], "season_id": f["season_id"], "team_id": index[club],
                                "effective_from_utc": SCHEDULE_PUBLISHED_AT, "effective_to_utc": None, **trace})
    ctx_fixtures = [{"fixture_id": f["fixture_id"], "competition_id": f["competition_id"], "season_id": f["season_id"],
                     "home_team_id": f["home_team_id"], "away_team_id": f["away_team_id"],
                     "competition_stage": f["context_stage"], **trace} for f in fixtures]
    snapshots = []
    for f in fixtures:
        snapshots.append({"fixture_id": f["fixture_id"], "observed_at_utc": SCHEDULE_PUBLISHED_AT,
                          "scheduled_kickoff_utc": f["kickoff_utc"], "status": "scheduled",
                          "competition_tier": f["context_tier"], **trace})
        if f["status"] != "scheduled":
            known_at = _plus_hours(f["kickoff_utc"], RESULT_KNOWN_AFTER_HOURS if f["status"] == "completed" else 0)
            snapshots.append({"fixture_id": f["fixture_id"], "observed_at_utc": known_at,
                              "scheduled_kickoff_utc": f["kickoff_utc"], "status": f["status"],
                              "competition_tier": f["context_tier"], **trace})
    return {"version": REPLAY_VERSION, "captured_at": captured_at, "canonical": {
        "competitions": competitions, "seasons": seasons, "teams": teams, "fixtures": ctx_fixtures,
        "competition_memberships": memberships, "fixture_schedule_snapshots": snapshots,
        "team_standing_snapshots": []}}


# ------------------------------------------------------------------ reading the local store back

class LiveTrialBuildHandle:
    """The base-store handle FI-5b needs, for a store built locally by this adapter.

    ``RuntimeBuildHandle`` reads the pointer a *synchronized* cache holds (remote
    schema) and refuses live-trial provenance; a store built here carries the local
    builder's pointer. This handle reads that one, validates the build, and insists
    on ``live_trial_local`` so it cannot be used to open any other store.
    """

    def __init__(self, root: Path) -> None:
        self.cache_root = Path(root)

    def manifest(self) -> dict:
        from .builder import resolve_contained_build_directory, validate_build

        pointer = json.loads((self.cache_root / "_football_latest.json").read_text(encoding="utf-8"))
        manifest = validate_build(resolve_contained_build_directory(self.cache_root / "builds", pointer.get("build_id")))
        if LIVE_TRIAL_LOCAL not in manifest.get("assumption_status_summary", {}):
            raise LiveTrialAdapterError("LiveTrialBuildHandle opens only live_trial_local stores")
        return manifest

    def dataset_path(self, entity: str) -> Path:
        manifest = self.manifest()
        if entity not in manifest["entity_files"]:
            raise KeyError(entity)
        return (self.cache_root / "builds" / manifest["build_id"] / manifest["entity_files"][entity]).resolve()


# ------------------------------------------------------------------ orchestration

def build_store(capture_path: Path, root: Path, *, build_id: str = "live-trial", captured_at: str | None = None) -> dict[str, Any]:
    """Build every store under ``root`` and return the adapter's aggregate report (no names, no ids)."""
    from .builder import build_from_fixture
    from .builder_v2 import build_context_v2

    capture = json.loads(Path(capture_path).read_text(encoding="utf-8"))
    if capture.get("schema_version") != CAPTURE_SCHEMA_VERSION:
        raise LiveTrialAdapterError("unsupported capture schema version")
    stamp = captured_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    registry, index = build_team_registry(capture)
    fixtures = canonical_fixtures(capture, index)
    report: dict[str, Any] = {"build_id": build_id, "assumption_status": LIVE_TRIAL_LOCAL, "competitions": [],
                              "teams": len(index), "trial_local_seeds": len(registry.teams),
                              "fixtures_total": len(fixtures)}
    (root / "source").mkdir(parents=True, exist_ok=True)
    for league_id in sorted({f["league_id"] for f in fixtures}):
        source, summary = replay_source(capture, fixtures, league_id, captured_at=stamp)
        meta = COMPETITIONS[league_id]
        path = root / "source" / f"{meta['registry_key']}.replay.json"
        path.write_text(json.dumps(source, ensure_ascii=False, sort_keys=True), encoding="utf-8", newline="\n")
        manifest = build_from_fixture(path, root / "v1" / meta["registry_key"], build_id=build_id, built_at=stamp,
                                      team_registry=registry, source_kind="local-live-trial")
        summary["row_counts"] = manifest["row_counts"]
        summary["quarantine_counts"] = manifest["quarantine_counts"]
        report["competitions"].append(summary)
    context_source = root / "source" / "context.json"
    context_source.write_text(json.dumps(context_payload(capture, fixtures, index, captured_at=stamp), sort_keys=True),
                              encoding="utf-8", newline="\n")
    context = build_context_v2(context_source, root / "context", build_id=build_id, built_at=stamp, provenance=LIVE_TRIAL_LOCAL)
    report["context_row_counts"] = context["row_counts"]
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="live_trial", description="Build local live-trial stores from a frozen capture.")
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--build-id", default="live-trial")
    args = parser.parse_args(argv)
    print(json.dumps(build_store(args.capture, args.root, build_id=args.build_id), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
