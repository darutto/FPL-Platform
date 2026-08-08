"""Shared harness for the FI-8 trial acceptance scripts.

Eight `trial_*.py` scripts each do the same four things -- call, snapshot the raw
response, normalize, report. This module owns everything they share: argument
parsing, mode resolution, client construction, raw-snapshot writing, and report
emission. Written once here rather than eight divergent times; the deviation
from the plan's stated eleven FI-8 files is recorded in the plan's FI-8 spec.

HARD CONSTRAINT -- NO LIVE CALL BEFORE FI-9
-------------------------------------------
`--mock` is the default mode of every script. The live path exists in this file
and is reviewed, but is never executed before FI-9: it requires `--live` plus
the explicit `--i-understand-this-is-live` acknowledgement, mirroring
`cli.py`'s `REFUSED` path and its exit code 2. Tests reach the live *code path*
by injecting a fake transport, never a real one, and `tests/conftest.py` patches
every HTTP entry point to raise so a real call fails loudly.

BYTE-STABILITY
--------------
Reports carry no timestamp. The frozen schema has no time field, so re-running a
script in `--mock` regenerates byte-identical output structurally rather than by
convention -- which is what makes the committed `trial-reports/examples/` copies
usable as evidence instead of churn. Raw snapshots, which the provider stamps
with a real `fetched_at`, are written under `trial-output/` and gitignored; in
mock mode their filenames use `MOCK_CLOCK` so re-runs overwrite rather than
accumulate.

WHY `trial-output` AND `trial-reports` ARE HYPHENATED
-----------------------------------------------------
See `CONTRACT.md`. The package root is on `pythonpath`, so an underscored
sibling directory would be importable -- as a package or, without `__init__.py`,
as a PEP 420 namespace package that merges across paths.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

# Scripts are entry points, not library modules: when run as `python
# scripts/trial_auth.py` the package root is not on sys.path. Bootstrapped once
# here so every trial script inherits it rather than repeating it. Under pytest
# this is a no-op -- pytest.ini already puts `.` on the path.
_PACKAGE_ROOT = str(Path(__file__).resolve().parent.parent)
if _PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _PACKAGE_ROOT)

from sportmonks_client.client import SNAPSHOT_RESPONSE_HEADERS, SportmonksClient  # noqa: E402
from sportmonks_client.config import SportmonksConfig  # noqa: E402
from sportmonks_client.models import RawResponseSnapshot  # noqa: E402
from sportmonks_client.transport import RequestsTransport, Transport, TransportResponse  # noqa: E402

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = PACKAGE_ROOT / "trial-output"
EXAMPLES_DIR = PACKAGE_ROOT / "trial-reports" / "examples"
FIXTURES_DIR = PACKAGE_ROOT / "tests" / "fixtures"

#: Fixed clock for mock mode. Not a report field -- used only for snapshot
#: filenames, so repeated mock runs overwrite rather than accumulate.
MOCK_CLOCK = "2026-01-01T00-00-00Z"

# --- Frozen status vocabulary -------------------------------------------------
# EXACTLY these four. `not_started` is a TRIAL_STATUS.md dashboard value that
# describes the table's state, not a run's outcome; it must never enter this set.
OBSERVED = "observed"
UNMET = "unmet"
DEGRADED = "degraded"
NOT_APPLICABLE = "not_applicable"
STATUSES: tuple[str, ...] = (OBSERVED, UNMET, DEGRADED, NOT_APPLICABLE)

# --- Frozen exit codes --------------------------------------------------------
EXIT_OK = 0            # every claimed objective observed
EXIT_UNMET = 1         # an objective is unmet or degraded
EXIT_REFUSED = 2       # live requested without the acknowledgement flag
EXIT_CONFIG = 3        # configuration or authentication failure

MODE_MOCK = "mock"
MODE_LIVE = "live"


class TrialRefusal(Exception):
    """Live mode requested without the explicit acknowledgement."""


@dataclass(frozen=True)
class Objective:
    """One brief §11.3 acceptance objective as observed by a script."""

    id: int
    title: str
    status: str
    evidence: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(
                f"status {self.status!r} is not one of the frozen four {STATUSES}"
            )


@dataclass(frozen=True)
class ObservedShape:
    """A payload shape as actually found -- reported, never asserted."""

    name: str
    shape: str


@dataclass
class TrialReport:
    """The frozen report schema. Field order here is the emitted order."""

    script: str
    mode: str
    objectives: list[Objective] = field(default_factory=list)
    observed_shapes: list[ObservedShape] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "script": self.script,
            "mode": self.mode,
            "objectives": [
                {"id": o.id, "title": o.title, "status": o.status, "evidence": o.evidence}
                for o in self.objectives
            ],
            "observed_shapes": [{"name": s.name, "shape": s.shape} for s in self.observed_shapes],
            "warnings": list(self.warnings),
        }

    def exit_code(self) -> int:
        """0 unless an objective is unmet or degraded. not_applicable is not a failure."""
        if any(o.status in (UNMET, DEGRADED) for o in self.objectives):
            return EXIT_UNMET
        return EXIT_OK


def build_parser(script: str) -> argparse.ArgumentParser:
    """The frozen invocation surface. S3-S6 inherit this unchanged."""
    parser = argparse.ArgumentParser(prog=script, description=f"FI-8 trial acceptance script: {script}")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mock", action="store_true", default=False,
                      help="rehearse against checked-in fixtures (the default)")
    mode.add_argument("--live", action="store_true", default=False,
                      help="call the real provider; also requires --i-understand-this-is-live")
    parser.add_argument("--i-understand-this-is-live", action="store_true", default=False,
                        help="acknowledgement required by --live")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"artifact directory (default: {DEFAULT_OUT.name}/, gitignored)")
    return parser


def resolve_mode(args: argparse.Namespace) -> str:
    """Mock unless live is explicitly requested *and* acknowledged."""
    if not args.live:
        return MODE_MOCK
    if not args.i_understand_this_is_live:
        raise TrialRefusal("live run requires --i-understand-this-is-live")
    return MODE_LIVE


def load_fixture(name: str) -> Any:
    """Load a checked-in fixture. The tests/fixtures/ set is the package's only
    fixture source; mock mode reads it rather than keeping a second copy."""
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


RATE_LIMIT_HEADERS: tuple[str, ...] = (
    "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
)


@dataclass(frozen=True)
class Exchange:
    """One response as actually received.

    `body_keys` is a **key-name skeleton** -- names only, never values -- so a
    script can report where a block was found and which of its fields were
    present without carrying raw provider data into a report.
    """

    status: int
    headers: Mapping[str, str]
    body_keys: Mapping[str, Any] = field(default_factory=dict)


def body_skeleton(body: Any, depth: int = 3) -> dict[str, Any]:
    """Nested key names, no values. Bounded depth keeps it small on real payloads."""
    if not isinstance(body, Mapping) or depth <= 0:
        return {}
    return {
        str(key): body_skeleton(value, depth - 1) if isinstance(value, Mapping) else {}
        for key, value in body.items()
    }


class ObservingTransport:
    """Wraps any transport and records what actually came back.

    This exists because a script must report what it *received*, not what the
    documentation says it should receive. Without it, a script can only infer
    from call counts, and the difference between "observed" and "asserted"
    collapses -- an FI-8 review caught exactly that: stripping every header from
    the mock transport left the report byte-identical, still claiming
    "rate-limit headers observed".

    Wraps the real transport in live mode too, so FI-9 observes by the same
    mechanism the mock rehearsal does. Only headers on the client's existing
    sanctioned allowlist are retained -- never arbitrary provider headers.
    """

    def __init__(self, inner: Transport) -> None:
        self._inner = inner
        self.exchanges: list[Exchange] = []

    def request(self, method: str, url: str, *, params: Mapping[str, Any], timeout: float) -> TransportResponse:
        response = self._inner.request(method, url, params=params, timeout=timeout)
        self.exchanges.append(Exchange(
            response.status,
            {
                key.casefold(): value for key, value in response.headers.items()
                if key.casefold() in SNAPSHOT_RESPONSE_HEADERS
            },
            body_skeleton(response.body),
        ))
        return response


def observed_rate_limit_fields(exchanges: Sequence[Exchange]) -> tuple[str, ...]:
    """Rate-limit header names actually present, in canonical order. Empty when
    the provider sent none -- which is a `degraded` observation, not a gap to
    paper over."""
    seen = {name for exchange in exchanges for name in exchange.headers}
    return tuple(name for name in RATE_LIMIT_HEADERS if name in seen)


def observed_throttles(exchanges: Sequence[Exchange]) -> tuple[Exchange, ...]:
    """Every throttled response actually received, header or not.

    Kept separate from `observed_retry_after` because conflating them
    under-reports a real 429 that arrived without the header as zero throttles --
    a misobservation inside objective 17's own subject matter.
    """
    return tuple(exchange for exchange in exchanges if exchange.status == 429)


def observed_retry_after(exchanges: Sequence[Exchange]) -> tuple[tuple[int, str], ...]:
    """(status, Retry-After) for throttled responses that carried the header."""
    return tuple(
        (exchange.status, exchange.headers["retry-after"])
        for exchange in observed_throttles(exchanges)
        if "retry-after" in exchange.headers
    )


def observed_pagination(exchanges: Sequence[Exchange]) -> tuple[str | None, tuple[str, ...]]:
    """Where the pagination block was found and which fields it carried.

    Returns `(None, ())` when no response carried pagination metadata. The
    location matters: this client accepts it top-level *or* under `meta`
    (`models.py:73`), and the checked-in fixtures use the top-level form -- so a
    hardcoded `envelope.meta.pagination` would name a location the response did
    not have. `next_page` is optional, so the field list is what was present,
    not what the documentation lists.
    """
    for exchange in exchanges:
        skeleton = exchange.body_keys
        # Presence, not truthiness. A `pagination: {}` block that arrived and
        # carried no field names is a *shape difference worth recording*, not an
        # absent block -- conflating them is the same failure to observe a
        # distinction that this file exists to demonstrate observing.
        if "pagination" in skeleton:
            return "pagination", tuple(skeleton["pagination"])
        nested = skeleton.get("meta", {})
        if isinstance(nested, Mapping) and "pagination" in nested:
            return "meta.pagination", tuple(nested["pagination"])
    return None, ()


def render_skeleton(skeleton: Mapping[str, Any]) -> str:
    """Render a key-name skeleton as `data, pagination{current_page,has_more}`."""
    parts = []
    for key, nested in skeleton.items():
        parts.append(f"{key}{{{','.join(nested)}}}" if nested else key)
    return ", ".join(parts)


class ReplayTransport:
    """Serves checked-in responses in mock mode. Never touches the network."""

    def __init__(self, responses: Sequence[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any], float]] = []

    def request(self, method: str, url: str, *, params: Mapping[str, Any], timeout: float) -> TransportResponse:
        self.calls.append((method, url, dict(params), timeout))
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def response(body: Any, status: int = 200, headers: Mapping[str, str] | None = None) -> TransportResponse:
    return TransportResponse(status, dict(headers or {}), body)


def snapshot_writer(out_dir: Path, mode: str) -> Callable[[RawResponseSnapshot], None]:
    """Write raw provider payloads under out_dir/raw/.

    Gitignored unconditionally, in both modes. The same hook runs live, so a
    slice that committed mock payloads would make FI-9 commit real provider
    payloads by default -- into a public repo, before licensing question 3 has
    been answered.
    """
    raw_dir = out_dir / "raw"

    def _write(snapshot: RawResponseSnapshot) -> None:
        raw_dir.mkdir(parents=True, exist_ok=True)
        stamp = MOCK_CLOCK if mode == MODE_MOCK else snapshot.fetched_at.replace(":", "-")
        safe = snapshot.endpoint.replace("/", "-")
        path = raw_dir / f"{safe}-{stamp}.json"
        path.write_text(
            json.dumps(
                {
                    "endpoint": snapshot.endpoint,
                    "requested_parameters": dict(snapshot.requested_parameters),
                    "fetched_at": snapshot.fetched_at,
                    "status": snapshot.status,
                    "response_metadata": dict(snapshot.response_metadata),
                    "raw_payload": dict(snapshot.raw_payload),
                    "schema_version": snapshot.schema_version,
                },
                indent=2, ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )

    return _write


def make_client(
    mode: str,
    *,
    transport: Transport | None = None,
    config: SportmonksConfig | None = None,
    out_dir: Path | None = None,
) -> SportmonksClient:
    """Construct the client for the resolved mode.

    Mock mode goes through `SportmonksClient.offline(...)`, which requires an
    injected transport and never asks for a token. The live branch below is the
    only place in FI-8 that would construct a real transport; it is written and
    reviewed now and executed for the first time in FI-9. Tests exercise it by
    injecting a fake transport, so the live *code path* is covered without a
    live *call*.
    """
    hook = snapshot_writer(out_dir, mode) if out_dir is not None else None
    if mode == MODE_MOCK:
        if transport is None:
            raise ValueError("mock mode requires an injected transport")
        # Mock mode observes the retry delay from the header; it does not enact
        # it. Sleeping real seconds for a synthetic 429 would put wall-clock
        # time into every rehearsal and every CI run for no added signal.
        return SportmonksClient.offline(
            ObservingTransport(transport), config=config, snapshot_hook=hook,
            sleep=lambda _seconds: None,
        )
    resolved = config or SportmonksConfig.from_env()
    inner = transport or RequestsTransport(max_response_bytes=resolved.max_response_bytes)
    return SportmonksClient(resolved, transport=ObservingTransport(inner), snapshot_hook=hook)


def render_markdown(report: TrialReport) -> str:
    """Human-readable twin of the JSON. Timestamp-free, so it is byte-stable."""
    lines = [
        f"# {report.script} — trial report",
        "",
        f"Mode: `{report.mode}`",
        "",
        "| # | Objective | Status | Evidence |",
        "|---|---|---|---|",
    ]
    for o in report.objectives:
        lines.append(f"| {o.id} | {o.title} | `{o.status}` | {o.evidence} |")
    lines += ["", "## Observed shapes", ""]
    if report.observed_shapes:
        lines += ["| Name | Shape as found |", "|---|---|"]
        lines += [f"| {s.name} | `{s.shape}` |" for s in report.observed_shapes]
    else:
        lines.append("*none recorded*")
    lines += ["", "## Warnings", ""]
    lines += [f"- {w}" for w in report.warnings] if report.warnings else ["*none*"]
    return "\n".join(lines) + "\n"


def write_report(report: TrialReport, out_dir: Path) -> tuple[Path, Path]:
    """Emit the JSON and Markdown pair. Returns (json_path, markdown_path)."""
    reports_dir = out_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / f"{report.script}.json"
    md_path = reports_dir / f"{report.script}.md"
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path
