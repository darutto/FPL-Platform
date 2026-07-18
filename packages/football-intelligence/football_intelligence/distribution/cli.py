"""Explicit FI-4b operator commands; client construction is deferred."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .runtime import RuntimeBuildHandle, startup_status
from .config import RemoteStoreConfig
from .service import publish_build, sync_build, verify_remote
from .store import S3ArtifactStore


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m football_intelligence.distribution")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    verify = sub.add_parser("verify-local"); verify.add_argument("--cache-root", type=Path, required=True)
    publish = sub.add_parser("publish"); publish.add_argument("--build", type=Path, required=True); publish.add_argument("--dry-run", action="store_true")
    sub.add_parser("verify-remote"); sub.add_parser("sync")
    args = parser.parse_args(argv)
    if args.command == "status": print(json.dumps(startup_status().__dict__, sort_keys=True)); return 0
    if args.command == "verify-local": print(json.dumps(RuntimeBuildHandle(args.cache_root).manifest(), sort_keys=True)); return 0
    try:
        config = RemoteStoreConfig.from_env()
        if config is None: raise RuntimeError("football remote distribution is not configured")
        store = S3ArtifactStore(config)
        if args.command == "publish": report = publish_build(store, config.prefix, args.build, dry_run=args.dry_run)
        elif args.command == "sync": report = sync_build(store, config.prefix, Path("data/football-runtime"), config.limits)
        else: report = verify_remote(store, config.prefix, config.limits)
        print(json.dumps(report.__dict__, sort_keys=True)); return 0
    except Exception as exc:
        print(f"FI-4b command failed: {type(exc).__name__}: {exc}"); return 1


if __name__ == "__main__": raise SystemExit(main())
