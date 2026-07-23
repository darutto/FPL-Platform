# Player of the Gameweek — hero page handoff

Feature: a per-gameweek hero page that highlights the standout FPL performer,
in the style of ESPN's Body Issue cover-athlete pages (big name, short
editorial "why", minimal meta line, numbered pager). Prototype:
https://claude.ai/code/artifact/15fb1b4c-1df6-45dc-ae1a-17660d63520c

That artifact is a throwaway static prototype (vanilla HTML/CSS/JS, all data
inlined) meant to prove the concept and hand off a visual direction — it is
not production code to lift as-is. This doc + the data file are the actual
handoff.

## 1. The data

`potg-data-4-seasons.json` (same folder) has one entry per finished gameweek
for four seasons: `2022-2023`, `2023-2024`, `2024-2025`, `2025-2026`. Shape:

```json
{
  "2025-2026": [
    {
      "event_id": 1,
      "player_id": 531,
      "web_name": "Ballard",
      "team_short": "SUN",
      "position": "DEF",
      "points": 17,
      "highlight": "1 goal, clean sheet, 14 defensive contributions, 3 bonus points"
    }
  ]
}
```

Field notes:

- `event_id` — gameweek number, 1–38 (2022-2023 has 37; GW7 is missing from
  the owned store for that season).
- `player_id` — FPL element id for that season. Not stable across seasons.
- `web_name` — display name as FPL shows it (may need accent-encoding
  cleanup for a few older-season names, see caveats below).
- `team_short` — 3-letter club code. **Known caveat, accepted for now**: this
  reflects the player's team on the season's most recent roster snapshot, not
  necessarily their club on that specific gameweek. A player transferred
  mid-season will show their later club for earlier gameweeks too.
- `position` — one of `GKP`, `DEF`, `MID`, `FWD`.
- `points` — total FPL points that gameweek.
- `highlight` — a short generated "why" string (goals, assists, clean sheet,
  saves, defensive contributions, bonus points), in that priority order.
  Empty string if no box-score detail was available — treat as "no detail,
  just show the points."

### Refreshing this data

The JSON file is a point-in-time export. The backend tool that produces it —
`get_historical_gameweek_top_scorer(season, gw=None)` in
`packages/fpl-grounded-assistant/fpl_grounded_assistant/historical_gameweek_top_scorer.py`
— can be re-run any time to regenerate it (e.g. once the current season
progresses, or a season is re-synced). There is currently **no dedicated
structured HTTP endpoint** for this tool — only the conversational `POST /ask`
endpoint, which returns rendered prose, not JSON. If the real page needs to
fetch this live rather than from a static export, the smallest addition is a
thin route that calls the Python function directly and returns its dict
(mirroring how `/resources` already exposes other read-only data) — flag this
to whoever owns the backend if/when live refresh is needed.

## 2. Design direction (from the prototype)

Not a locked design system — a starting point your other agent can diverge
from, but useful defaults if nothing else is specified:

**Palette** — pitch/paper/gold, not a generic AI palette:
| Token | Light | Dark | Use |
|---|---|---|---|
| `paper` | `#eef1ea` | `#0d1f16` | page background |
| `ink` | `#12241b` | `#eef1ea` | primary text |
| `ink-soft` | `#3f5245` | `#b7c4b9` | secondary text/meta |
| `pitch` | `#0d1f16` | `#0a1913` | dark hero-side panel ground |
| `accent` | `#af8a2e` | `#e3c877` | gold — headline name, active states, CTA |
| position chips | GKP amber `#b8862c` · DEF teal `#2b7a6b` · MID blue `#2f5f9e` · FWD terracotta `#b0492f` | (dark variants: `#e3c877` / `#5fc9b4` / `#7fa8e0` / `#e07a54`) | semantic, kept separate from the main accent |

**Type** — three roles, no single "safe" grotesk carrying everything:
- Display (player name, big numerals): condensed heavy sans — `"Arial
  Narrow", "Roboto Condensed"` stack, weight 800, uppercase, tight tracking.
  Evokes a stadium scoreboard / kit number rather than a generic headline font.
- Body (the "why" sentence): a serif — `Georgia, "Iowan Old Style"` — gives
  it an editorial/program voice, distinct from the display face.
- Utility (GW numbers, points, table data): monospace with tabular figures —
  `"SFMono-Regular", Consolas, "Roboto Mono"` — anywhere digits need to line
  up in columns.

**Layout** — full-viewport hero: name + meta + "why" sentence on the left
~65%, an abstract stat-plate panel on the right ~35% (not a photo — no source
imagery exists for real players; the prototype uses the player's point total
as a huge translucent numeral over a pitch-line texture instead). A footer
bar holds season tabs, a per-GW scrub rail, and prev/next arrows. Below the
fold: a plain data table of the full archive, grouped by season, click-to-load
into the hero.

**Interaction**: prev/next steps through the season's played gameweeks only
(skips missing ones, e.g. 2022-2023 GW7); switching season snaps to the first
available GW if the current GW number doesn't exist in the new season.

## 3. Open items for the real build

- Decide the real hero image treatment (stat-plate abstraction, a club crest
  treatment, or something else) — no real athlete photography is available.
- If live/current-season data is needed (not just the 4 static seasons here),
  wire up a real endpoint as noted above.
- `web_name` encoding: a handful of older-season names have mangled accented
  characters at the source (a pre-existing `fpl-historical` data-quality
  issue, e.g. "Gu​hi" instead of "Guéhi") — worth a pass if those specific
  gameweeks get featured.
