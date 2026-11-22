"""Tier effective ownership (EO): top-10K stride sample (EO step 2).

Samples 2,000 entries from the top 10,000 of the overall league (every 5th rank),
reads each one's picks for a gameweek whose deadline has passed, and computes per
player: ownership %, captaincy %, bench % and EO % (sum of multiplier / N * 100).
It publishes ``eo/{season}/gw{N}/top10k.json`` only if a split-half consistency
check passes. Free public FPL API only, read-only, sequential and rate limited.

* Resumable: progress is kept in a checkpoint (rank -> compact picks, no entry
  ids, no names) under the same ``eo/`` prefix, and the checkpoint is deleted when
  the run publishes. A run that hits its time or request budget saves and exits 2.
* Storage is an interface. ``LocalStorage`` is for dry runs and tests; ``R2Storage``
  refuses every key outside ``{prefix}eo/`` and never lists anything or deletes
  outside it. The multiplier is the one the API reports for the picks at the
  deadline (bench 0 unless Bench Boost, captain 2, Triple Captain 3); automatic
  substitutions are not applied.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

BASE = "https://fantasy.premierleague.com/api"
OVERALL_LEAGUE = 314
USER_AGENT = "fpl-platform-eo-sampler/1.0 (read-only, rate limited)"
TIMEOUT_S = 20
PAGE_SIZE = 50
TOP_N = 10_000
SAMPLE_N = 2_000
STRIDE = TOP_N // SAMPLE_N  # every 5th rank
SCHEMA_VERSION = 1
TIER = "top10k"

MIN_INTERVAL_S = 0.25          # <= 4 requests per second
MAX_ATTEMPTS = 3
REQUEST_BUDGET = 4_000         # hard cap per run
MIN_SUCCESS_FRACTION = 0.90    # below this the tier is "partial" and not published
SPLIT_HALF_TOP_PLAYERS = 15
SPLIT_HALF_TOLERANCE = 10.0    # percentage points of EO between the two halves
SPLIT_HALF_SEED = 20260101

Fetch = Callable[[str], tuple[int | None, Any, dict[str, str]]]


# -- HTTP ---------------------------------------------------------------------------

def http_get(url: str) -> tuple[int | None, Any, dict[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8")), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, None, dict(exc.headers or {})
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise ConnectionError(type(exc).__name__) from None


class BudgetExceeded(RuntimeError):
    pass


class Client:
    """Sequential, rate limited, retrying GET with a hard request budget."""

    def __init__(self, fetch: Fetch = http_get, *, sleep=time.sleep, clock=time.monotonic,
                 min_interval: float = MIN_INTERVAL_S, budget: int = REQUEST_BUDGET):
        self._fetch, self._sleep, self._clock = fetch, sleep, clock
        self._min_interval, self.budget = min_interval, budget
        self._last: float | None = None
        self.requests = 0

    def get(self, url: str) -> Any | None:
        """The JSON body, or None after MAX_ATTEMPTS failed attempts (404 -> None at once)."""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if self.requests >= self.budget:
                raise BudgetExceeded(f"request budget {self.budget} reached")
            if self._last is not None:
                wait = self._min_interval - (self._clock() - self._last)
                if wait > 0:
                    self._sleep(wait)
            self._last = self._clock()
            self.requests += 1
            try:
                status, body, headers = self._fetch(url)
            except ConnectionError:
                status, body, headers = None, None, {}
            if status == 200 and body is not None:
                return body
            if status == 404:
                return None
            if attempt < MAX_ATTEMPTS:
                retry_after = 0.0
                try:
                    retry_after = float(headers.get("Retry-After", 0))
                except (TypeError, ValueError):
                    pass
                self._sleep(max(retry_after, 2.0 * attempt))
        return None


# -- Sampling and maths ---------------------------------------------------------------

def sample_ranks() -> list[int]:
    """Every STRIDE-th rank of the top TOP_N: STRIDE, 2*STRIDE, ... TOP_N."""
    return list(range(STRIDE, TOP_N + 1, STRIDE))


def standings_page_for_rank(rank: int) -> int:
    return (rank - 1) // PAGE_SIZE + 1


def current_gw(bootstrap: dict[str, Any], now: datetime | None = None) -> int | None:
    """Latest gameweek whose deadline has passed (picks are public from then on)."""
    now = now or datetime.now(timezone.utc)
    passed = []
    for event in bootstrap.get("events") or []:
        raw = event.get("deadline_time")
        if not raw:
            continue
        deadline = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if deadline <= now:
            passed.append(event["id"])
    return max(passed) if passed else None


def compact_picks(picks_body: dict[str, Any]) -> dict[str, Any] | None:
    """The fields EO needs from one picks response: [element, multiplier, is_captain, position]."""
    picks = picks_body.get("picks")
    if not picks:
        return None
    return {
        "chip": picks_body.get("active_chip"),
        "p": [[p["element"], p["multiplier"], bool(p.get("is_captain")), p["position"]] for p in picks],
    }


def compute_eo(samples: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(samples)
    players: dict[int, dict[str, float]] = {}
    chips: dict[str, int] = {}
    for s in samples:
        if s.get("chip"):
            chips[s["chip"]] = chips.get(s["chip"], 0) + 1
        for element, mult, is_cap, _pos in s["p"]:
            row = players.setdefault(element, {"owned": 0, "captain": 0, "bench": 0, "mult": 0})
            row["owned"] += 1
            row["mult"] += mult
            row["captain"] += 1 if is_cap else 0
            row["bench"] += 1 if mult == 0 else 0

    def pct(x: float) -> float:
        return round(100.0 * x / n, 1) if n else 0.0

    return {
        "players": {
            str(el): {"owned_pct": pct(r["owned"]), "captain_pct": pct(r["captain"]),
                      "bench_pct": pct(r["bench"]), "eo": pct(r["mult"])}
            for el, r in sorted(players.items())
        },
        "chips": {f"{name}_pct": pct(count) for name, count in sorted(chips.items())},
    }


def split_half_check(samples: list[dict[str, Any]], *, top_players: int = SPLIT_HALF_TOP_PLAYERS,
                     tolerance: float = SPLIT_HALF_TOLERANCE, seed: int = SPLIT_HALF_SEED) -> dict[str, Any]:
    """Random halves of the sample: the top players' EO must agree within *tolerance* points."""
    shuffled = list(samples)
    random.Random(seed).shuffle(shuffled)
    half = len(shuffled) // 2
    a = compute_eo(shuffled[:half])["players"]
    b = compute_eo(shuffled[half:])["players"]
    whole = compute_eo(samples)["players"]
    top = sorted(whole, key=lambda k: whole[k]["eo"], reverse=True)[:top_players]
    zero = {"eo": 0.0}
    worst = max((abs(a.get(k, zero)["eo"] - b.get(k, zero)["eo"]) for k in top), default=0.0)
    return {"ok": worst <= tolerance, "max_abs_diff": round(worst, 1), "tolerance": tolerance,
            "top_players": len(top), "half_size": half}


# -- Storage ---------------------------------------------------------------------------

class Storage(Protocol):
    def get(self, key: str) -> dict[str, Any] | None: ...
    def put(self, key: str, value: dict[str, Any]) -> None: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key

    def get(self, key: str):
        path = self._path(key)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def put(self, key: str, value) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class R2Storage:
    """R2 via boto3, confined to ``{prefix}eo/``. No listing, no deleting elsewhere."""

    ENV = ("OWNED_STORE_R2_ENDPOINT", "OWNED_STORE_R2_BUCKET",
           "OWNED_STORE_R2_ACCESS_KEY_ID", "OWNED_STORE_R2_SECRET_ACCESS_KEY")

    def __init__(self, client=None, bucket: str | None = None, prefix: str | None = None):
        if client is None:
            missing = [n for n in self.ENV if not (os.environ.get(n) or "").strip()]
            if missing:
                raise RuntimeError(f"missing required R2 env vars: {', '.join(missing)}")
            import boto3  # noqa: PLC0415  (lazy)
            client = boto3.client(
                "s3", endpoint_url=os.environ["OWNED_STORE_R2_ENDPOINT"].strip(),
                aws_access_key_id=os.environ["OWNED_STORE_R2_ACCESS_KEY_ID"].strip(),
                aws_secret_access_key=os.environ["OWNED_STORE_R2_SECRET_ACCESS_KEY"].strip(),
                region_name="auto")
            bucket = os.environ["OWNED_STORE_R2_BUCKET"].strip()
        raw = prefix if prefix is not None else (os.environ.get("OWNED_STORE_R2_PREFIX") or "")
        raw = raw.strip().lstrip("/")
        self.prefix = (raw.rstrip("/") + "/") if raw else ""
        self.eo_root = f"{self.prefix}eo/"
        self._client, self._bucket = client, bucket

    def _key(self, key: str) -> str:
        """The full object key; an AssertionError for anything outside ``{prefix}eo/``."""
        full = f"{self.prefix}{key}"
        if not full.startswith(self.eo_root) or ".." in full.split("/"):
            raise AssertionError(f"refusing key outside {self.eo_root!r}")  # not `assert`: survives python -O
        return full

    def get(self, key: str):
        full = self._key(key)
        try:
            obj = self._client.get_object(Bucket=self._bucket, Key=full)
        except Exception as exc:  # noqa: BLE001  (a missing key -> None; anything else surfaces)
            if "NoSuchKey" in type(exc).__name__ or "NoSuchKey" in str(exc) or "404" in str(exc):
                return None
            raise
        return json.loads(obj["Body"].read().decode("utf-8"))

    def put(self, key: str, value) -> None:
        self._client.put_object(Bucket=self._bucket, Key=self._key(key),
                                Body=json.dumps(value, separators=(",", ":")).encode("utf-8"),
                                ContentType="application/json")

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=self._key(key))


# -- The run -----------------------------------------------------------------------------

def output_key(season: str, gw: int) -> str:
    return f"eo/{season}/gw{gw}/{TIER}.json"


def checkpoint_key(season: str, gw: int) -> str:
    return f"eo/{season}/gw{gw}/_checkpoint_{TIER}.json"


def run(*, season: str, gw: int | None, storage: Storage, client: Client,
        max_seconds: float = 2400.0, clock=time.monotonic, log=print,
        now: datetime | None = None) -> int:
    """0 published, 1 failed (check or too few samples), 2 budget hit (checkpoint saved)."""
    started = clock()
    if gw is None:
        bootstrap = client.get(f"{BASE}/bootstrap-static/")
        gw = current_gw(bootstrap, now) if bootstrap else None
    if gw is None:
        log("no gameweek with a passed deadline; nothing to do")
        return 1
    log(f"season={season} gw={gw} tier={TIER}")

    ckpt_key = checkpoint_key(season, gw)
    ckpt = storage.get(ckpt_key) or {}
    done: dict[str, Any] = ckpt.get("samples", {})
    failed: set[str] = set(ckpt.get("failed", []))
    log(f"resuming: {len(done)} done, {len(failed)} failed")

    def save() -> None:
        storage.put(ckpt_key, {"samples": done, "failed": sorted(failed)})

    ranks = sample_ranks()
    pages: dict[int, list[int]] = {}
    for rank in ranks:
        if str(rank) not in done and str(rank) not in failed:
            pages.setdefault(standings_page_for_rank(rank), []).append(rank)

    try:
        for page, wanted in sorted(pages.items()):
            if clock() - started > max_seconds:
                save()
                log(f"time budget reached; checkpoint saved ({len(done)} done)")
                return 2
            body = client.get(f"{BASE}/leagues-classic/{OVERALL_LEAGUE}/standings/?page_standings={page}")
            results = ((body or {}).get("standings") or {}).get("results") or []
            by_rank = {r.get("rank"): r.get("entry") for r in results}
            for rank in wanted:
                entry = by_rank.get(rank)
                picks = client.get(f"{BASE}/entry/{entry}/event/{gw}/picks/") if entry else None
                compact = compact_picks(picks) if picks else None
                if compact:
                    done[str(rank)] = compact
                else:
                    failed.add(str(rank))
            if page % 20 == 0:
                save()
    except BudgetExceeded as exc:
        save()
        log(f"{exc}; checkpoint saved ({len(done)} done)")
        return 2

    samples = [done[k] for k in sorted(done, key=int)]
    fraction = len(samples) / len(ranks)
    log(f"sampled {len(samples)}/{len(ranks)} ({fraction:.1%}); requests={client.requests}")
    if fraction < MIN_SUCCESS_FRACTION:
        save()
        log("too many failures: partial, nothing published")
        return 1
    check = split_half_check(samples)
    log(f"split-half: ok={check['ok']} max_abs_diff={check['max_abs_diff']} tolerance={check['tolerance']}")
    if not check["ok"]:
        save()
        log("split-half check failed: nothing published")
        return 1

    out = {
        "schema_version": SCHEMA_VERSION, "season": season, "gw": gw, "tier": TIER,
        "basis": "locked", "n_sampled": len(samples), "n_target": len(ranks),
        "sampled_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "sampling": {"league": OVERALL_LEAGUE, "ranks": f"every {STRIDE}th of top {TOP_N}"},
        "split_half": check, **compute_eo(samples),
    }
    storage.put(output_key(season, gw), out)
    storage.delete(ckpt_key)
    log(f"published {output_key(season, gw)} ({len(out['players'])} players)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Top-10K tier EO sampler")
    ap.add_argument("--season", required=True)
    ap.add_argument("--gw", type=int, default=None, help="default: latest GW whose deadline has passed")
    ap.add_argument("--publish", choices=["none", "r2"], default="none",
                    help="none = dry run into --out-dir (default); r2 = write to R2 under eo/")
    ap.add_argument("--out-dir", default="eo_out")
    ap.add_argument("--max-seconds", type=float, default=2400.0)
    args = ap.parse_args(argv)
    storage: Storage = R2Storage() if args.publish == "r2" else LocalStorage(Path(args.out_dir))
    return run(season=args.season, gw=args.gw, storage=storage, client=Client(),
               max_seconds=args.max_seconds)


if __name__ == "__main__":
    sys.exit(main())
