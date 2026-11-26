"""Writes ``world.json``: a small made-up league for the query engine's tests. Every number is invented.

    python make_world.py            (deterministic: the same file every time)

Six clubs, eight gameweeks, eight players a club (ids = club id * 100 + slot). Built-in traps:

* GW3: clubs 5 and 6 blank; their match is played in GW6, so both have a double there. Slot 5 and the bench
  of those clubs play only one of the two.
* Player 207 ("Mover") played GW1-2 for club 1 and joined club 2 before GW3.
* Player 106 ("Subject", club 1) plays 90' in GW1-3 and GW8, 0' in GW4-6 and 13' in GW7.
* In the GW2 match of club 1 the shooters' xG is far from the opponents' ``expected_goals_conceded``.
"""
from __future__ import annotations

import datetime as dt
import json
import random
from pathlib import Path

ADDITIVE = ["total_points", "minutes", "starts", "goals_scored", "assists", "clean_sheets", "goals_conceded",
            "own_goals", "penalties_saved", "penalties_missed", "yellow_cards", "red_cards", "saves", "bonus", "bps",
            "influence", "creativity", "threat", "ict_index", "expected_goals", "expected_assists",
            "expected_goal_involvements", "expected_goals_conceded", "defensive_contribution",
            "clearances_blocks_interceptions", "recoveries", "tackles"]
DECIMALS = {"influence", "creativity", "threat", "ict_index", "expected_goals", "expected_assists",
            "expected_goal_involvements", "expected_goals_conceded"}
CLUBS = [(1, "Alder Town", "ALD"), (2, "Birch City", "BIR"), (3, "Cedar Rovers", "CED"), (4, "Dune United", "DUN"),
         (5, "Elm Athletic", "ELM"), (6, "Fir Wanderers", "FIR")]
NAMES = ["Keeper", "Back", "Stopper", "Wing", "Mid", "Subject", "Striker", "Bench"]
TYPES = [1, 2, 2, 3, 3, 3, 4, 4]
ROUNDS = [[(1, 2), (3, 4), (5, 6)], [(3, 1), (2, 5), (6, 4)], [(1, 4), (2, 3)], [(5, 1), (4, 2), (6, 3)],
          [(1, 6), (2, 4), (3, 5)], [(2, 1), (4, 3), (6, 5), (5, 6)], [(1, 3), (5, 2), (4, 6)],
          [(4, 1), (6, 2), (5, 3)]]
GW1 = dt.date(2026, 8, 15)
MOVER, SUBJECT = 207, 106


def day(gameweek: int, slot: int) -> str:
    return (GW1 + dt.timedelta(days=7 * (gameweek - 1) + slot)).isoformat()


def squad(club: int, gameweek: int) -> list[int]:
    ids = [club * 100 + i for i in range(1, 9)]
    if gameweek <= 2:                                    # the mover is still at club 1
        if club == 1:
            ids.append(MOVER)
        if club == 2:
            ids.remove(MOVER)
    return ids


def minutes_for(rng: random.Random, player: int, gameweek: int, second_match: bool) -> int:
    slot = player % 100
    if player == SUBJECT:
        return {4: 0, 5: 0, 6: 0, 7: 13}.get(gameweek, 90)
    if player == MOVER:
        return 90
    if slot == 8:
        return 0 if second_match else rng.choice([0, 20, 25])
    if second_match and slot == 5:
        return 0
    if slot == 7:
        return rng.choice([90, 70, 65])
    return 90


def main() -> None:
    rng = random.Random(20261126)
    rows: dict[int, dict[int, dict]] = {gw: {} for gw in range(1, 9)}
    minutes: dict[int, dict[int, dict]] = {gw: {} for gw in range(1, 9)}
    fixtures: dict[int, list] = {}
    fixture_id = 0
    for gameweek, pairs in enumerate(ROUNDS, start=1):
        fixtures[gameweek] = []
        played_before: set[int] = set()
        for slot, (home, away) in enumerate(pairs):
            fixture_id += 1
            second = gameweek == 6 and {home, away} == {5, 6} and slot == 3
            goals = {home: rng.randint(0, 3), away: rng.randint(0, 2)}
            xg = {home: rng.randint(60, 240) / 100, away: rng.randint(40, 200) / 100}
            lineup = {club: {p: minutes_for(rng, p, gameweek, second or (club in played_before))
                             for p in squad(club, gameweek)} for club in (home, away)}
            for club, other in ((home, away), (away, home)):
                on = [p for p, m in lineup[club].items() if m > 0]
                outfield = [p for p in on if p % 100 != 1]
                # split the club's xG over its outfield players in cents, so the shooters add up exactly
                cents = round(xg[club] * 100)
                weights = [rng.randint(1, 9) for _ in outfield]
                shares = [cents * w // sum(weights) for w in weights]
                shares[-1] += cents - sum(shares)
                share = {p: s / 100 for p, s in zip(outfield, shares)}
                if gameweek == 2 and club == 1:
                    share[outfield[0]] = round(share[outfield[0]] + 0.45, 2)
                scorers = [rng.choice(outfield) for _ in range(goals[club])]
                assisters = [rng.choice(outfield) for _ in range(max(goals[club] - 1, 0))]
                for p in on:
                    m = lineup[club][p]
                    stats = {k: 0 for k in ADDITIVE}
                    stats.update(
                        minutes=m, starts=int(m >= 60), goals_scored=scorers.count(p), assists=assisters.count(p),
                        goals_conceded=goals[other] if m >= 60 else 0,
                        clean_sheets=int(m >= 60 and goals[other] == 0), expected_goals=share.get(p, 0.0),
                        expected_assists=rng.randint(0, 40) / 100,
                        expected_goals_conceded=round(xg[other] * m / 90, 2),
                        yellow_cards=int(rng.random() < 0.12), saves=rng.randint(1, 6) if p % 100 == 1 else 0,
                        bonus=rng.choice([0, 0, 0, 1, 2, 3]), bps=rng.randint(2, 40),
                        influence=rng.randint(0, 600) / 10, creativity=rng.randint(0, 600) / 10,
                        threat=rng.randint(0, 600) / 10, defensive_contribution=rng.randint(0, 14),
                        clearances_blocks_interceptions=rng.randint(0, 9), recoveries=rng.randint(0, 9),
                        tackles=rng.randint(0, 5))
                    stats["expected_goal_involvements"] = round(stats["expected_goals"] + stats["expected_assists"], 2)
                    stats["ict_index"] = round((stats["influence"] + stats["creativity"] + stats["threat"]) / 10, 1)
                    stats["total_points"] = (2 if m >= 60 else 1) + 4 * stats["goals_scored"] + \
                        3 * stats["assists"] + stats["bonus"] - stats["yellow_cards"]
                    total = rows[gameweek].setdefault(p, {k: 0 for k in ADDITIVE})
                    for k in ADDITIVE:
                        total[k] = round(total[k] + stats[k], 2) if k in DECIMALS else total[k] + stats[k]
                    minutes[gameweek].setdefault(p, {})[fixture_id] = m
            fixtures[gameweek].append({
                "id": fixture_id, "event": gameweek, "team_h": home, "team_a": away,
                "team_h_score": goals[home], "team_a_score": goals[away], "finished": True,
                "team_h_difficulty": rng.randint(2, 4), "team_a_difficulty": rng.randint(2, 5),
                "kickoff_time": f"{day(gameweek, slot % 3)}T14:00:00Z"})
            played_before |= {home, away}

    elements = []
    for club, _, short in CLUBS:
        for i in range(1, 9):
            p = club * 100 + i
            mine = [rows[gw][p] for gw in rows if p in rows[gw]]
            element = {
                "id": p, "team": club, "element_type": TYPES[i - 1],
                "web_name": "Mover" if p == MOVER else f"{NAMES[i - 1]}{short.title()}",
                "first_name": f"Nia{p}",
                "second_name": "Mover" if p == MOVER else f"{NAMES[i - 1]}{short.title()}",
                "now_cost": rng.randint(40, 130), "selected_by_percent": str(rng.randint(1, 400) / 10),
                "form": str(rng.randint(0, 90) / 10), "points_per_game": str(rng.randint(10, 90) / 10),
                "transfers_in_event": rng.randint(0, 90000), "transfers_out_event": rng.randint(0, 90000),
                "penalties_order": {7: 1, 6: 2}.get(i), "direct_freekicks_order": {5: 1}.get(i),
                "corners_and_indirect_freekicks_order": {4: 1, 5: 2}.get(i),
                "team_join_date": "2026-08-27" if p == MOVER else "2025-07-01"}
            for k in ADDITIVE:
                value = round(sum(r[k] for r in mine), 2)
                element[k] = f"{value:.2f}" if k in DECIMALS else int(value)
            elements.append(element)

    bootstrap = {
        "teams": [{"id": i, "name": name, "short_name": short} for i, name, short in CLUBS],
        "events": [{"id": gw, "finished": True, "data_checked": True,
                    "deadline_time": f"{day(gw, -1)}T17:30:00Z"} for gw in range(1, 9)],
        "elements": elements}
    gameweeks = {str(gw): {"status": "final", "revision": f"1:synthetic{gw}", "fixtures": fixtures[gw],
                           "rows": {str(p): r for p, r in sorted(rows[gw].items())},
                           "fixture_minutes": {str(p): {str(f): m for f, m in per.items() if m > 0}
                                               for p, per in sorted(minutes[gw].items())}}
                 for gw in range(1, 9)}
    out = Path(__file__).with_name("world.json")
    out.write_text(json.dumps({"bootstrap": bootstrap, "gameweeks": gameweeks}, separators=(",", ":")) + "\n",
                   encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
