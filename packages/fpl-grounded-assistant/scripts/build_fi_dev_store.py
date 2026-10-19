"""Assemble the runtime-shaped dev store the chat FI tools read (DEV ONLY, ``live_trial_local``).

The FI-9 trial writes its stores split by builder (``v1/premier-league``, ``context``, ``features``) with no
identity crosswalk. ``football_intelligence_runtime._load_runtime`` wants ONE root:

    <root>/_football_latest.json + builds/            (base v1 build, remote-schema pointer)
    <root>/_football_v2_latest.json + builds-v2/      (context build)
    <root>/features/_features_v2_latest.json + builds-v2/
    <root>/identity/                                  (FPL id -> canonical id, players + teams)

This copies the already-built stores (no rebuild, no Sportmonks call) and writes ``identity`` from the same
capture the trial built them from (the capture's unanimous identity pairs + club crosswalk).
Fixture/competition identity tables are written empty: only ``get_fixture_context`` by explicit fixture id needs them.
Outputs belong in the git-ignored trial-output folder, never under data/football.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


def _norm(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c)).strip()


def build(run_dir: Path, out: Path) -> dict[str, int]:
    import pandas as pd  # noqa: PLC0415
    from football_identity_registry.store import IdentityStore, PlayerIdentityRow, _atomic_parquet, OTHER_COLUMNS  # noqa: PLC0415
    from football_intelligence.ingestion import live_trial as lt  # noqa: PLC0415

    store = run_dir / "store"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    v1 = store / "v1" / "premier-league"
    shutil.copytree(v1 / "builds", out / "builds")
    # The runtime's base handle reads the *remote-schema* pointer; the local builder's pointer has other fields.
    from football_intelligence.distribution.service import encode_pointer  # noqa: PLC0415
    local = json.loads((v1 / "_football_latest.json").read_text(encoding="utf-8"))
    manifest_bytes = (out / "builds" / local["build_id"] / "manifest.json").read_bytes()
    (out / "_football_latest.json").write_bytes(encode_pointer(local["build_id"], hashlib.sha256(manifest_bytes).hexdigest()))
    shutil.copy2(store / "context" / "_football_v2_latest.json", out / "_football_v2_latest.json")
    shutil.copytree(store / "context" / "builds-v2", out / "builds-v2")
    (out / "features").mkdir()
    shutil.copy2(store / "features" / "_features_v2_latest.json", out / "features" / "_features_v2_latest.json")
    shutil.copytree(store / "features" / "builds-v2", out / "features" / "builds-v2")

    capture = json.loads((run_dir / "capture.json").read_text(encoding="utf-8"))
    build_dir = out / "builds" / json.loads((out / "_football_latest.json").read_text())["build_id"]
    players = pd.read_parquet(build_dir / "canonical" / "players.parquet")
    canonical_of = {str(r.source_provider_id): r.player_id for r in players.itertuples(index=False)}
    elements = {int(e["id"]): e for e in capture["fpl"]["elements"]}
    rows = []
    for pair in capture["identity_pairs"]:
        element, canonical = elements.get(int(pair["fpl_id"])), canonical_of.get(str(pair["sportmonks_id"]))
        if element is None or canonical is None:
            continue
        full = f"{element['first_name']} {element['second_name']}".strip()
        rows.append(PlayerIdentityRow(
            canonical_player_id=canonical, provider="fpl", provider_id=str(element["id"]), normalized_name=_norm(full),
            full_name=full, team_provider_id=str(element["team"]), birth_date=(element.get("birth_date") or "")[:10] or None,
            valid_from=lt.SEED_VALID_FROM, valid_to=None, match_method=str(pair.get("method", "capture_pair")),
            match_confidence=1.0, manual_override=False))
    registry, _index = lt.build_team_registry(capture)
    names = {s.canonical_team_id: s.display_name for s in registry.teams}
    team_rows = [{"canonical_team_id": c.canonical_team_id, "provider": "fpl", "provider_id": c.provider_id,
                  "name": names[c.canonical_team_id], "valid_from": c.valid_from, "valid_to": c.valid_to}
                 for c in registry.crosswalks if c.provider == "fpl"]
    identity = out / "identity"
    _atomic_parquet(identity / "team_identity.parquet", team_rows, OTHER_COLUMNS["team"])
    IdentityStore(identity).write(rows, run_id="fi-dev-store", queue=[],
                                  generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    errors = IdentityStore(identity).verify()
    if errors:
        raise SystemExit("identity store invalid: " + "; ".join(errors))
    return {"players": len(rows), "teams": len(team_rows)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", type=Path, required=True, help="trial-output/runs/<tag> (has store/ and capture.json)")
    ap.add_argument("--out", type=Path, required=True, help="dev store root (git-ignored trial-output, never data/football)")
    args = ap.parse_args(argv)
    if "data" in args.out.parts and "football" in args.out.parts:
        print("refusing to write under data/football", file=sys.stderr)
        return 2
    print(json.dumps(build(args.run_dir, args.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
