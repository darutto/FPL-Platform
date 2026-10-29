# European calendar layer (`manual_curated`)

Status: converter, endpoint layer, rest hours and rotation notice built; **production delivery is a proposal, nothing irreversible built.**

## What it is

A hand-compiled list of European matches of Premier League clubs (UCL / UEL / UECL), kept by Leo OUTSIDE git in
`data/calendar-manual/` (git-excluded). It is a compilation of public facts; **its origin is still to be registered
(Leo will name the source)** and it must never be committed or published to GitHub.

Text list -> `manual_calendar.parse_manual_europe` -> `data/calendar-manual/europe_manual.json`
(`packages/football-intelligence/scripts/convert_manual_calendar.py IN.txt OUT.json --list-date YYYY-MM-DD [--unverified CLUB:YYYY-MM-DD]`).

Line format: `- DD/MM/YYYY vs Rival (Local|Visitante) - HH:MM EST / HH:MM <zone>`. EST (UTC-5) and the local time (GMT/WET 0, CET +1, EET +2, TRT +3) are both converted to UTC and must give the same instant; a mismatch is printed as a warning and the match is kept as unverified.

## Contract (decided)

* Provenance `manual_curated`, own and explicit. It is not `licensed_starter` and not `live_trial_local`
  (production keeps refusing the latter).
* Coverage is always **partial** and the layer is **frozen**: not refreshed; `data.manual.list_date` is the visible date stamp.
* **Time known -> `kickoff_utc`**, real rest days (whole days and `rest_hours_before`) for the match and for the next
  Premier League match. **No time, EST/local mismatch, or a match listed `--unverified`** (today: Brighton-Universitatea
  Craiova 26/11, 17:45 UTC in the file vs 20:00 UK in an aggregator) -> `kickoff_known: false`: shown with "hora por
  verificar", never feeding a rest-day number or a notice. Missing data is never "no match".
* **Rotation notice** (<= 3 whole days after a verified European match) is issued even though the calendar is partial:
  a known match is a fact, and a hole can only hide a *closer* one, never undo it (`europe_prior`). Cups alone still
  never warn on a partial calendar (unchanged). Payload: `pl_matches[].rest_hours_before` next to the existing fields.
* `/fixtures/competitions` (premium detail, free = constant) adds the matches to each team's `matches` and
  `data.provenance` becomes `licensed_starter+manual_curated`, with `data.manual` = `{provenance, list_date, coverage, frozen, competitions}`.
  The layer rides on the licensed calendar only; if that is unavailable the endpoint stays `available: false`.
* Reads `FPL_MANUAL_CALENDAR_PATH` (default `data/calendar-manual/europe_manual.json`); an absent or invalid file = no layer.
* Not in the file: matches already played (needs date + score per row) and rounds after January.

## Proposal: how it reaches production (NOT built)

The data are public UEFA fixtures, but the file is a **compilation** (EU database-right territory) and its origin is
still unregistered; the GitHub repo is public and history is irreversible.

| Option | For | Against |
|---|---|---|
| Versioned in the repo | zero infra, reviewable, deploys with code | public + permanent: cannot be un-published; contradicts "never commit" |
| Private R2 prefix `football-manual/` | private, refresh without deploy, reuses the licensed-store pattern | needs a temporary write token (Leo creates, deletes) + a read/sync step on Railway with read access to the new prefix |
| Railway secret/env holding the JSON (~8 KB) | no key, private, instant rollback, no code in git | manual re-paste per refresh; size limit irrelevant here |

**Recommendation: R2 private prefix if the list will be refreshed (knockouts, times); for the single frozen list
shipped now, the Railway env var, mounted to a file at start (`FPL_MANUAL_CALENDAR_PATH`).** Not the repo.
Risks: R2 - token left alive (delete it right after; counts-only logs); env - a typo breaks parsing, which degrades to
"no layer" (the validator ignores an invalid file), never to a wrong calendar. Either route needs ~15 lines of startup
code (write env to file / sync prefix) that are NOT in this PR.
