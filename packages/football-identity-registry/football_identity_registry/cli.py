"""Non-interactive FI-2 identity registry CLI."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .builder import build
from .store import IdentityStore


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    build_cmd = sub.add_parser("build")
    build_cmd.add_argument("--input", type=Path, required=True)
    build_cmd.add_argument("--root", type=Path, default=None)
    build_cmd.add_argument("--overrides", type=Path, default=Path(__file__).parents[1] / "overrides.yaml")
    build_cmd.add_argument("--valid-from", required=True)
    build_cmd.add_argument("--run-id", required=True)
    build_cmd.add_argument("--generated-at", required=True)
    build_cmd.add_argument("--threshold", type=float, default=.8)
    for name in ("verify", "queue"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--root", type=Path, default=None)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    store = IdentityStore(args.root)
    if args.command == "build":
        print(json.dumps(build(args.input, store, args.overrides, valid_from=args.valid_from, run_id=args.run_id, generated_at=args.generated_at, threshold=args.threshold), sort_keys=True))
        return 0
    if args.command == "verify":
        errors = store.verify()
        print(json.dumps({"ok": not errors, "errors": errors}, sort_keys=True))
        return 1 if errors else 0
    queue_path = store.root / "ambiguity_queue.json"
    print(queue_path.read_text(encoding="utf-8") if queue_path.exists() else json.dumps({"schema_version": 1, "items": []}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
