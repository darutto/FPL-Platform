"""T1a acceptance: print >=10 real 2025/26 EPL shots with coordinates via soccerdata."""
import soccerdata as sd

shots = sd.Understat(leagues="ENG-Premier League", seasons="2025-2026").read_shot_events()
df = shots.reset_index()
cols = ["team", "player", "location_x", "location_y", "xg", "situation", "result"]
print(df[cols].head(12).to_string())
print(f"\ntotal shots: {len(df)}  games: {df['game_id'].nunique()}  teams: {df['team'].nunique()}")
