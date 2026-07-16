"""Explicitly guarded live smoke command."""
from __future__ import annotations

import argparse

from .client import SportmonksClient
from .errors import SportmonksError


def main(argv: list[str] | None = None, *, client_factory=SportmonksClient) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    smoke = sub.add_parser("smoke", help="LIVE and potentially rate-limited")
    smoke.add_argument("--i-understand-this-is-live", action="store_true")
    args = parser.parse_args(argv)
    if not args.i_understand_this_is_live:
        print("REFUSED: live smoke requires --i-understand-this-is-live")
        return 2
    try:
        client = client_factory()
        result = client.fetch_page("leagues", params={"per_page": 1})
        print(f"LIVE Sportmonks smoke succeeded; records={len(result)}")
        return 0
    except SportmonksError as exc:
        print(f"LIVE Sportmonks smoke failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
