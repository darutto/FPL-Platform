"""
fpl_tactical.strikerapi_ingest
==============================
StrikerAPI shots -> the owned shot schema, with the checks that decide
whether a store may be published.

Pure functions first (normalize, validate, canaries), then the two commands
that spend credits (``sync`` daily and cheap, ``load_by_team`` once).

Coordinates
-----------
The store's frame IS Understat's. StrikerAPI -> store::

    x_store = 1 - x_api / 2        y_store = 1 - y_api      (y is MIRRORED)

Pinned in tests on the penalty spot (x_api 0.23 -> 0.885) and one shot per
flank. A wrong sign on y swaps every flank, so the vendor flipping an axis is
also watched by two live canaries, not only by fixtures.

``situation``: StrikerAPI has no situation field. Penalties are labelled from
its ``penalty`` flag; every other row has ``situation = None`` (unknown) and
consumers must treat unknown as unknown, never as open play.
"""

from __future__ import annotations

import html
import json
import os
import re
import unicodedata
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

import pandas as pd

from fpl_tactical import PENALTY_SITUATION, store
from fpl_tactical.paths import (
    SOURCE_STRIKERAPI,
    source_pointer_path,
    source_shots_path,
)
from fpl_tactical.strikerapi_client import (
    COST_LIST_GAMES,
    COST_SHOT_MAP,
    StrikerApiClient,
    games_page,
    parse_data,
    shots_of,
)
from fpl_tactical.strikerapi_raw import RawCache
from fpl_tactical.teams import API_CODE_TO_STORE, store_name_from_api, store_name_from_fpl

SHOT_COLUMNS: list[str] = [
    "season", "match_id", "date", "shooting_team", "conceding_team", "player",
    "is_home_shot", "minute", "x", "y", "xg", "situation", "shot_type", "result",
]
_PRIVATE = ["_player_id"]

#: Today's store vocabulary (verified on the 2025-26 store). Values the
#: source sends that are not listed here fail the run.
RESULT_MAP: dict[str, str] = {
    "goal": "Goal",
    "saved": "Saved Shot",
    "missed": "Missed Shot",
    "blocked": "Blocked Shot",
    "woodwork": "Shot On Post",
}
#: The 2025-26 store holds exactly two values, "Left Foot" and "Right Foot",
#: and null for every other shot (checked on the real store).
#: A header or an unnamed body part is therefore stored as null.
SHOT_TYPE_MAP: dict[object, str | None] = {
    "left_foot": "Left Foot",
    "right_foot": "Right Foot",
    "header": None,
    None: None,
}

#: Full time is assumed at kickoff + 2 h. The source refreshes a match for
#: about 36 h after full time, so a match is fetched ONCE, after that window.
#: No refetches.
FULL_TIME_AFTER_KICKOFF = timedelta(hours=2)
SETTLE_AFTER_FULL_TIME = timedelta(hours=36)
#: A due match still absent from list_games this long after it was due
#: raises an alert (-> the one GitHub issue).
MISSING_ALERT_AFTER = timedelta(days=3)

DEFAULT_MAX_CREDITS = 130
FIRST_LOAD_MAX_CREDITS = COST_LIST_GAMES + 20 * COST_SHOT_MAP  # 202

# First-load canary (overlap with the other source's rows).
# Measured on 2025-26, four clubs, this source against the real store (paired
# shots; whole season, first 6/11/13 matches, ten 11-match windows):
# zone agreement 0.945-0.974, opposite flank 0.000, shots ratio 0.942-0.977.
# The same rows with y mirrored: zone agreement 0.655, opposite flank 0.218.
CANARY_MIN_MATCHES = 20
CANARY_MIN_MATCHED_SHOTS = 200
CANARY_ZONE_AGREE_MIN = 0.90
CANARY_OPPOSITE_FLANK_MAX = 0.02
CANARY_SHOTS_PER_MATCH_TOL = 0.15
# Every-sync pooled known-flank canary. The pool is the matches no verdict has
# covered yet, never the whole store (old rows would hide a new flip). Every
# pooled shot is on one flank or the other, so one limit says it all.
# Measured as above: opposite share 0.115-0.12 over the season, up to 0.175 in
# pools of about 40 shots (a 0.15 limit raised 1 false alarm in 5); mirrored
# 0.885. Only four clubs' shots, so 3-13 known-flank players.
FLANK_CANARY_MIN_POOLED = 40
FLANK_CANARY_OPPOSITE_MAX = 0.25
FLANK_PLAYER_MIN_SHOTS = 8
FLANK_PLAYER_PURITY = 0.80
FLANK_CANARY_MAX_PLAYERS = 25

# Zone geometry. Mirrors fpl_grounded_assistant.zonal_weakness (a test in that
# package pins the two together).
IN_BOX_MIN_X = 0.84
EDGE_MIN_X = 0.70
RIGHT_MAX_Y = 0.36
LEFT_MIN_Y = 0.64


class IngestError(RuntimeError):
    """Bad source data: the run fails and nothing is written."""


class ValidationFailed(IngestError):
    """One or more publish checks failed; ``problems`` lists them."""

    def __init__(self, problems: list[str]):
        more = f" (+{len(problems) - 6} more)" if len(problems) > 6 else ""
        super().__init__("; ".join(problems[:6]) + more)
        self.problems = problems


class SyncRefused(RuntimeError):
    """Not enough credits for what is due, or over the ceiling."""


# ---------------------------------------------------------------------------
# Coordinates and zones
# ---------------------------------------------------------------------------

def api_to_store_xy(x_api: float, y_api: float) -> tuple[float, float]:
    """StrikerAPI (x, y) -> the store's Understat frame. y is mirrored."""
    return 1.0 - x_api / 2.0, 1.0 - y_api


def flank_zone(x: float, y: float) -> str | None:
    """``"in-box / left"`` etc. in the store frame, or None for long range."""
    if x >= IN_BOX_MIN_X:
        depth = "in-box"
    elif x >= EDGE_MIN_X:
        depth = "edge-of-box"
    else:
        return None
    lat = "right" if y < RIGHT_MAX_Y else "left" if y > LEFT_MIN_Y else "central"
    return f"{depth} / {lat}"


def _flank(zone: str | None) -> str | None:
    if zone is None:
        return None
    lat = zone.split(" / ")[1]
    return lat if lat in ("left", "right") else None


# ---------------------------------------------------------------------------
# Normalize
# ---------------------------------------------------------------------------

def schedule_from_games(games: Iterable[dict]) -> dict[str, dict]:
    """``{game_id: {date, kickoff, home, away, final}}`` in store team names."""
    out: dict[str, dict] = {}
    for g in games:
        home = store_name_from_api(g["home"]["abbrev"])
        away = store_name_from_api(g["away"]["abbrev"])
        starts = str(g.get("starts_at") or "")
        try:
            kickoff = datetime.fromisoformat(starts.replace("Z", "+00:00"))
        except ValueError:
            raise IngestError(f"game {g.get('game_id')} has no readable starts_at") from None
        kickoff = kickoff.astimezone(timezone.utc)
        out[str(g["game_id"])] = {
            "date": kickoff.strftime("%Y-%m-%dT%H:%M:%S"),
            "kickoff": kickoff,
            "home": home,
            "away": away,
            "final": g.get("status") == "final",
        }
    return out


def normalize_shots(shots: Iterable[dict], schedule: dict[str, dict], season: str) -> pd.DataFrame:
    """Raw StrikerAPI shot dicts -> the owned schema. Pure; fails on anything unknown."""
    rows = []
    for s in shots:
        gid = str(s.get("game_id"))
        game = schedule.get(gid)
        if game is None:
            raise IngestError(f"shot in game {gid} absent from the game list")
        team = store_name_from_api(str(s.get("team")))
        if team == game["home"]:
            is_home, conceding = True, game["away"]
        elif team == game["away"]:
            is_home, conceding = False, game["home"]
        else:
            raise IngestError(f"shot team {team!r} is neither side of game {gid}")
        outcome = s.get("outcome")
        if outcome not in RESULT_MAP:
            raise IngestError(f"unknown shot outcome {outcome!r}")
        body = s.get("body_part")
        if body not in SHOT_TYPE_MAP:
            raise IngestError(f"unknown body_part {body!r}")
        penalty = s.get("penalty")
        if not isinstance(penalty, bool):
            raise IngestError("shot without a boolean penalty flag")
        x_api, y_api = s.get("x"), s.get("y")
        if not isinstance(x_api, (int, float)) or not isinstance(y_api, (int, float)):
            raise IngestError("shot without numeric coordinates")
        x, y = api_to_store_xy(float(x_api), float(y_api))
        rows.append({
            "season": season,
            "match_id": int(gid),
            "date": game["date"],
            "shooting_team": team,
            "conceding_team": conceding,
            "player": html.unescape(str(s.get("player"))),
            "is_home_shot": is_home,
            "minute": int(s["minute"]),
            "x": x,
            "y": y,
            "xg": float(s["xg"]),
            "situation": PENALTY_SITUATION if penalty else None,
            "shot_type": SHOT_TYPE_MAP[body],
            "result": RESULT_MAP[outcome],
        })
    return pd.DataFrame(rows, columns=SHOT_COLUMNS)


def _store_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df[SHOT_COLUMNS].copy()
    for col in ("situation", "shot_type"):
        out[col] = out[col].astype(object).where(out[col].notna(), None)
    return out


# ---------------------------------------------------------------------------
# FPL fixtures (free) -- decide what is due and carry the scores
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FplFixture:
    fpl_id: int
    gameweek: int | None
    home: str
    away: str
    kickoff: datetime
    finished: bool
    home_score: int | None
    away_score: int | None
    own_goals_for_home: int = 0  # own goals by away players, credited to home
    own_goals_for_away: int = 0

    @property
    def due_at(self) -> datetime:
        return self.kickoff + FULL_TIME_AFTER_KICKOFF + SETTLE_AFTER_FULL_TIME


def _fpl_get(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "python-client"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed https host
        return json.loads(resp.read().decode("utf-8"))


def fetch_fpl_fixtures(get: Callable[[str], object] = _fpl_get) -> list[FplFixture]:
    base = "https://fantasy.premierleague.com/api/"
    boot = get(base + "bootstrap-static/")
    short = {t["id"]: t["short_name"] for t in boot["teams"]}  # type: ignore[index]
    out: list[FplFixture] = []
    for f in get(base + "fixtures/"):  # type: ignore[union-attr]
        if not f.get("kickoff_time"):
            continue
        own_h = own_a = 0
        for stat in f.get("stats") or []:
            if stat.get("identifier") == "own_goals":
                # side "h" lists own goals by HOME players: goals for the away side
                own_a += sum(int(v["value"]) for v in stat.get("h") or [])
                own_h += sum(int(v["value"]) for v in stat.get("a") or [])
        out.append(FplFixture(
            fpl_id=int(f["id"]),
            gameweek=f.get("event"),
            home=store_name_from_fpl(short[f["team_h"]]),
            away=store_name_from_fpl(short[f["team_a"]]),
            kickoff=datetime.fromisoformat(f["kickoff_time"].replace("Z", "+00:00")),
            finished=bool(f.get("finished")) and not f.get("finished_provisional", False),
            home_score=f.get("team_h_score"),
            away_score=f.get("team_a_score"),
            own_goals_for_home=own_h,
            own_goals_for_away=own_a,
        ))
    return out


def _match_pair(g: pd.DataFrame) -> tuple[str, str]:
    r = g.iloc[0]
    if r["is_home_shot"]:
        return r["shooting_team"], r["conceding_team"]
    return r["conceding_team"], r["shooting_team"]


def stored_pairs(df: pd.DataFrame | None) -> set[tuple[str, str]]:
    """(home, away) of every match already stored."""
    if df is None or not len(df):
        return set()
    return {_match_pair(g) for _, g in df.groupby("match_id")}


def due_fixtures(fixtures: list[FplFixture], stored: pd.DataFrame | None, now: datetime) -> list[FplFixture]:
    have = stored_pairs(stored)
    return sorted(
        (f for f in fixtures if f.finished and f.due_at <= now and (f.home, f.away) not in have),
        key=lambda f: f.kickoff,
    )


# ---------------------------------------------------------------------------
# Validation (fail closed)
# ---------------------------------------------------------------------------

def validate_store(df: pd.DataFrame, fixtures: list[FplFixture], now: datetime) -> list[str]:
    """Problems that block publishing. Empty list = all checks passed.

    Every due finished match present; both teams have shots; goals per match
    = FPL's score, own goals taken from FPL's own_goals stat; coordinates in
    range; no duplicate shots.

    An FPL score correction after a match was stored changes the expected
    score, so the next run reports a goals mismatch for that match and
    publishes nothing until a human decides; there is no automatic refetch.
    """
    problems: list[str] = []
    by_pair = {_match_pair(g): g for _, g in df.groupby("match_id")}
    for f in fixtures:
        if not (f.finished and f.due_at <= now):
            continue
        g = by_pair.get((f.home, f.away))
        label = f"{f.home}-{f.away} (GW{f.gameweek})"
        if g is None:
            problems.append(f"missing match {label}")
            continue
        h, a = g[g["is_home_shot"]], g[~g["is_home_shot"]]
        if not len(h) or not len(a):
            problems.append(f"match {label} has no shots for one side")
        if f.home_score is None or f.away_score is None:
            problems.append(f"match {label} has no FPL score to check")
            continue
        goals_h = int((h["result"] == "Goal").sum()) + f.own_goals_for_home
        goals_a = int((a["result"] == "Goal").sum()) + f.own_goals_for_away
        if (goals_h, goals_a) != (f.home_score, f.away_score):
            problems.append(
                f"goals differ from FPL in {label}: store {goals_h}-{goals_a}, FPL {f.home_score}-{f.away_score}"
            )
    if ((df["x"] < 0) | (df["x"] > 1) | (df["y"] < 0) | (df["y"] > 1)).any():
        problems.append("coordinates outside 0-1")
    ndup = int(df.duplicated(["match_id", "shooting_team", "player", "minute", "x", "y"]).sum())
    if ndup:
        problems.append(f"{ndup} duplicate shots")
    return problems


# ---------------------------------------------------------------------------
# One season = one source
# ---------------------------------------------------------------------------
# The two sources have different xG models (per-shot correlation 0.71), so rows
# of both, or of two seasons, must never meet in one store or one comparison.

def check_backup(backup: pd.DataFrame, season: str) -> None:
    """The first-load reference must be the OTHER source's rows of THIS season.

    ``compare_with_backup`` pairs matches by (home, away) with no date: another
    season's rows would "overlap" and compare different matches. A file of this
    source's own rows would agree with itself; it is told apart by having no
    known situation outside penalties. Raises before any credit is spent.
    """
    seasons = sorted({str(s) for s in backup["season"].unique()})
    if seasons != [season]:
        raise IngestError(f"backup rows are of season(s) {seasons}, expected only {season}")
    open_rows = backup[backup["situation"] != PENALTY_SITUATION]
    if not len(open_rows) or open_rows["situation"].isna().all():
        raise IngestError("backup rows carry no situation: they are not the other source's store")


def _check_working_store(df: pd.DataFrame, pointer: dict | None, season: str) -> None:
    """Refuse to append to a working store of another source or season."""
    source = (pointer or {}).get("source")
    if source != SOURCE_STRIKERAPI:
        raise IngestError(f"working store source is {source!r}: one season is one source, nothing appended")
    seasons = sorted({str(s) for s in df["season"].unique()} | {str((pointer or {}).get("season"))})
    if seasons != [season]:
        raise IngestError(f"working store holds season(s) {seasons}, expected only {season}")


# ---------------------------------------------------------------------------
# Canaries (mismatch fails closed; too little data says "not_checked")
# ---------------------------------------------------------------------------

def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z]+", " ", s.lower()).strip()


def _pair_key(df: pd.DataFrame) -> pd.Series:
    home = df["shooting_team"].where(df["is_home_shot"], df["conceding_team"])
    away = df["conceding_team"].where(df["is_home_shot"], df["shooting_team"])
    return home + "|" + away


def compare_with_backup(new: pd.DataFrame, backup: pd.DataFrame) -> dict:
    """First-load canary: our overlap with the other source's rows for the same matches.

    Shots are paired one-to-one inside (match, shooting team) by minute (+-1)
    then nearest position. ``status`` is ``ok`` / ``mismatch`` / ``not_checked``.
    """
    n = new[new["situation"] != PENALTY_SITUATION].assign(_pair=lambda d: _pair_key(d))
    b = backup[backup["situation"] != PENALTY_SITUATION].assign(_pair=lambda d: _pair_key(d))
    overlap = sorted(set(n["_pair"]) & set(b["_pair"]))
    n, b = n[n["_pair"].isin(overlap)], b[b["_pair"].isin(overlap)]

    matched = agree = opposite = 0
    for (pair, team), gn in n.groupby(["_pair", "shooting_team"]):
        gb = b[(b["_pair"] == pair) & (b["shooting_team"] == team)]
        used: set = set()
        for _, row in gn.iterrows():
            best, best_d = None, 1e9
            for idx, cand in gb.iterrows():
                # Pair on minute and depth (x is never mirrored); y is what is
                # being checked, so it must not decide who pairs with whom.
                if (idx in used or abs(int(cand["minute"]) - int(row["minute"])) > 1
                        or abs(cand["x"] - row["x"]) > 0.08):
                    continue
                d = (cand["x"] - row["x"]) ** 2 + (cand["y"] - row["y"]) ** 2
                if d < best_d:
                    best, best_d = idx, d
            if best is None:
                continue
            used.add(best)
            matched += 1
            zn = flank_zone(row["x"], row["y"])
            zb = flank_zone(gb.loc[best, "x"], gb.loc[best, "y"])
            agree += zn == zb
            fn, fb = _flank(zn), _flank(zb)
            opposite += bool(fn and fb and fn != fb)

    result: dict = {"kind": "backup_overlap", "overlap_matches": len(overlap), "matched_shots": matched}
    if len(overlap) < CANARY_MIN_MATCHES or matched < CANARY_MIN_MATCHED_SHOTS:
        return {**result, "status": "not_checked",
                "reason": f"sample too small ({len(overlap)} matches, {matched} matched shots)"}
    result["zone_agreement"] = round(agree / matched, 4)
    result["opposite_flank"] = round(opposite / matched, 4)
    result["shots_per_match_ratio"] = round(len(n) / len(b), 4)
    ok = (
        result["zone_agreement"] >= CANARY_ZONE_AGREE_MIN
        and result["opposite_flank"] <= CANARY_OPPOSITE_FLANK_MAX
        and abs(result["shots_per_match_ratio"] - 1.0) <= CANARY_SHOTS_PER_MATCH_TOL
    )
    return {**result, "status": "ok" if ok else "mismatch"}


def pick_flank_players(trusted: pd.DataFrame) -> dict[str, list[str]]:
    """Players with a strongly one-sided record in the TRUSTED (other-source) rows.

    The side is measured, never hand-written: at least FLANK_PLAYER_MIN_SHOTS
    left/right edge-or-box shots with FLANK_PLAYER_PURITY of them on one side.
    Names are returned normalized, highest volume first.
    """
    t = trusted[trusted["situation"] != PENALTY_SITUATION]
    cands: list[tuple[int, str, str]] = []
    for player, g in t.groupby("player"):
        sides = [_flank(flank_zone(x, y)) for x, y in zip(g["x"], g["y"])]
        left, right = sides.count("left"), sides.count("right")
        tot = left + right
        if tot < FLANK_PLAYER_MIN_SHOTS:
            continue
        if left / tot >= FLANK_PLAYER_PURITY:
            cands.append((tot, _norm(str(player)), "left"))
        elif right / tot >= FLANK_PLAYER_PURITY:
            cands.append((tot, _norm(str(player)), "right"))
    cands.sort(reverse=True)
    out: dict[str, list[str]] = {"left": [], "right": []}
    for _, name, side in cands:
        if len(out[side]) < FLANK_CANARY_MAX_PLAYERS and name not in out[side]:
            out[side].append(name)
    return out


def flank_canary(df: pd.DataFrame, players: dict[str, list[str]]) -> dict:
    """Pooled known-flank check on stored data; ``not_checked`` when the sample is small."""
    d = df[df["situation"] != PENALTY_SITUATION]
    names = d["player"].map(lambda s: _norm(str(s)))
    same = opp = 0
    for side, other in (("left", "right"), ("right", "left")):
        sub = d[names.isin(players.get(side, []))]
        for x, y in zip(sub["x"], sub["y"]):
            f = _flank(flank_zone(x, y))
            same += f == side
            opp += f == other
    pooled = same + opp
    result: dict = {"kind": "known_flank", "pooled_shots": pooled}
    if pooled < FLANK_CANARY_MIN_POOLED:
        return {**result, "status": "not_checked",
                "reason": f"pooled sample {pooled} < {FLANK_CANARY_MIN_POOLED}"}
    result["same_flank"] = round(same / pooled, 4)
    result["opposite_flank"] = round(opp / pooled, 4)
    ok = result["opposite_flank"] <= FLANK_CANARY_OPPOSITE_MAX
    return {**result, "status": "ok" if ok else "mismatch"}


# ---------------------------------------------------------------------------
# The StrikerAPI working store (never the serving path)
# ---------------------------------------------------------------------------

def read_working_store(season: str) -> tuple[pd.DataFrame | None, dict | None]:
    sp = source_shots_path(season, SOURCE_STRIKERAPI)
    pp = source_pointer_path(season, SOURCE_STRIKERAPI)
    df = pd.read_parquet(sp) if sp.exists() else None
    ptr = json.loads(pp.read_text(encoding="utf-8")) if pp.exists() else None
    return df, ptr


def write_working_store(df: pd.DataFrame, pointer: dict, season: str) -> None:
    store._write_parquet_atomic(_store_frame(df), source_shots_path(season, SOURCE_STRIKERAPI))
    dest = source_pointer_path(season, SOURCE_STRIKERAPI)
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(pointer, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(dest))


def _api_season(season: str) -> int:
    return int(season[:4])


def _build_pointer(df: pd.DataFrame, season: str, canaries: dict, fixtures: list[FplFixture],
                   now: datetime, flank_players: dict | None,
                   flank_pending: Iterable[int] = ()) -> dict:
    gw_by_pair = {(f.home, f.away): f.gameweek for f in fixtures if f.finished}
    gws = [gw_by_pair.get(p) for p in stored_pairs(df)]
    gws = [g for g in gws if g is not None]
    ptr = {
        "season": season,
        "ingested_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": SOURCE_STRIKERAPI,
        "source_version": "strikerapi v1",
        "n_matches": int(df["match_id"].nunique()),
        "n_shots": int(len(df)),
        "newest_shot_date": str(df["date"].max()),
        "data_through_gw": max(gws) if gws else None,
        "situation": "unknown",
        "validation": {"status": "ok", "checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
        "canaries": canaries,
        # matches stored since the last known-flank verdict
        "flank_pending_matches": sorted(int(m) for m in flank_pending),
    }
    if flank_players:
        ptr["flank_players"] = flank_players
    return ptr


# ---------------------------------------------------------------------------
# Kept responses first: a match with a raw file is never fetched again
# ---------------------------------------------------------------------------

def _keep_responses(client: StrikerApiClient, cache: RawCache, now: datetime) -> None:
    client.on_response = lambda tool, request, text: cache.put(tool, request, text, now)


def _kept_games(cache: RawCache) -> list[dict] | None:
    """The kept ``list_games`` pages, or None when the chain is incomplete."""
    games: list[dict] = []
    offset = 0
    for _ in range(10):
        kept = cache.get(f"list_games_{offset}")
        if kept is None:
            return None
        page, nxt = games_page(parse_data("list_games", kept["body"]))
        games.extend(page)
        if not nxt:
            return games
        offset = int(nxt)  # type: ignore[arg-type]
    return None


def _final_pairs(sched: dict[str, dict]) -> dict[tuple[str, str], str]:
    return {(g["home"], g["away"]): gid for gid, g in sched.items() if g["final"]}


def _kept_schedule(cache: RawCache) -> dict[str, dict]:
    return schedule_from_games(_kept_games(cache) or [])


def _shots_for_game(client: StrikerApiClient, cache: RawCache, gid: str) -> list[dict]:
    kept = cache.get(gid)
    if kept is not None:
        return shots_of(parse_data("get_shot_map", kept["body"]))
    return client.shot_map_for_game(gid)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@dataclass
class SyncReport:
    action: str  # "nothing_due" | "synced"
    due: int = 0
    fetched: int = 0
    credits_estimated: int = 0
    credits_spent: int = 0
    credits_remaining: int | None = None
    missing_alerts: list[str] = field(default_factory=list)
    canaries: dict = field(default_factory=dict)


def sync(
    season: str,
    client: StrikerApiClient,
    fixtures: list[FplFixture],
    now: datetime | None = None,
    max_credits: int = DEFAULT_MAX_CREDITS,
    cache: RawCache | None = None,
) -> SyncReport:
    """Daily job: store finished matches that are >= 36 h past full time and not stored.

    Nothing due -> no API call, zero credits. A match whose response is already
    kept costs nothing, whatever an earlier validation said of it; so a run that
    failed a check re-validates from the kept files for free. ``list_games`` (2)
    is asked only when a due match is not in the kept list. Only what must be
    paid counts against *max_credits* and the source's remaining credits. A
    stored match is never refetched.
    """
    now = now or datetime.now(tz=timezone.utc)
    cache = cache or RawCache(season)
    current, prior = read_working_store(season)
    if current is None:
        raise SyncRefused("no StrikerAPI store yet: run strikerapi-load first (explicit, 202 credits)")
    _check_working_store(current, prior, season)
    due = due_fixtures(fixtures, current, now)
    if not due:
        return SyncReport(action="nothing_due")

    sched = _kept_schedule(cache)
    by_pair = _final_pairs(sched)
    need_list = any((f.home, f.away) not in by_pair for f in due)
    unpaid = [f for f in due
              if (f.home, f.away) not in by_pair or cache.get(by_pair[(f.home, f.away)]) is None]
    estimate = (COST_LIST_GAMES if need_list else 0) + COST_SHOT_MAP * len(unpaid)
    if estimate > max_credits:
        raise SyncRefused(
            f"{len(unpaid)} matches to fetch need {estimate} credits, over the ceiling of {max_credits}; "
            f"raise --max-credits on purpose"
        )
    if estimate:
        cache.check_writable()
        _keep_responses(client, cache, now)

    if need_list:
        sched = schedule_from_games(client.list_games(_api_season(season)))
        by_pair = _final_pairs(sched)
    alerts: list[str] = []
    todo: list[str] = []
    for f in due:
        gid = by_pair.get((f.home, f.away))
        if gid is None:
            if now - f.due_at >= MISSING_ALERT_AFTER:
                alerts.append(
                    f"{f.home}-{f.away} (GW{f.gameweek}) due since {f.due_at:%Y-%m-%d} but absent from the source"
                )
            continue
        todo.append(gid)
    need = COST_SHOT_MAP * sum(cache.get(gid) is None for gid in todo)
    if client.credits_remaining is not None and need > client.credits_remaining:
        raise SyncRefused(
            f"the matches to fetch need {need} credits, the source reports {client.credits_remaining} remaining"
        )
    base = dict(due=len(due), credits_estimated=estimate, missing_alerts=alerts)
    if not todo:
        return SyncReport(action="nothing_due", credits_spent=client.credits_spent,
                          credits_remaining=client.credits_remaining, **base)

    frames = [normalize_shots(_shots_for_game(client, cache, gid), sched, season) for gid in todo]
    # An empty answer has untyped columns: leave it out, validate_store reports the match as missing.
    merged = pd.concat([_store_frame(current)] + [f for f in frames if len(f)], ignore_index=True)
    problems = validate_store(merged, fixtures, now)
    players = (prior or {}).get("flank_players")
    pending = {int(m) for m in (prior or {}).get("flank_pending_matches") or []}
    pending |= {int(m) for frame in frames for m in frame["match_id"].unique()}
    if players:
        flank = flank_canary(merged[merged["match_id"].isin(pending)], players)
        flank["pooled_matches"] = len(pending)
        if flank["status"] == "ok":
            pending = set()
        if flank["status"] == "mismatch":
            problems.append(f"flank canary mismatch: {flank}")
    else:
        flank = {"kind": "known_flank", "status": "not_checked", "reason": "no flank players recorded"}
    if problems:
        raise ValidationFailed(problems)
    canaries = {**(prior or {}).get("canaries", {}), "known_flank": flank}
    write_working_store(merged, _build_pointer(merged, season, canaries, fixtures, now, players, pending), season)
    return SyncReport(action="synced", fetched=len(todo), credits_spent=client.credits_spent,
                      credits_remaining=client.credits_remaining, canaries=canaries, **base)


def load_by_team(
    season: str,
    client: StrikerApiClient,
    fixtures: list[FplFixture],
    backup: pd.DataFrame,
    now: datetime | None = None,
    max_credits: int = FIRST_LOAD_MAX_CREDITS,
    cache: RawCache | None = None,
) -> SyncReport:
    """One-time whole-season load: list_games + one get_shot_map per team (202 credits).

    Keeps only matches that are due (>= 36 h past full time) so nothing loaded
    here is later revised. *backup* is the other source's rows for the same
    season: the first-load canary must say ``ok`` (``not_checked`` also
    refuses) before anything is written. Replaces the whole working store.

    Every response is kept, so running it again after a failed check costs
    nothing. A team file only counts for the matches that were due when it was
    fetched; a match that became due later is fetched on its own (10, once).
    """
    now = now or datetime.now(tz=timezone.utc)
    cache = cache or RawCache(season)
    check_backup(backup, season)
    names = sorted({f.home for f in fixtures} | {f.away for f in fixtures})
    code_of = {v: k for k, v in API_CODE_TO_STORE.items()}
    due = due_fixtures(fixtures, None, now)
    due_pairs = {(f.home, f.away) for f in due}

    sched = _kept_schedule(cache)
    need_list = not due_pairs <= set(_final_pairs(sched))
    unpaid_teams = [n for n in names if cache.get(f"team_{code_of[n]}") is None]
    cost = (COST_LIST_GAMES if need_list else 0) + COST_SHOT_MAP * len(unpaid_teams)
    if cost > max_credits:
        raise SyncRefused(f"first load needs {cost} credits, over {max_credits}")
    cache.check_writable()
    _keep_responses(client, cache, now)
    if need_list:
        sched = schedule_from_games(client.list_games(_api_season(season)))
    need = COST_SHOT_MAP * len(unpaid_teams)
    if client.credits_remaining is not None and need > client.credits_remaining:
        raise SyncRefused(
            f"first load needs {need} more credits, the source reports {client.credits_remaining}"
        )

    team_shots: dict[str, list[dict]] = {}
    team_fetched: dict[str, datetime] = {}
    for name in names:
        code = code_of[name]
        key = f"team_{code}"
        kept = cache.get(key)
        if kept is None:
            client.shot_map_for_team(code, _api_season(season))
            kept = cache.get(key)
        team_fetched[name] = datetime.fromisoformat(kept["fetched_at"])
        # A match is in both teams' calls: each call contributes only the asked
        # team's shots, so a shot can never be taken twice. (The captures hold
        # one side only; a missing side fails validate_store.)
        team_shots[name] = [s for s in shots_of(parse_data("get_shot_map", kept["body"]))
                            if s.get("team") == code]

    pair_ids = _final_pairs(sched)
    from_teams: set[str] = set()
    later: list[str] = []  # due now, but not yet due when a team file was fetched
    for f in due:
        gid = pair_ids.get((f.home, f.away))
        if gid is None:
            continue  # validate_store reports it as missing
        if f.due_at <= min(team_fetched[f.home], team_fetched[f.away]):
            from_teams.add(gid)
        else:
            later.append(gid)
    extra = COST_SHOT_MAP * sum(cache.get(gid) is None for gid in later)
    if client.credits_spent + extra > max_credits or (
            client.credits_remaining is not None and extra > client.credits_remaining):
        raise SyncRefused(
            f"{len(later)} matches became due after the team files were fetched and need {extra} more credits; "
            f"raise --max-credits on purpose"
        )
    frames = [normalize_shots([s for s in team_shots[n] if str(s.get("game_id")) in from_teams], sched, season)
              for n in names]
    frames += [normalize_shots(_shots_for_game(client, cache, gid), sched, season) for gid in later]
    df = pd.concat([f for f in frames if len(f)] or frames[:1], ignore_index=True)
    problems = validate_store(df, fixtures, now)
    overlap = compare_with_backup(df, backup)
    if overlap["status"] != "ok":
        problems.append(f"backup canary {overlap['status']}: {overlap}")
    flank_players = pick_flank_players(backup)
    flank = flank_canary(df, flank_players)
    if flank["status"] == "mismatch":
        problems.append(f"flank canary mismatch: {flank}")
    if problems:
        raise ValidationFailed(problems)
    canaries = {"backup_overlap": overlap, "known_flank": flank}
    write_working_store(df, _build_pointer(df, season, canaries, fixtures, now, flank_players), season)
    return SyncReport(action="synced", due=len(due_pairs), fetched=len(unpaid_teams) + len(later),
                      credits_estimated=cost + extra, credits_spent=client.credits_spent,
                      credits_remaining=client.credits_remaining, canaries=canaries)
