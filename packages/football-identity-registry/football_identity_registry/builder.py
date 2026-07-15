"""Offline JSON-to-crosswalk build orchestration."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .canonical_ids import assert_candidates_distinguishable, assert_no_id_collisions, canonical_player_id
from .matcher import match_player
from .models import CandidatePlayer, SourcePlayer
from .normalization import normalize_name
from .overrides import load_overrides
from .store import IdentityStore, PlayerIdentityRow, reconcile_player_rows


def build(input_path: Path, store: IdentityStore, overrides_path: Path, *, valid_from: str, run_id: str, generated_at: str, threshold: float = .8) -> dict[str, int]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if any("canonical_player_id" in item for item in payload["candidates"]):
        raise ValueError("build inputs must not supply canonical_player_id")
    assert_candidates_distinguishable(payload["candidates"])
    identities = [(item["full_name"], item.get("birth_date")) for item in payload["candidates"]]
    assert_no_id_collisions(identities)
    candidate_rows = [CandidatePlayer(
        canonical_player_id(item["full_name"], item.get("birth_date")),
        item["full_name"], item.get("team_provider_id"), item.get("birth_date"), item.get("known_name"),
    ) for item in payload["candidates"]]
    candidates = list(dict.fromkeys(candidate_rows))
    sources = [SourcePlayer(**item) for item in payload["sources"]]
    overrides = load_overrides(overrides_path)
    incoming: list[PlayerIdentityRow] = []
    queue: list[dict[str, object]] = []
    for source in sources:
        result = match_player(source, candidates, overrides, threshold=threshold)
        if not result.matched:
            queue.append({
                "source": asdict(source), "reason": result.reason,
                "candidates": [asdict(candidate) for candidate in result.candidates],
            })
            continue
        incoming.append(PlayerIdentityRow(
            result.canonical_player_id or "", source.provider, source.provider_id,
            normalize_name(source.full_name), source.full_name, source.team_provider_id,
            source.birth_date, valid_from, None, result.match_method or "", result.match_confidence or 0,
            result.match_method == "manual_override",
        ))
    rows = reconcile_player_rows(store.read_players(), incoming)
    store.write(rows, run_id=run_id, generated_at=generated_at, queue=queue)
    return {"matched": len(incoming), "unresolved": len(queue), "total": len(sources)}
