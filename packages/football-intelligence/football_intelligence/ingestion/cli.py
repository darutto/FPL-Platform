"""Offline-only FI-4a canonical build CLI."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .builder import build_from_fixture, replay_manifest, validate_active


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m football_intelligence.ingestion.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    rebuild = sub.add_parser("rebuild"); rebuild.add_argument("--source", type=Path, required=True); rebuild.add_argument("--destination", type=Path, required=True); rebuild.add_argument("--build-id", required=True); rebuild.add_argument("--built-at")
    validate = sub.add_parser("validate"); validate.add_argument("--destination", type=Path, required=True)
    replay = sub.add_parser("replay"); replay.add_argument("--manifest", type=Path, required=True); replay.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "rebuild": report = build_from_fixture(args.source, args.destination, build_id=args.build_id, built_at=args.built_at)
        elif args.command == "validate": report = validate_active(args.destination)
        else: report = replay_manifest(args.manifest, args.destination)
    except Exception as exc:
        print(f"FI-4a offline build failed: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps({"build_id": report["build_id"], "row_counts": report["row_counts"], "quarantine_counts": report["quarantine_counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
