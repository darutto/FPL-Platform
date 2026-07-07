"""
PoC part 2: league-wide RELATIVE zonal weakness (the real Ghono signal).
One pass over all 380 matches; each match feeds BOTH teams' conceded profiles.
Then rank teams by in-box LEFT / RIGHT xGA-per-game vs the league average
= "which defense leaks most down each flank relative to everyone else".
"""
import gzip, json, sys, time, urllib.request
from collections import defaultdict

SEASON = "2025"
H = {"User-Agent": "Mozilla/5.0 (research PoC)", "X-Requested-With": "XMLHttpRequest",
     "Referer": "https://understat.com/"}

def getj(url):
    r = urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=30)
    raw = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))

def lat_zone(x, y):
    if x < 0.84:                 # in-box only for flank read
        return None
    if y < 0.36:  return "left"
    if y > 0.64:  return "right"
    return "central"

league = getj(f"https://understat.com/getLeagueData/EPL/{SEASON}")
done = [m for m in league["dates"] if m.get("isResult")]
print(f"{len(done)} completed matches; pulling shots (one pass)...")

# team -> zone -> [xga, games]
conc = defaultdict(lambda: defaultdict(float))
games = defaultdict(int)
for i, m in enumerate(done, 1):
    md = getj(f"https://understat.com/getMatchData/{m['id']}")
    for side, team_key in (("h", "a"), ("a", "h")):   # side shoots; team_key concedes
        team = m[team_key]["title"]
        games[team] += 1
        for s in md["shots"][side]:
            if s["situation"] == "Penalty":
                continue
            z = lat_zone(float(s["X"]), float(s["Y"]))
            if z:
                conc[team][z] += float(s["xG"])
    time.sleep(0.1)
    if i % 50 == 0:
        print(f"  ...{i}/{len(done)}")

teams = sorted(conc)
per_game = {t: {z: conc[t][z] / games[t] for z in ("left", "central", "right")} for t in teams}
league_avg = {z: sum(per_game[t][z] for t in teams) / len(teams) for z in ("left", "central", "right")}
print(f"\nLeague avg in-box xGA/game — left {league_avg['left']:.3f}  "
      f"central {league_avg['central']:.3f}  right {league_avg['right']:.3f}\n")

def rank(zone, label):
    print(f"=== Most vulnerable {label} (in-box xGA/game vs league avg) ===")
    rows = sorted(teams, key=lambda t: -(per_game[t][zone] - league_avg[zone]))[:6]
    for t in rows:
        d = per_game[t][zone] - league_avg[zone]
        print(f"  {t:24} {per_game[t][zone]:.3f}   ({d:+.3f} vs avg)")
    print()

rank("left", "down the LEFT (attacker's left / defence's right)")
rank("right", "down the RIGHT (attacker's right / defence's left)")
