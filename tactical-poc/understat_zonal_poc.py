"""
PoC: derive a team's DEFENSIVE zonal weakness from Understat shot data (2025/26).
Pure stdlib. Uses Understat's CURRENT (2026) AJAX endpoints:
  getLeagueData/{league}/{season}  -> dates, teams, players
  getMatchData/{match_id}          -> shots.h / shots.a
Responses are gzip'd JSON.

For each of TEAM's completed matches we take the OPPONENT's shots (= shots the
team CONCEDED) and bucket them by pitch zone to expose zonal weakness.
"""
import gzip, json, sys, time, urllib.request

SEASON = "2025"                       # Understat "2025" == 2025/26
TEAM = sys.argv[1] if len(sys.argv) > 1 else "West Ham"
H = {"User-Agent": "Mozilla/5.0 (research PoC)",
     "X-Requested-With": "XMLHttpRequest",
     "Referer": "https://understat.com/"}

def getj(url):
    r = urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=30)
    raw = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))

def zone(x, y):
    if x >= 0.84:      depth = "in-box"
    elif x >= 0.70:    depth = "edge-of-box"
    else:              return None            # ignore long-range
    if y < 0.36:       lat = "left"
    elif y > 0.64:     lat = "right"
    else:              lat = "central"
    return f"{depth:11} / {lat}"

print(f"Fetching EPL {SEASON} league data...")
league = getj(f"https://understat.com/getLeagueData/EPL/{SEASON}")
dates = league["dates"]

matches = []
for m in dates:
    if not m.get("isResult"):
        continue
    h, a = m["h"]["title"], m["a"]["title"]
    if TEAM in (h, a):
        opp_side = "h" if a == TEAM else "a"   # opponent's shots = what we conceded
        matches.append((m["id"], opp_side, h if opp_side == "h" else a))

if not matches:
    teams = sorted({m["h"]["title"] for m in dates} | {m["a"]["title"] for m in dates})
    sys.exit("Team not found. Available:\n  " + "\n  ".join(teams))

print(f"{TEAM}: {len(matches)} completed matches\n")
zones, totS, totXg, totG, penXg = {}, 0, 0.0, 0, 0.0
for i, (mid, opp_side, opp) in enumerate(matches, 1):
    md = getj(f"https://understat.com/getMatchData/{mid}")
    for s in md["shots"][opp_side]:
        xg, x, y = float(s["xG"]), float(s["X"]), float(s["Y"])
        g = 1 if s["result"] == "Goal" else 0
        totS += 1; totXg += xg; totG += g
        if s["situation"] == "Penalty":
            penXg += xg; continue
        z = zone(x, y)
        if z is None:
            continue
        row = zones.setdefault(z, [0, 0.0, 0])
        row[0] += 1; row[1] += xg; row[2] += g
    time.sleep(0.2)
    if i % 10 == 0:
        print(f"  ...{i}/{len(matches)}")

print(f"\n=== {TEAM} — shots CONCEDED, EPL {SEASON} ===")
print(f"conceded shots {totS} | xGA {totXg:.1f} | goals {totG} | penalties xG {penXg:.1f}")
print("(open-play + non-penalty set-pieces, in/around box only)\n")
print(f"{'zone':26}{'shots':>7}{'xGA':>8}{'goals':>7}{'xGA/shot':>10}")
print("-" * 58)
for z, (n, xg, g) in sorted(zones.items(), key=lambda kv: -kv[1][1]):
    print(f"{z:26}{n:>7}{xg:>8.2f}{g:>7}{xg/n:>10.3f}")
