# fpl-tactical

Owned tactical (zonal shot-event) data store: Understat shot events →
normalized parquet → R2, feeding the zonal-weakness engine in
`fpl-grounded-assistant` (`zonal_weakness.py` + the `get_zonal_weakness` /
`get_zonal_opportunity` orchestrator tools).

## Quick start

```bash
pip install -r requirements.txt          # soccerdata + pandas + pyarrow
python -m fpl_tactical.cli ingest --season 2025-2026   # full-league pull (~380 matches)
python -m fpl_tactical.cli verify --season 2025-2026   # row counts + provenance
python scripts/smoke_zonal.py                          # end-to-end: store → engine verdicts
```

Store layout (override root with `FPL_TACTICAL_ROOT`):

```
data/tactical/seasons/<season>/understat_shots.parquet
data/tactical/seasons/<season>/_tactical_latest.json    # provenance pointer
```

## R2 publish + weekly refresh

`.github/workflows/tactical-store-refresh.yml` runs Mondays 06:30 UTC
(offset from the FPL owned-store refresh) and on `workflow_dispatch`:
ingest → verify → `python -m fpl_tactical.publish publish`. R2 credentials
reuse the `OWNED_STORE_R2_*` secrets; objects land under a distinct
`tactical/<season>/` key segment. The serving side downloads with
`python -m fpl_tactical.publish sync` (fail-soft) — **soccerdata is a
weekly-workflow dependency only and must never ship to the server**.

## The signal is relative, never absolute

Central in-box zones dominate raw xGA for every team (league avg in-box
xGA/game 2025/26: left 0.079 · central 1.159 · right 0.081), so the engine
only reports **deviation from the league baseline per zone**. Penalties are
excluded from zonal aggregation (re-labelled at ingest behind a signature
guard — see DECISIONS.md) and reported separately as context.

## Finish-zone vs buildup-flank caveat

Understat coordinates give the **zone of finish** — where conceded chances
are struck from — with lateral labels in the *attacker's* frame (a defence
leaking in the attacker's-left band is weak down *its own right*). This is
not buildup-flank attribution ("plays the right channel"); that needs
event/heatmap data — Tier-2 FotMob/Sofascore, tracked as Phase T3 in
`TACTICAL_ASSISTANT_ROADMAP.md`.

## Language discipline

All engine verdicts are Spanish and weakness/opportunity-framed only —
never buy/sell/captain advice. Advice framing stays owned by the
deterministic engines.

See `CONTRACT.md` for the schema and invariants, `DECISIONS.md` for the
T1a data-source decision and its caveats.
