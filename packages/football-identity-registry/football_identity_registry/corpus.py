"""Generate and validate sanitized real-name identity corpora."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from .canonical_ids import canonical_player_id, identity_fingerprint
from .matcher import match_player
from .models import CandidatePlayer, SourcePlayer
from .normalization import normalize_name


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _full_name(row: Any) -> str:
    return " ".join(filter(None, (_text(row.first_name), _text(row.second_name))))


def extract_owned_names(tactical: Path, current_players: Path, current_teams: Path, historical_players: Path) -> dict[str, Any]:
    shots = pd.read_parquet(tactical)
    players = pd.read_parquet(current_players)
    teams = pd.read_parquet(current_teams)
    historical = pd.read_parquet(historical_players)
    team_names = {int(row.team_id): str(row.name) for row in teams.itertuples()}

    current_candidates = [{
        "full_name": _full_name(row),
        "team_provider_id": team_names.get(int(row.team_id)),
        "birth_date": _text(getattr(row, "birth_date", None)),
        "known_name": _text(getattr(row, "known_name", None)) or _text(row.web_name),
    } for row in players.itertuples() if _full_name(row)]
    understat_sources = [{
        "provider": "understat", "provider_id": f"understat-{index:04d}",
        "full_name": str(player), "team_provider_id": str(team),
    } for index, (player, team) in enumerate(sorted(set(zip(shots["player"].dropna(), shots["shooting_team"].dropna()))), 1)]

    historical_candidates = [{
        "full_name": _full_name(row), "team_provider_id": str(row.team_id),
        "birth_date": None, "known_name": _text(row.web_name),
    } for row in historical.itertuples() if _full_name(row)]
    historical_sources = [{
        "provider": "vaastav", "provider_id": f"vaastav-{index:04d}",
        "full_name": str(row.web_name), "team_provider_id": str(row.team_id),
    } for index, row in enumerate(historical.itertuples(), 1) if _text(row.web_name)]
    return {
        "schema_version": 1,
        "provenance": {
            "understat": {"season": "2025-2026", "source": "owned tactical understat_shots.parquet", "sha256": _sha256(tactical)},
            "candidate_registry": {"season": "2025-2026", "source": "owned historical players.parquet", "sha256": _sha256(current_players)},
            "vaastav": {"season": "2024-2025", "source": "owned vaastav-imported historical players.parquet", "sha256": _sha256(historical_players)},
            "sanitization": "names, team context, birth date, and generated corpus-local source ids only; no match data",
        },
        "corpora": {
            "understat": {"candidates": current_candidates, "sources": understat_sources},
            "vaastav": {"candidates": historical_candidates, "sources": historical_sources},
        },
    }


def _candidate_set(rows: list[dict[str, Any]]) -> tuple[list[CandidatePlayer], set[str]]:
    signatures: dict[str, set[tuple[str, str, str]]] = {}
    for row in rows:
        fp = identity_fingerprint(row["full_name"], row.get("birth_date"))
        signatures.setdefault(fp, set()).add((str(row.get("team_provider_id") or ""), normalize_name(str(row.get("known_name") or "")), str(row.get("birth_date") or "")))
    conflicts = {fp for fp, values in signatures.items() if len(values) > 1}
    candidates = {CandidatePlayer(
        canonical_player_id(row["full_name"], row.get("birth_date")), row["full_name"],
        row.get("team_provider_id"), row.get("birth_date"), row.get("known_name"),
    ) for row in rows if identity_fingerprint(row["full_name"], row.get("birth_date")) not in conflicts}
    return sorted(candidates, key=lambda item: item.canonical_player_id), conflicts


def validate_extract(extract: dict[str, Any]) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    queue: list[dict[str, Any]] = []
    for name, corpus in extract["corpora"].items():
        candidates, conflicts = _candidate_set(corpus["candidates"])
        tiers: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        matched = ambiguous = 0
        for item in corpus["sources"]:
            source = SourcePlayer(**item)
            source_fp = identity_fingerprint(source.full_name, source.birth_date)
            if source_fp in conflicts:
                reasons["identity_indistinguishable"] += 1
                ambiguous += 1
                queue.append({"corpus": name, "source": item, "reason": "identity_indistinguishable"})
                continue
            result = match_player(source, candidates)
            if result.matched:
                matched += 1
                tiers[result.match_method or "unknown"] += 1
            else:
                reasons[result.reason or "unknown"] += 1
                ambiguous += result.reason == "ambiguous"
                queue.append({"corpus": name, "source": item, "reason": result.reason or "unknown"})
        total = len(corpus["sources"])
        reports[name] = {
            "total_source_identities": total, "matched": matched,
            "unmatched": total - matched - ambiguous, "ambiguous": ambiguous,
            "manual_override": tiers.get("manual_override", 0),
            "automatic_match_rate": round(matched / total, 6) if total else 0,
            "tier_distribution": dict(sorted(tiers.items())),
            "unresolved_reasons": dict(sorted(reasons.items())),
            "meets_95_percent_target": matched / total >= .95 if total else False,
        }
    return {
        "schema_version": 1, "provenance": extract["provenance"],
        "generation_command": "python -m football_identity_registry.corpus generate --repo-root .",
        "denominator_rule": "all distinct non-empty source name plus team identities in each owned source; no exclusions",
        "results": reports, "ambiguity_queue": queue,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["generate", "verify"])
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--extract", type=Path, default=Path(__file__).parents[1] / "corpus" / "owned_names.json")
    parser.add_argument("--report", type=Path, default=Path(__file__).parents[1] / "corpus" / "report.json")
    args = parser.parse_args(argv)
    if args.command == "generate":
        root = args.repo_root
        extract = extract_owned_names(
            root / "packages/fpl-tactical/data/tactical/seasons/2025-2026/understat_shots.parquet",
            root / "packages/fpl-historical/data/historical/seasons/2025-2026/parquet_merged/players.parquet",
            root / "packages/fpl-historical/data/historical/seasons/2025-2026/parquet_merged/teams.parquet",
            root / "packages/fpl-historical/data/historical/seasons/2024-2025/parquet_merged/players.parquet",
        )
        args.extract.parent.mkdir(parents=True, exist_ok=True)
        args.extract.write_text(json.dumps(extract, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        extract = json.loads(args.extract.read_text(encoding="utf-8"))
    report = validate_extract(extract)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report["results"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
