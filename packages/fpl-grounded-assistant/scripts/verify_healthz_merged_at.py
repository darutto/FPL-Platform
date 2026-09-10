#!/usr/bin/env python3
"""Poll /healthz until owned_store_sync.merged_at matches the expected value.

Usage:
    python verify_healthz_merged_at.py \
        --url https://fpl-backend-production-4151.up.railway.app/healthz \
        --expected-merged-at 2026-06-01T00-40-44Z \
        --expected-season 2026-2027 \
        --timeout 900 \
        --interval 30

With --expected-season given, a match additionally requires
owned_store_sync.season == expected_season, and tactical_store_sync.season
== expected_season whenever the tactical_store_sync key is present (that
key is absent entirely when the tactical sync flag is off; its absence is
not itself a failure). Without --expected-season, only merged_at is checked
-- unchanged behavior for existing callers (i73 Entrega 2: this is the
central invariant the manual "Verify /healthz" workflow step was missing --
it used to confirm a timestamp moved, never that production was serving the
correct season for either store).

Exit codes:
    0 — matched within the timeout window.
    1 — timed out before a match was observed.
    2 — malformed response: non-200 status persisting past interval*2 seconds,
        or the owned_store_sync key missing across 3 successive responses.
"""

import argparse
import json
import sys
import time

import requests


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Poll /healthz until owned_store_sync.merged_at matches expected."
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Full URL to poll (must already include /healthz path).",
    )
    parser.add_argument(
        "--expected-merged-at",
        required=True,
        help="The merged_at value to wait for (e.g. 2026-06-01T00-40-44Z).",
    )
    parser.add_argument(
        "--expected-season",
        default=None,
        help=(
            "If given, also require owned_store_sync.season (and "
            "tactical_store_sync.season, when that key is present) to equal "
            "this value before declaring a match."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=900,
        help="Maximum seconds to wait before giving up (default: 900).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Seconds between polls (default: 30).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    url = args.url
    expected = args.expected_merged_at
    expected_season = args.expected_season
    timeout = args.timeout
    interval = args.interval

    print(
        f"[verify] url={url} expected={expected} expected_season={expected_season} "
        f"timeout={timeout}s interval={interval}s",
        flush=True,
    )

    start = time.monotonic()

    # Counters for escalation to exit 2.
    # - consecutive_non200: tracks non-200 HTTP; resets on a 200.
    # - consecutive_missing_key: tracks missing owned_store_sync key; resets on presence.
    consecutive_non200: int = 0
    consecutive_missing_key: int = 0

    # How long a non-200 must persist before we escalate to exit 2.
    non200_persist_threshold: float = interval * 2

    while True:
        elapsed = time.monotonic() - start
        last_seen: str | None = None
        poll_error: str = ""

        try:
            response = requests.get(url, timeout=30)
        except requests.RequestException as exc:
            # Network exception: treat as transient (still deploying).
            poll_error = f"network error: {exc}"
            consecutive_non200 += 1
            print(f"[verify t={elapsed:.0f}s] transient — {poll_error}", flush=True)
        else:
            if response.status_code not in (200, 502, 503):
                # Unexpected status — track persistence.
                poll_error = f"HTTP {response.status_code}"
                consecutive_non200 += 1
                print(
                    f"[verify t={elapsed:.0f}s] non-200 ({response.status_code}) "
                    f"— {consecutive_non200} consecutive",
                    flush=True,
                )
                # Escalate to exit 2 if the non-200 has persisted too long.
                if elapsed >= non200_persist_threshold:
                    print(
                        f"[verify] MALFORMED/PERSISTENT — HTTP {response.status_code} "
                        f"persisting past {non200_persist_threshold:.0f}s (interval*2)",
                        file=sys.stderr,
                        flush=True,
                    )
                    sys.exit(2)
            elif response.status_code in (502, 503):
                # Railway is still deploying — treat as transient, don't escalate.
                consecutive_non200 += 1
                print(
                    f"[verify t={elapsed:.0f}s] HTTP {response.status_code} "
                    f"(still deploying), retrying…",
                    flush=True,
                )
            else:
                # HTTP 200 — reset non-200 counter.
                consecutive_non200 = 0

                try:
                    body = response.json()
                except (json.JSONDecodeError, ValueError) as exc:
                    # Malformed JSON is a structural error — exit 2 immediately.
                    print(
                        f"[verify] MALFORMED — JSON parse error: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
                    sys.exit(2)

                sync_block = body.get("owned_store_sync")
                if sync_block is None:
                    # owned_store_sync key absent or null — track successive occurrences.
                    consecutive_missing_key += 1
                    print(
                        f"[verify t={elapsed:.0f}s] owned_store_sync absent/null "
                        f"({consecutive_missing_key}/3)",
                        flush=True,
                    )
                    if consecutive_missing_key >= 3:
                        print(
                            "[verify] MALFORMED — owned_store_sync key missing "
                            "across 3 successive responses",
                            file=sys.stderr,
                            flush=True,
                        )
                        sys.exit(2)
                else:
                    # Key present — reset missing counter.
                    consecutive_missing_key = 0
                    last_seen = sync_block.get("merged_at")
                    owned_season = sync_block.get("season")

                    merged_at_matches = last_seen == expected

                    season_matches = True
                    season_detail = ""
                    if expected_season is not None:
                        if owned_season != expected_season:
                            season_matches = False
                        tactical_block = body.get("tactical_store_sync")
                        if tactical_block is not None:
                            tactical_season = tactical_block.get("season")
                            if tactical_season != expected_season:
                                season_matches = False
                            season_detail = (
                                f" owned_season={owned_season!r} "
                                f"tactical_season={tactical_season!r}"
                            )
                        else:
                            season_detail = f" owned_season={owned_season!r}"

                    if merged_at_matches and season_matches:
                        print(
                            f"[verify] matched merged_at={last_seen}"
                            f"{season_detail} after {elapsed:.0f}s",
                            flush=True,
                        )
                        sys.exit(0)
                    else:
                        print(
                            f"[verify t={elapsed:.0f}s] merged_at={last_seen!r} "
                            f"expected={expected!r}{season_detail} "
                            f"expected_season={expected_season!r}, waiting…",
                            flush=True,
                        )

        # Check timeout before sleeping.
        elapsed = time.monotonic() - start
        remaining = timeout - elapsed
        if remaining <= 0:
            print(
                f"[verify] TIMEOUT after {elapsed:.0f}s — "
                f"last seen merged_at={last_seen!r}, expected={expected!r}",
                file=sys.stderr,
                flush=True,
            )
            sys.exit(1)

        sleep_for = min(interval, remaining)
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
