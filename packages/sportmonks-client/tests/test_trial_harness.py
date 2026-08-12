"""FI-8 S2: the trial harness, the frozen contract, and the live-call guard.

Everything S3-S6 inherit without re-reading is pinned here: the report schema,
the four-status enum, the exit codes, the `--out` default, the gitignore rule,
and byte-stability of mock output.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest
import requests
import requests.adapters

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import _trial_common  # noqa: E402
import trial_auth  # noqa: E402
from _trial_common import (  # noqa: E402
    DEFAULT_OUT, DEGRADED, EXAMPLES_DIR, EXIT_CONFIG, EXIT_OK, EXIT_REFUSED,
    EXIT_UNMET, MODE_LIVE, MODE_MOCK, NOT_APPLICABLE, OBSERVED, PACKAGE_ROOT,
    STATUSES, UNMET, Exchange, Objective, ObservingTransport, ReplayTransport,
    TrialReport, build_parser, make_client, observed_pagination,
    observed_rate_limit_fields, observed_retry_after, observed_throttles,
    render_markdown, render_skeleton, resolve_mode, response, write_report,
)
from sportmonks_client.config import SportmonksConfig
from sportmonks_client.errors import SportmonksRateLimitError

REPO_ROOT = PACKAGE_ROOT.parent.parent


# --- The guard ----------------------------------------------------------------

#: Loopback with nothing listening. Every test that exercises the guard aims
#: here, never at the provider: if the guard ever regresses, the suite's failure
#: mode must be a refused local connection, not an authenticated-shaped GET to
#: api.sportmonks.com. The guard fires before any DNS or socket work, so the
#: host is irrelevant to the proof and entirely relevant to the blast radius.
LOOPBACK = "http://127.0.0.1:1"

#: The two callables the guard replaces, captured at import time -- collection
#: happens before any fixture runs, so these are the genuine unpatched
#: implementations. The isolation tests below hand one of them back mid-test in
#: order to run with a single layer of the guard standing.
REAL_SESSION_REQUEST = requests.Session.request
REAL_ADAPTER_SEND = requests.adapters.HTTPAdapter.send


def test_the_guard_fires_on_a_real_session_request():
    """The seeded violation, made permanent.

    Attempts the boundary itself -- `requests.Session().request(...)` -- rather
    than a `RequestsTransport` construction, so the proof matches what is
    guarded. Without the autouse fixture in conftest.py this call would attempt
    real network I/O; against LOOPBACK that is a refused connection, never a
    provider call.
    """
    with pytest.raises(AssertionError, match="live network call attempted"):
        requests.Session().request("GET", f"{LOOPBACK}/leagues")


def test_the_guard_covers_the_adapter_entry_point_too():
    with pytest.raises(AssertionError, match="live network call attempted"):
        requests.adapters.HTTPAdapter().send(requests.Request("GET", LOOPBACK).prepare())


# The two tests above assert the *outcome* -- a call was refused -- and both
# layers of the guard produce that outcome with the same exception and the same
# message. A subject-deletion sweep measured the consequence: with
# `monkeypatch.setattr(requests.Session, "request", _refuse)` deleted from
# conftest.py, the whole suite stayed green, because `Session.request` fell
# through to the still-patched `HTTPAdapter.send`. Defence in depth whose layers
# share an observable outcome is indistinguishable from a single layer.
#
# The pair below removes that ambiguity by isolation: each test hands one layer
# back to its real implementation and exercises the entry point the *other*
# layer guards. They assert what the outcome tests cannot -- that each layer
# catches the call alone -- and they fail individually, naming the layer that
# went missing. Both aim at LOOPBACK, so the failure mode when a layer is
# genuinely absent is a refused local connection.

def test_the_session_layer_refuses_on_its_own_with_the_adapter_layer_stood_down(monkeypatch):
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", REAL_ADAPTER_SEND)
    with pytest.raises(AssertionError, match="live network call attempted"):
        requests.Session().request("GET", f"{LOOPBACK}/leagues")


def test_the_adapter_layer_refuses_on_its_own_with_the_session_layer_stood_down(monkeypatch):
    monkeypatch.setattr(requests.Session, "request", REAL_SESSION_REQUEST)
    with pytest.raises(AssertionError, match="live network call attempted"):
        requests.adapters.HTTPAdapter().send(requests.Request("GET", LOOPBACK).prepare())


# The isolation tests above prove each layer catches the call alone. They say
# nothing about whether the two layers *cover the surface* -- that holds only
# while `requests` is the package's sole way out. Today it is: `transport.py:8`
# is the one import, and nothing here reaches the network by any other route.
#
# That is a standing condition, not a settled fact. The day someone adds `httpx`
# the guard becomes incomplete, and the discovery would otherwise be a live call
# during FI-9. So the condition is pinned rather than remembered: an allowlist,
# not a denylist, so a client nobody thought of fails it too.

#: Directories the guard's completeness claim covers. `tests/` is included
#: deliberately -- a test that imported another client would bypass the guard
#: exactly as production code would.
GUARDED_DIRS = ("sportmonks_client", "scripts", "tests")

def _first_party_roots():
    """Top-level names this package supplies itself, derived from the tree.

    Written as a literal list first, which broke on the next slice: S3 added two
    scripts and the allowlist failed on our own files. Making a maintainer edit
    a list every time they add a script is precisely the friction that ends in
    someone loosening the assertion instead — so the list is derived. It can
    only ever classify *our own files* as first-party, which they are.
    """
    roots = {
        child.name for child in PACKAGE_ROOT.iterdir()
        if (child / "__init__.py").exists()
    }
    for directory in GUARDED_DIRS:
        roots |= {path.stem for path in (PACKAGE_ROOT / directory).glob("*.py")}
    return frozenset(roots)


#: Modules importable from this package that are neither stdlib nor third-party.
FIRST_PARTY = _first_party_roots()

#: The pin. Growth here is an event, not a drift: adding an entry is a
#: deliberate edit that must be accompanied by extending the conftest guard to
#: that library's entry points, or by an argument for why it cannot reach the
#: network.
#:
#: `football_identity_registry` is the second kind, added by FI-8 S6 — the one
#: slice §15 permits to read outside this package. It is a sibling package in
#: this repository, not an installed library, and the argument that it cannot
#: reach the network is not left as this comment:
#: `test_the_registry_import_adds_no_network_capable_module` below measures what
#: importing it actually loads. That distinction matters here more than usual,
#: because `football_identity_registry` *does* import `pandas` and `yaml` — in
#: `corpus.py`, `store.py`, and `overrides.py`, none of which are on the import
#: path `trial_mapping` takes. A file scan would report a dependency that never
#: executes.
EXPECTED_THIRD_PARTY = frozenset({
    "requests", "pytest", "football_identity_registry",
})

#: The packages S6 is permitted to reach outside this package, as top-level
#: names. `football_data_contract` is on `trial_mapping`'s `sys.path` as the
#: registry's own dependency but is imported by none of our files, which is why
#: it is not here: this set is what *we* reach for, not what our dependencies do.
SIBLING_PACKAGE_ROOTS = frozenset({"football_identity_registry"})

#: Stdlib routes out, matched on the full dotted name so that `urllib.parse`
#: -- string handling, not networking -- does not read as a violation.
NETWORK_CAPABLE_STDLIB = (
    "socket", "ssl", "http", "urllib.request", "urllib.error", "ftplib",
    "smtplib", "poplib", "imaplib", "nntplib", "xmlrpc", "asyncio",
    "webbrowser", "socketserver",
)


def _imported_modules(*roots):
    """Every module imported under `roots`, by full dotted name.

    Parses rather than greps: the same reason `test_the_probe_never_shells_out_
    to_git_to_restore` uses the AST. A docstring naming `httpx` is not an import
    of it, and a grep cannot tell the difference.
    """
    found = {}
    for root in roots:
        for path in sorted(Path(root).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    found.setdefault(name, set()).add(str(path))
    return found


def test_the_import_enumerator_reports_what_each_file_imports(tmp_path):
    """Two inputs, different expectations -- the enumerator is the instrument
    every claim below rests on, so it is measured before it is trusted."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "one.py").write_text(
        "import requests\nfrom urllib.parse import quote\n", encoding="utf-8")
    (tmp_path / "b" / "two.py").write_text(
        '"""httpx is named here but not imported."""\nimport socket\n', encoding="utf-8")

    assert set(_imported_modules(tmp_path / "a")) == {"requests", "urllib.parse"}
    assert set(_imported_modules(tmp_path / "b")) == {"socket"}


def test_requests_is_the_only_network_client_the_package_can_reach(monkeypatch):
    monkeypatch.chdir(PACKAGE_ROOT)
    imported = _imported_modules(*GUARDED_DIRS)
    third_party = {
        name.split(".")[0] for name in imported
        if name.split(".")[0] not in sys.stdlib_module_names
        and name.split(".")[0] not in FIRST_PARTY
    }
    assert third_party == EXPECTED_THIRD_PARTY, (
        "The live-call guard patches `requests` entry points only, so its "
        "completeness holds exactly while `requests` is this package's sole "
        "route out.\n"
        f"  unexpected: {sorted(third_party - EXPECTED_THIRD_PARTY)}\n"
        f"  missing:    {sorted(EXPECTED_THIRD_PARTY - third_party)}\n"
        "A legitimate new dependency is a two-step decision, not a reason to "
        "loosen this assertion:\n"
        "  1. Extend the autouse guard in tests/conftest.py to the new "
        "library's network entry points, with an isolation test per layer "
        "(see test_the_session_layer_refuses_on_its_own_with_the_adapter_"
        "layer_stood_down) -- or record in this test why the library cannot "
        "reach the network at all.\n"
        "  2. Add its top-level name to EXPECTED_THIRD_PARTY above."
    )

    reached = sorted(
        name for name in imported
        if any(name == mod or name.startswith(f"{mod}.")
               for mod in NETWORK_CAPABLE_STDLIB)
    )
    assert reached == [], (
        f"A stdlib network route out of the package: {reached}\n"
        "The guard patches `requests` only, so this path is unguarded and a "
        "call through it would reach the provider during FI-9.\n"
        "Either route the call through `requests` and the existing transport "
        "seam, or -- if this import genuinely cannot reach the network -- "
        "narrow NETWORK_CAPABLE_STDLIB above to the dotted names that can, "
        "the way `urllib.request` is listed and `urllib.parse` is not."
    )


def _modules_loaded_by(statement):
    """Top-level module names a fresh interpreter loads for `statement`.

    A subprocess, because in-process `sys.modules` carries whatever every other
    test in the suite already imported — a check that passes because pandas
    happened not to be imported *yet* is a check whose result depends on
    collection order.
    """
    probe = (
        "import json, sys\n"
        f"sys.path.insert(0, {str(PACKAGE_ROOT / 'scripts')!r})\n"
        f"{statement}\n"
        "print(json.dumps(sorted({name.split('.')[0] for name in sys.modules})))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=PACKAGE_ROOT,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return set(json.loads(result.stdout.strip().splitlines()[-1]))


def test_the_module_load_probe_sees_what_a_statement_actually_imports():
    """The instrument before the claim. Two statements, different expectations —
    a probe returning the same set for both would make every assertion below
    vacuous, and both of them assert on a *difference*."""
    baseline = _modules_loaded_by("pass")
    with_socket = _modules_loaded_by("import socket")
    assert "socket" not in baseline
    assert "socket" in with_socket


def test_the_registry_import_adds_no_network_capable_module():
    """The argument that S6's sibling package cannot reach the network, made as
    a measurement.

    The allowlist above grew by one entry, and the pin's own error message
    sanctions that only when the conftest guard is extended to the new library's
    entry points *or* the library provably cannot reach the network. This is the
    second, and it interrogates **what actually loads** rather than what the
    files say: `football_identity_registry` contains `import pandas` and
    `import yaml`, in three modules that are not on the path `trial_mapping`
    takes. Reading the tree would report a dependency that never executes — the
    `inspect.getsource` entry in §15's adjacent-question table, in a different
    costume.

    Measured as a **difference** against the harness alone. `requests` brings
    `http`, `socket`, and `ssl` with it and always has; those are the routes the
    conftest guard covers. The question this test asks is the narrow one the
    allowlist entry rests on: does the registry path add any *more*.
    """
    baseline = _modules_loaded_by("import _trial_common")
    added = _modules_loaded_by("import trial_mapping") - baseline

    reached = sorted(
        name for name in added
        if any(name == mod or name.startswith(f"{mod}.") for mod in NETWORK_CAPABLE_STDLIB)
    )
    assert reached == [], (
        "Importing the identity-registry path loaded a network-capable module "
        f"the harness alone does not: {reached}. The allowlist entry for "
        "football_identity_registry rests on it being unable to reach the "
        "network; that is no longer true."
    )
    assert "pandas" not in added and "yaml" not in added, (
        "A pandas- or yaml-importing module of football_identity_registry is "
        "now on trial_mapping's import path. Both can open URLs, so the "
        "allowlist argument above no longer holds — either keep the import "
        "path off those modules or extend the conftest guard to them."
    )
    assert "football_identity_registry" in added, (
        "The difference no longer contains the registry at all, so this test is "
        "measuring nothing. Either the import moved or the baseline grew to "
        "include it."
    )


def test_the_sibling_packages_are_the_only_ones_reached_outside_this_package():
    """S6 is the only slice permitted to read outside the package, and it names
    two. A third arriving is growth nobody decided on."""
    imported = _imported_modules(*(PACKAGE_ROOT / name for name in GUARDED_DIRS))
    outside = {
        name.split(".")[0] for name in imported
        if name.split(".")[0] not in sys.stdlib_module_names
        and name.split(".")[0] not in FIRST_PARTY
        and name.split(".")[0] not in {"requests", "pytest"}
    }
    assert outside == SIBLING_PACKAGE_ROOTS


def test_the_first_party_derivation_finds_the_modules_it_is_supposed_to():
    """Derived, so it needs its own subject: a derivation returning everything
    would classify a real third-party client as ours and the pin would pass
    while guarding nothing."""
    assert {"sportmonks_client", "trial_auth", "conftest"} <= FIRST_PARTY
    assert "requests" not in FIRST_PARTY
    assert "pytest" not in FIRST_PARTY


def test_the_completeness_check_actually_read_the_package(monkeypatch):
    """Both assertions above are satisfiable by an enumerator that scanned
    nothing. This one is not: it names the file the guard's premise rests on."""
    monkeypatch.chdir(PACKAGE_ROOT)
    imported = _imported_modules(*GUARDED_DIRS)
    assert str(Path("sportmonks_client/transport.py")) in imported["requests"]


def test_default_client_construction_cannot_reach_the_network(monkeypatch):
    """The path the guard most needs to catch: no injected transport, so the
    client builds a real RequestsTransport around a real Session.

    `base_url` is pointed at loopback so that if the guard regresses this test
    fails with a refused connection rather than sending a token-bearing request
    to the provider.
    """
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "DUMMY-TOKEN")
    monkeypatch.setenv("SPORTMONKS_BASE_URL", LOOPBACK)
    client = make_client(MODE_LIVE)
    with pytest.raises(AssertionError, match="live network call attempted"):
        client.leagues()


# --- Mode resolution and refusal ----------------------------------------------

def test_mock_is_the_default_mode():
    assert resolve_mode(build_parser("t").parse_args([])) == MODE_MOCK
    assert resolve_mode(build_parser("t").parse_args(["--mock"])) == MODE_MOCK


def test_live_without_acknowledgement_is_refused(capsys):
    assert trial_auth.main(["--live"]) == EXIT_REFUSED
    assert capsys.readouterr().out.startswith("REFUSED:")


def test_live_with_acknowledgement_resolves_to_live():
    args = build_parser("t").parse_args(["--live", "--i-understand-this-is-live"])
    assert resolve_mode(args) == MODE_LIVE


def test_mock_and_live_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        build_parser("t").parse_args(["--mock", "--live"])


# --- Token wiring (plan §14.1) ------------------------------------------------

def test_token_absent_degrades_cleanly(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    code = trial_auth.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path)])
    assert code == EXIT_CONFIG
    out = capsys.readouterr().out
    assert out.startswith("CONFIG: SportmonksConfigurationError")
    assert "Traceback" not in out


def test_dummy_token_surfaces_auth_failure_without_leaking_it(monkeypatch, tmp_path, capsys):
    """The token-leak half of DoD 4, asserted against real report bytes.

    The first version of this test returned before any report was written, so
    `token not in printed` ran against stdout that the preceding assertion had
    already pinned to a single fixed line -- it could not fail for any
    implementation. The failure paths now write a report, so there are bytes to
    check.
    """
    token = "DUMMY-TRIAL-TOKEN"
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", token)
    monkeypatch.setattr(
        trial_auth, "make_client",
        lambda mode, **kw: _trial_common.make_client(
            mode, transport=ReplayTransport([response({}, status=401)]),
            config=SportmonksConfig(api_token=token), out_dir=kw.get("out_dir"),
        ),
    )
    code = trial_auth.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path)])
    assert code == EXIT_CONFIG
    printed = capsys.readouterr().out
    assert printed.startswith("AUTH: SportmonksAuthenticationError")
    assert token not in printed

    payload = json.loads((tmp_path / "reports" / "trial_auth.json").read_text(encoding="utf-8"))
    assert payload["objectives"][0]["status"] == UNMET, (
        "a run that never reached the provider observed nothing, so the objective "
        "is unmet rather than partially degraded"
    )

    report_bytes = (tmp_path / "reports" / "trial_auth.json").read_bytes()
    markdown_bytes = (tmp_path / "reports" / "trial_auth.md").read_bytes()
    assert report_bytes, "the auth-failure path must still write a report"
    assert token.encode() not in report_bytes
    assert token.encode() not in markdown_bytes


def test_the_leak_check_would_catch_a_token_in_the_report(tmp_path):
    """Proves the assertion above is not vacuous: a report that does contain the
    token fails the same check."""
    token = "DUMMY-TRIAL-TOKEN"
    leaky = TrialReport("trial_auth", MODE_MOCK, warnings=[f"api_token={token}"])
    write_report(leaky, tmp_path)
    assert token.encode() in (tmp_path / "reports" / "trial_auth.json").read_bytes()


# --- Pagination and rate-limit observation (objective 17) ---------------------

def _run(tmp_path, **kwargs):
    """Run trial_auth against a configurable mock transport and return its report."""
    if kwargs:
        original = trial_auth.mock_transport
        trial_auth.mock_transport = lambda: original(**kwargs)
    try:
        code = trial_auth.main(["--out", str(tmp_path)])
    finally:
        if kwargs:
            trial_auth.mock_transport = original
    return code, json.loads((tmp_path / "reports" / "trial_auth.json").read_text(encoding="utf-8"))


def test_mock_run_walks_pages_and_observes_rate_limit_headers(tmp_path):
    code, payload = _run(tmp_path)
    assert code == EXIT_OK
    objective = payload["objectives"][0]
    assert objective["id"] == 17 and objective["status"] == OBSERVED
    assert "x-ratelimit-limit, x-ratelimit-remaining, x-ratelimit-reset" in objective["evidence"]
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["rate_limit_headers"] == "x-ratelimit-limit, x-ratelimit-remaining, x-ratelimit-reset"


#: Header subsets and the exact `rate_limit_headers` entry each must produce.
#: Standing DoD item 11: the all-or-nothing switch alone could not tell
#: "reports what arrived" from "reports the canonical set whenever anything
#: arrived" -- the latter survived a seeding probe of the single-input version.
RATE_HEADER_SUBSETS = [
    pytest.param(
        ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"),
        "x-ratelimit-limit, x-ratelimit-remaining, x-ratelimit-reset",
        id="all-three",
    ),
    pytest.param(("X-RateLimit-Remaining",), "x-ratelimit-remaining", id="remaining-only"),
    pytest.param(
        ("X-RateLimit-Limit", "X-RateLimit-Reset"),
        "x-ratelimit-limit, x-ratelimit-reset",
        id="limit-and-reset",
    ),
]


@pytest.mark.parametrize("served,expected", RATE_HEADER_SUBSETS)
def test_the_rate_limit_entry_names_the_headers_that_arrived_and_no_others(tmp_path, served, expected):
    _, payload = _run(tmp_path, rate_limit_headers=served)
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["rate_limit_headers"] == expected
    assert f"rate-limit fields seen: {expected}" in payload["objectives"][0]["evidence"]


def test_the_rate_header_subsets_are_pairwise_distinguishing():
    expected = [case.values[1] for case in RATE_HEADER_SUBSETS]
    assert len(set(expected)) == len(expected) >= 2


@pytest.mark.parametrize("value,expected", [("2", "HTTP 429 retry-after=2"), ("7", "HTTP 429 retry-after=7")])
def test_the_retry_after_entry_carries_the_value_that_arrived(tmp_path, value, expected):
    """Equality, not containment, and two values. The single-input substring
    version was satisfied by the literal `"HTTP 429 retry-after=2"`."""
    _, payload = _run(tmp_path, retry_after=value)
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["retry_after"] == expected


def test_the_objective_17_evidence_string_is_derived_end_to_end(tmp_path):
    """The evidence string as a whole, pinned by `==` on two inputs that differ
    in every derived sub-field. Every prior assertion against it was `in`, so
    three independent literals inside it survived a seeding probe: the record
    count, the rate-limit field list, and the Retry-After count."""
    _, full = _run(tmp_path)
    assert full["objectives"][0]["evidence"] == (
        "walked 2 pages, 2 records; "
        "pagination at: pagination; "
        "rate-limit fields seen: x-ratelimit-limit, x-ratelimit-remaining, x-ratelimit-reset; "
        "throttled responses: 1 (with Retry-After: 1)"
    )

    _, thin = _run(tmp_path, rate_limit_headers=("X-RateLimit-Remaining",), throttle=False, pagination=False)
    assert thin["objectives"][0]["evidence"] == (
        "walked 1 pages, 1 records; "
        "pagination at: none; "
        "rate-limit fields seen: x-ratelimit-remaining; "
        "throttled responses: 0 (with Retry-After: 0) — "
        "pagination did not advance beyond 1 page(s); "
        "no pagination metadata on any response"
    )
    assert full["objectives"][0]["evidence"] != thin["objectives"][0]["evidence"]

    # A third input with **two** throttles. Two inputs alone left the counts
    # satisfiable by `1 if retry_afters else 0`, which is a boolean wearing an
    # integer's name -- it survived the probe until this case existed.
    _, twice = _run(tmp_path, throttle=2)
    assert "throttled responses: 2 (with Retry-After: 2)" in twice["objectives"][0]["evidence"]


def test_removing_the_headers_degrades_the_objective_and_drops_the_shape(tmp_path):
    """Standing DoD item 10, made falsifiable.

    The first version of this slice passed this scenario unchanged: the evidence
    string and the shape entry were literals, so deleting every header left the
    report byte-identical. That defect was found by running this experiment, not
    by reading the code -- which is why it is now a required test rather than a
    review habit.
    """
    code, payload = _run(tmp_path, rate_limit_headers=False)
    objective = payload["objectives"][0]
    assert code == EXIT_UNMET
    assert objective["status"] == DEGRADED
    assert "no rate-limit headers present" in objective["evidence"]
    assert "rate-limit fields seen: none" in objective["evidence"]
    assert not [s for s in payload["observed_shapes"] if s["name"] == "rate_limit_headers"]


def test_pagination_shape_reports_the_location_and_fields_actually_present(tmp_path):
    """The checked-in fixtures carry pagination at the **top level**, not under
    `meta` -- the client accepts either (`models.py:73`). A hardcoded
    `envelope.meta.pagination` would name a location the response did not have,
    which is what the first two versions of this slice shipped."""
    _, payload = _run(tmp_path)
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["pagination"] == "envelope.pagination{current_page,has_more,next_page}"
    assert "meta.pagination" not in shapes["pagination"]
    assert "pagination at: pagination" in payload["objectives"][0]["evidence"]


def test_removing_the_pagination_metadata_drops_the_shape(tmp_path):
    """Standing DoD item 10 for the pagination entry. The previous version
    keyed this shape off a 200-response count, so it survived deleting the
    pagination block entirely."""
    code, payload = _run(tmp_path, pagination=False)
    assert code == EXIT_UNMET
    assert payload["objectives"][0]["status"] == DEGRADED
    assert "no pagination metadata on any response" in payload["objectives"][0]["evidence"]
    assert "pagination at: none" in payload["objectives"][0]["evidence"]
    assert not [s for s in payload["observed_shapes"] if s["name"] == "pagination"]


def _run_with_transport(tmp_path, responses):
    """Run trial_auth against an explicit response sequence."""
    original = trial_auth.mock_transport
    trial_auth.mock_transport = lambda: ReplayTransport(responses)
    try:
        code = trial_auth.main(["--out", str(tmp_path)])
    finally:
        trial_auth.mock_transport = original
    return code, json.loads((tmp_path / "reports" / "trial_auth.json").read_text(encoding="utf-8"))


#: Three refused payloads whose skeletons are pairwise different, and the exact
#: string each must round-trip to. This is the falsification pattern S3, S4a,
#: S4b, S5a, S5b, and S6 copy for every derived-content entry (standing DoD
#: item 11): more than one input, expected outputs that differ, and equality
#: rather than containment. One payload plus a substring assertion proves the
#: entry *exists*; it cannot distinguish a derivation from a literal, because
#: any literal containing the substring passes.
#:
#: All three are rejected by `parse_envelope` for the same reason -- `has_more`
#: is not a bool -- so the payloads vary only in the dimension under test.
REFUSED_PAYLOADS = [
    pytest.param(
        {"data": [{"id": 1}], "pagination": {"current_page": 1, "has_more": "yes"}},
        "data, pagination{current_page,has_more}",
        id="pagination-top-level",
    ),
    pytest.param(
        {"data": [{"id": 1}], "meta": {"pagination": {"current_page": 1, "has_more": "yes"}}},
        "data, meta{pagination{current_page,has_more}}",
        id="pagination-under-meta",
    ),
    pytest.param(
        # The envelope Sportmonks v3 actually documents around `data`: a
        # `subscription` list and a `rate_limit` block. If the live payload
        # carries blocks we have never seen, this is the entry that shows them,
        # so it has to reproduce the whole top level rather than the part we
        # expected.
        {
            "data": [{"id": 1}],
            "subscription": [{"meta": {}}],
            "rate_limit": {"resets_in_seconds": 3600, "remaining": 2997},
            "pagination": {"current_page": 1, "has_more": "yes"},
        },
        "data, subscription, rate_limit{resets_in_seconds,remaining}, pagination{current_page,has_more}",
        id="unexpected-live-blocks",
    ),
]


@pytest.mark.parametrize("body,expected_skeleton", REFUSED_PAYLOADS)
def test_a_payload_the_parser_rejects_degrades_and_records_what_arrived(
    tmp_path, body, expected_skeleton,
):
    """The single scenario FI-8 exists to rehearse: a live payload differing
    from the documented shape (§17's top risk).

    `has_more` as a string rather than a bool makes `parse_envelope` raise. The
    first version surfaced that as exit **3** -- which the frozen contract
    defines as *configuration/auth failure* -- with an empty `observed_shapes`,
    discarding the very payload the trial needed to see. The contract already
    said the opposite: a script "must not fail merely because a payload differs
    from the documented shape; it records the difference and marks the objective
    `degraded`."

    The second version fixed the discard but proved only that *an*
    `rejected_envelope` entry appeared, asserting a substring one fixed payload
    happened to contain. Replacing the derivation with the literal
    `"data[],pagination{current_page,has_more}"` left the whole suite green --
    measured, not supposed. Four slices had copied that test by then. Hence
    three payloads and equality: no single literal satisfies all three.
    """
    code, payload = _run_with_transport(tmp_path, [response(body)])
    objective = payload["objectives"][0]
    assert code == EXIT_UNMET, "a shape difference is not a configuration failure"
    assert code != EXIT_CONFIG
    assert objective["status"] == DEGRADED
    assert "payload rejected by the parser" in objective["evidence"]

    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert "rejected_envelope" in shapes, "the refused payload must be recorded, not discarded"
    assert shapes["rejected_envelope"] == expected_skeleton


def test_the_rejected_envelope_records_the_response_that_was_refused(tmp_path):
    """*Which* exchange the entry reads, which a single-response sequence cannot
    test: with one response, `exchanges[0]` and `exchanges[-1]` coincide, so
    swapping them left the suite green. Page one parses; page two is refused. The
    entry must describe page two -- the one that failed -- and the two pages'
    skeletons differ, so reading the wrong end is now a failure."""
    code, payload = _run_with_transport(tmp_path, [
        response({"data": [{"id": 1}], "pagination": {"current_page": 1, "has_more": True, "next_page": 2}}),
        response({"data": [{"id": 2}], "meta": {"pagination": {"current_page": 2, "has_more": "no"}}}),
    ])
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert code == EXIT_UNMET
    assert shapes["rejected_envelope"] == "data, meta{pagination{current_page,has_more}}"
    assert shapes["rejected_envelope"] != "data, pagination{current_page,has_more,next_page}", (
        "that is page one, which parsed fine"
    )


def test_the_refused_payload_cases_are_pairwise_distinguishing():
    """The property that makes the parametrization falsifying rather than
    merely repetitive. If two cases ever expect the same string, a literal of
    that string passes both and the redundancy hides it -- so the distinctness
    the pattern relies on is asserted, not assumed."""
    expected = [case.values[1] for case in REFUSED_PAYLOADS]
    assert len(set(expected)) == len(expected) >= 2


#: Pagination carried at two different locations, end to end, and the exact
#: `pagination` entry each must produce. Item 11's two inputs for this entry
#: previously differed only in their *field list*, so the location half stayed a
#: literal: replacing `envelope.{page_location}` with `envelope.pagination` left
#: all 122 green. That is the defect S2 was rejected for twice — naming a
#: location the response never had — surviving in the entry it was found in,
#: because the only `meta.pagination` test exercised `observed_pagination` at
#: unit level and never reached the f-string that builds the entry.
PAGINATION_LOCATIONS = [
    pytest.param(
        {"data": [{"id": 1}], "pagination": {"current_page": 1, "has_more": False}},
        "envelope.pagination{current_page,has_more}",
        "pagination at: pagination",
        id="top-level",
    ),
    pytest.param(
        {"data": [{"id": 1}], "meta": {"pagination": {"current_page": 1, "has_more": False}}},
        "envelope.meta.pagination{current_page,has_more}",
        "pagination at: meta.pagination",
        id="under-meta",
    ),
]


@pytest.mark.parametrize("body,expected_shape,expected_evidence", PAGINATION_LOCATIONS)
def test_the_pagination_entry_names_the_location_the_response_actually_used(
    tmp_path, body, expected_shape, expected_evidence,
):
    _, payload = _run_with_transport(tmp_path, [response(body)])
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["pagination"] == expected_shape
    assert expected_evidence in payload["objectives"][0]["evidence"]


def test_the_pagination_location_cases_are_pairwise_distinguishing():
    expected = [case.values[1] for case in PAGINATION_LOCATIONS]
    assert len(set(expected)) == len(expected) >= 2


def test_an_empty_pagination_block_is_recorded_not_treated_as_absent(tmp_path):
    """Present-but-empty and absent are different observations. Truthiness
    conflated them."""
    code, payload = _run_with_transport(tmp_path, [
        response({"data": [{"id": 1}], "pagination": {}}),
    ])
    objective = payload["objectives"][0]
    assert code == EXIT_UNMET and objective["status"] == DEGRADED
    assert "present but carried no field names" in objective["evidence"]
    assert "no pagination metadata on any response" not in objective["evidence"]
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert shapes["pagination"] == "envelope.pagination{}"


def test_observed_pagination_distinguishes_absent_from_empty():
    assert observed_pagination([Exchange(200, {}, {"data": {}})]) == (None, ())
    assert observed_pagination([Exchange(200, {}, {"data": {}, "pagination": {}})]) == ("pagination", ())


def test_render_skeleton_shows_names_only():
    assert render_skeleton({"data": {}, "pagination": {"current_page": {}, "has_more": {}}}) == (
        "data, pagination{current_page,has_more}"
    )


def test_render_skeleton_does_not_truncate_below_the_second_level():
    """`body_skeleton` captures three levels; rendering only two loses the field
    names under `meta.pagination` -- the location the client explicitly supports
    (`models.py:73`) and the one a rejected-envelope entry most needs to show."""
    skeleton = _trial_common.body_skeleton(
        {"data": [], "meta": {"pagination": {"current_page": 1, "has_more": True}}}
    )
    assert render_skeleton(skeleton) == "data, meta{pagination{current_page,has_more}}"


def test_pagination_shape_names_only_the_fields_present():
    """`next_page` is optional. The shape must not name a field the response
    did not carry."""
    exchanges = [Exchange(200, {}, {"data": {}, "pagination": {"current_page": {}, "has_more": {}}})]
    assert observed_pagination(exchanges) == ("pagination", ("current_page", "has_more"))


def test_pagination_shape_reports_the_meta_location_when_that_is_where_it_is():
    exchanges = [Exchange(200, {}, {"meta": {"pagination": {"current_page": {}}}})]
    assert observed_pagination(exchanges) == ("meta.pagination", ("current_page",))


def test_body_skeleton_carries_key_names_only_never_values():
    """Reports must not carry raw provider data. The skeleton is names only."""
    skeleton = _trial_common.body_skeleton({"data": [{"id": 1}], "meta": {"pagination": {"current_page": 3}}})
    assert skeleton == {"data": {}, "meta": {"pagination": {"current_page": {}}}}
    assert "3" not in json.dumps(skeleton)


def test_a_throttle_without_retry_after_is_still_counted(tmp_path):
    """Conflating "throttled" with "throttled and carried the header" reports a
    real 429 as zero throttles -- a misobservation inside objective 17's own
    subject matter, previously exiting 0."""
    code, payload = _run(tmp_path, retry_after=False)
    evidence = payload["objectives"][0]["evidence"]
    assert "throttled responses: 1 (with Retry-After: 0)" in evidence
    assert "carried no Retry-After" in evidence
    assert payload["objectives"][0]["status"] == DEGRADED
    assert code == EXIT_UNMET
    assert not [s for s in payload["observed_shapes"] if s["name"] == "retry_after"]


def test_synthetic_retry_after_is_observed_and_reported(tmp_path):
    """S2 DoD 5: a synthetic 429 carrying Retry-After, exercised and reported."""
    _, payload = _run(tmp_path)
    shapes = {s["name"]: s["shape"] for s in payload["observed_shapes"]}
    assert "retry_after" in shapes
    assert "HTTP 429 retry-after=2" in shapes["retry_after"]
    assert "throttled responses: 1" in payload["objectives"][0]["evidence"]


def test_removing_the_throttle_drops_the_retry_shape_and_warns(tmp_path):
    _, payload = _run(tmp_path, throttle=False)
    assert not [s for s in payload["observed_shapes"] if s["name"] == "retry_after"]
    assert any("retry pacing is unmeasured" in w for w in payload["warnings"])
    assert "throttled responses: 0" in payload["objectives"][0]["evidence"]


#: The three `missing` messages that interpolate a value, and two inputs each
#: producing a different one. Item 11 applies to "every `evidence` string", and
#: these three sub-fields were asserted only by containment, so each accepted a
#: literal: the parser-rejection detail, the empty-block location, and the
#: unpaired-throttle count.
INTERPOLATED_MISSING_MESSAGES = [
    pytest.param(
        [response({"data": [{"id": 1}], "pagination": {"current_page": 1, "has_more": "yes"}})],
        "payload rejected by the parser: pagination has_more must be boolean endpoint=leagues",
        id="rejection-detail-has-more",
    ),
    pytest.param(
        [response({"data": "not-a-list"})],
        "payload rejected by the parser: malformed response envelope endpoint=leagues",
        id="rejection-detail-envelope",
    ),
    pytest.param(
        [response({"data": [{"id": 1}], "pagination": {}})],
        "pagination block present but carried no field names",
        id="empty-block-top-level",
    ),
    pytest.param(
        [response({"data": [{"id": 1}], "meta": {"pagination": {}}})],
        "meta.pagination block present but carried no field names",
        id="empty-block-under-meta",
    ),
]


@pytest.mark.parametrize("served,expected_message", INTERPOLATED_MISSING_MESSAGES)
def test_each_interpolated_missing_message_carries_the_value_that_produced_it(
    tmp_path, served, expected_message,
):
    _, payload = _run_with_transport(tmp_path, served)
    evidence = payload["objectives"][0]["evidence"]
    detail = evidence.split(" — ")[1]
    assert expected_message in detail.split("; ")


def test_the_interpolated_missing_message_cases_are_pairwise_distinguishing():
    """Within each pair, the two inputs must differ — a literal satisfying both
    members of a pair is exactly what containment allowed."""
    expected = [case.values[1] for case in INTERPOLATED_MISSING_MESSAGES]
    assert len(set(expected)) == len(expected) >= 2


@pytest.mark.parametrize("throttles,expected", [(1, "1 throttled response(s) carried no Retry-After"),
                                                (3, "3 throttled response(s) carried no Retry-After")])
def test_the_unpaired_throttle_count_is_derived(tmp_path, throttles, expected):
    _, payload = _run(tmp_path, throttle=throttles, retry_after=False)
    detail = payload["objectives"][0]["evidence"].split(" — ")[1]
    assert expected in detail.split("; ")


# --- The failure-path reports -------------------------------------------------

def test_the_two_unmet_reasons_are_not_interchangeable(tmp_path, monkeypatch):
    """Swapping the config-absent and auth-rejected report bodies was undetected:
    both tests asserted only stdout and the exit code, never the evidence the
    report carries. The reason string is `evidence` content on two
    distinguishable inputs, so item 11 applies to it."""
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    trial_auth.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path / "cfg")])
    config = json.loads((tmp_path / "cfg" / "reports" / "trial_auth.json").read_text(encoding="utf-8"))

    token = "DUMMY-TRIAL-TOKEN"
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", token)
    monkeypatch.setattr(
        trial_auth, "make_client",
        lambda mode, **kw: _trial_common.make_client(
            mode, transport=ReplayTransport([response({}, status=401)]),
            config=SportmonksConfig(api_token=token), out_dir=kw.get("out_dir"),
        ),
    )
    trial_auth.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path / "auth")])
    auth = json.loads((tmp_path / "auth" / "reports" / "trial_auth.json").read_text(encoding="utf-8"))

    assert config["objectives"][0]["evidence"] == "configuration incomplete; no request was issued"
    assert auth["objectives"][0]["evidence"] == "authentication rejected by the provider"
    assert config["objectives"][0]["evidence"] != auth["objectives"][0]["evidence"]


# --- The item 10 / item 11 declaration ----------------------------------------

def test_every_entry_is_declared_and_names_a_test_that_exists(tmp_path):
    """The machine check standing DoD items 10 and 11 require.

    Set equality against the names actually emitted, because a declaration that
    drifts from the code is the defect the clause exists to prevent — it has
    already happened once in this phase, naming two identifiers present nowhere
    in the repository. Resolving each named test closes the same gap on the
    other side.
    """
    emitted = set()
    for kwargs in ({}, {"rate_limit_headers": False}, {"throttle": False}, {"pagination": False}):
        _, payload = _run(tmp_path, **kwargs) if kwargs else _run(tmp_path)
        emitted |= {s["name"] for s in payload["observed_shapes"]}
    _, rejected = _run_with_transport(tmp_path, [
        response({"data": [{"id": 1}], "pagination": {"current_page": 1, "has_more": "yes"}}),
    ])
    emitted |= {s["name"] for s in rejected["observed_shapes"]}

    assert set(trial_auth.DECLARED_SHAPES) == emitted

    module = sys.modules[__name__]
    for entry, named_tests in trial_auth.DECLARED_SHAPES.items():
        assert named_tests, f"{entry} declares no test"
        for name in named_tests:
            assert hasattr(module, name), f"{entry} names a test that does not exist: {name}"


# --- The degraded-provider branch ---------------------------------------------

#: Two provider failures that are neither configuration nor authentication, and
#: the exact reason each must produce. This branch is S2's third correction --
#: "only Config and Auth map to exit 3; every other provider failure is a
#: degraded observation" -- and until now **no test reached it**: replacing
#: `_degraded_report`'s whole body with `raise AssertionError` left all 111
#: green. Its status and its evidence were both unfalsifiable, which is the
#: defect that correction was itself written to fix.
PROVIDER_FAILURES = [
    pytest.param(
        [
            response({"data": [{"id": 1}], "pagination": {"current_page": 1, "has_more": True, "next_page": 2}}),
            response({"data": [{"id": 2}], "pagination": {"current_page": 1, "has_more": True, "next_page": 2}}),
        ],
        "provider error: SportmonksPaginationError",
        id="pagination-repeats-a-page",
    ),
    pytest.param(
        [SportmonksRateLimitError("rate limited")],
        "provider error: SportmonksRateLimitError",
        id="rate-limit-exhausted",
    ),
]


@pytest.mark.parametrize("served,expected_reason", PROVIDER_FAILURES)
def test_a_non_auth_provider_failure_degrades_rather_than_exiting_three(
    tmp_path, capsys, served, expected_reason,
):
    code, payload = _run_with_transport(tmp_path, served)
    objective = payload["objectives"][0]
    assert code == EXIT_UNMET, "a provider fault is not a configuration failure"
    assert code != EXIT_CONFIG
    assert objective["status"] == DEGRADED
    assert objective["evidence"] == expected_reason
    assert capsys.readouterr().out.startswith(f"PROVIDER: {expected_reason.split(': ')[1]}")


def test_the_provider_failure_cases_are_pairwise_distinguishing():
    expected = [case.values[1] for case in PROVIDER_FAILURES]
    assert len(set(expected)) == len(expected) >= 2


# --- The frozen report schema -------------------------------------------------

def test_report_schema_keys_are_exactly_the_frozen_set(tmp_path):
    trial_auth.main(["--out", str(tmp_path)])
    payload = json.loads((tmp_path / "reports" / "trial_auth.json").read_text(encoding="utf-8"))
    assert list(payload) == ["script", "mode", "objectives", "observed_shapes", "warnings"]
    assert list(payload["objectives"][0]) == ["id", "title", "status", "evidence"]
    assert list(payload["observed_shapes"][0]) == ["name", "shape"]


def test_status_enum_is_exactly_four_and_excludes_not_started():
    assert STATUSES == ("observed", "unmet", "degraded", "not_applicable")
    assert "not_started" not in STATUSES


def test_objective_rejects_a_status_outside_the_frozen_four():
    with pytest.raises(ValueError, match="frozen four"):
        Objective(1, "x", "not_started")


def test_exit_code_mapping_is_the_frozen_one():
    ok = TrialReport("t", MODE_MOCK, [Objective(1, "a", OBSERVED)])
    assert ok.exit_code() == EXIT_OK
    skipped = TrialReport("t", MODE_MOCK, [Objective(1, "a", NOT_APPLICABLE)])
    assert skipped.exit_code() == EXIT_OK, "not_applicable is not a failure"
    for failing in ("unmet", "degraded"):
        assert TrialReport("t", MODE_MOCK, [Objective(1, "a", failing)]).exit_code() == EXIT_UNMET


# --- Artifact locations -------------------------------------------------------

def test_out_defaults_to_the_gitignored_trial_output_directory():
    assert build_parser("t").parse_args([]).out == DEFAULT_OUT
    assert DEFAULT_OUT.name == "trial-output"


#: These tests shell out to git. Outside a checkout -- inside the backend image,
#: for instance -- that is a missing precondition, not a failure of the slice.
requires_git = pytest.mark.skipif(
    not (REPO_ROOT / ".git").exists(), reason="not a git checkout"
)


def _git_ls_files(pathspec: str) -> list[str]:
    return subprocess.run(
        ["git", "ls-files", pathspec],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()


def _git_ignored_entries(pathspec: str) -> list[str]:
    """Paths git reports as **ignored** -- the `!!` rows of `status --ignored`,
    not the `??` untracked ones.

    Deliberately not `git check-ignore`. That command answers this question with
    an exit code and a `<file>:<line>` citation, and a citation is only as good
    as the ref the working tree happens to be on: read against a branch
    predating the rule, it reports a line number that means something else
    entirely. `status --ignored` distinguishes the two outcomes as different
    tokens, so ignored and merely-untracked cannot be confused.
    """
    rows = subprocess.run(
        ["git", "status", "--porcelain", "--ignored", pathspec],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    return [row[3:] for row in rows if row.startswith("!! ")]


@requires_git
def test_trial_output_is_gitignored_after_a_run_that_wrote_there():
    """Two assertions that do not imply each other, and both are load-bearing.

    The **property**: nothing under `trial-output/` is tracked. This is what
    fails if payloads are ever committed for a reason having nothing to do with
    the ignore rule, and it is the one that matters most.

    The **mechanism**: the ignore rule is what keeps them untracked. The
    property assertion passes unchanged with the rule deleted, because nothing
    was ever `git add`ed either way -- its subject can be absent without its
    result changing, which means on its own it does not test the rule at all.
    Delete the `.gitignore` line and only the second assertion fails.
    """
    assert trial_auth.main([]) == EXIT_OK
    assert (DEFAULT_OUT / "reports" / "trial_auth.json").exists()

    tracked = _git_ls_files("packages/sportmonks-client/trial-output/")
    assert tracked == [], f"trial-output/ must never be tracked; found: {tracked}"

    ignored = _git_ignored_entries("packages/sportmonks-client/")
    assert any("trial-output" in entry for entry in ignored), (
        "trial-output/ is untracked but not *ignored* -- the .gitignore rule is "
        f"missing, so one `git add -A` tracks raw payloads. Ignored here: {ignored}"
    )


def _git_ignore_pattern_for(path: str) -> str | None:
    """The `.gitignore` **pattern** that would ignore `path`, or None.

    `--no-index` so the answer does not depend on the path existing: the first
    version of this check asked `git status --ignored`, which lists only paths
    present on disk, so it passed locally and failed on CI where the
    directories are absent. It was asserting ambient state, not a rule.

    This uses `git check-ignore` but reads only the **pattern** field, never
    the `<file>:<line>` citation. The citation is what misleads — read against
    a branch predating a rule it will cite a line number that means something
    else, and a broad unrelated pattern will answer "ignored" for a reason
    nobody intended. The pattern says *which* rule matched, which is the
    question worth asking.
    """
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-v", path],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    _source, _line, rest = result.stdout.strip().split(":", 2)
    return rest.split("\t")[0]


@requires_git
@pytest.mark.parametrize("path,expected_pattern", [
    ("downloaded_files/x", "downloaded_files/"),
    (".claude/worktrees/x", ".claude/worktrees/"),
    ("packages/sportmonks-client/trial-output/raw/x.json",
     "packages/sportmonks-client/trial-output/"),
])
def test_each_ignore_rule_is_present_and_is_the_one_that_matches(path, expected_pattern):
    """Asserted at all because the runtime-artifact rule shipped alongside the
    `trial-output/` one and was proven only by *observing* `!!` in a tree where
    the directory happened to exist. Deleting the line left the suite green.

    Asserting the matched pattern rather than mere ignored-ness also catches the
    case where some unrelated broad rule is doing the work — a rule that is
    effective today for a reason that has nothing to do with the rule we wrote.
    """
    assert _git_ignore_pattern_for(path) == expected_pattern


@requires_git
def test_no_raw_snapshot_payload_is_tracked_anywhere():
    tracked = _git_ls_files("packages/sportmonks-client/")
    assert not [p for p in tracked if "/raw/" in p or "trial-output" in p]


def test_raw_snapshots_land_under_trial_output(tmp_path):
    trial_auth.main(["--out", str(tmp_path)])
    snapshots = list((tmp_path / "raw").glob("*.json"))
    assert snapshots, "the snapshot hook must write raw payloads"
    assert "leagues" in snapshots[0].name


# --- Byte-stability -----------------------------------------------------------

def test_mock_output_is_byte_stable_across_runs(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    trial_auth.main(["--out", str(first)])
    trial_auth.main(["--out", str(second)])
    for name in ("trial_auth.json", "trial_auth.md"):
        assert (first / "reports" / name).read_bytes() == (second / "reports" / name).read_bytes()


def test_committed_example_matches_a_fresh_mock_run(tmp_path):
    """The committed example is evidence only while it matches. If this fails,
    regenerate it in the same change that altered the schema.

    Compared as **bytes**. `read_text` applies universal-newline translation on
    both platforms, so the previous version asserted text-identity while every
    report of this check — including several PR descriptions — claimed
    byte-identity. The two happen to coincide here (`core.autocrlf` gives the
    working tree the platform's convention, and `write_text` generates the
    same), but a drift confined to line endings would have passed while the
    claim about it was false. Assert the property that is being claimed.
    """
    trial_auth.main(["--out", str(tmp_path)])
    for name in ("trial_auth.json", "trial_auth.md"):
        fresh = (tmp_path / "reports" / name).read_bytes()
        committed = (EXAMPLES_DIR / name).read_bytes()
        assert fresh == committed, f"{name} drifted from trial-reports/examples/"


def test_every_report_path_carries_the_same_objective_title(tmp_path, monkeypatch):
    """Deliberate coverage for the two sites the probe marks exempt.

    Those sites are currently killed by a *side effect*: seeding a title to a
    literal turns the argument into an `ast.Constant`, enumeration correctly
    skips constants, the exempt-site count drops from 2 to 1, and the pin
    fails. Pleasing, but coupled to two unrelated behaviours — change either
    and the coverage vanishes with nothing failing to announce it. An escape
    valve protected by an accident is not protected.

    The property that actually matters: objective 17 is one objective, so every
    path reporting it names it identically. A literal at either site breaks
    that the moment it differs from the constant.
    """
    _, observed = _run(tmp_path / "ok")
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    trial_auth.main(["--live", "--i-understand-this-is-live", "--out", str(tmp_path / "cfg")])
    failed = json.loads(
        (tmp_path / "cfg" / "reports" / "trial_auth.json").read_text(encoding="utf-8")
    )
    titles = {observed["objectives"][0]["title"], failed["objectives"][0]["title"]}
    assert titles == {trial_auth.OBJECTIVE_17}, (
        f"objective 17 is reported under more than one name: {titles}"
    )


def test_report_carries_no_timestamp_field(tmp_path):
    """Byte-stability is structural, not conventional: the frozen schema has no
    time field, so nothing needs freezing at render time."""
    trial_auth.main(["--out", str(tmp_path)])
    text = (tmp_path / "reports" / "trial_auth.json").read_text(encoding="utf-8")
    assert "generated_at" not in text and "timestamp" not in text
    assert "T00:00:00" not in render_markdown(TrialReport("t", MODE_MOCK))


# --- Harness plumbing ---------------------------------------------------------

def test_write_report_emits_both_artifacts(tmp_path):
    report = TrialReport("demo", MODE_MOCK, [Objective(1, "a", OBSERVED, "e")])
    json_path, md_path = write_report(report, tmp_path)
    assert json_path.name == "demo.json" and md_path.name == "demo.md"
    assert "| 1 | a | `observed` | e |" in md_path.read_text(encoding="utf-8")


def test_mock_mode_requires_an_injected_transport():
    with pytest.raises(ValueError, match="requires an injected transport"):
        make_client(MODE_MOCK)


def test_report_mode_comes_from_the_resolved_mode_not_a_proxy():
    """`mode` was previously derived from `transport is not None`, which labels a
    live run with an injected transport as `mock`. Same species as the literal
    evidence: inferring a fact from a proxy rather than reading it."""
    client = make_client(MODE_LIVE, transport=ReplayTransport(
        [response({"data": [], "meta": {"pagination": {"current_page": 1, "has_more": False}}})]
    ), config=SportmonksConfig(api_token="X"))
    assert trial_auth.collect(client, "live").mode == "live"


def test_observation_helpers_read_only_sanctioned_headers():
    exchanges = [Exchange(200, {"x-ratelimit-limit": "3000", "content-type": "application/json"})]
    assert observed_rate_limit_fields(exchanges) == ("x-ratelimit-limit",)
    assert observed_retry_after(exchanges) == ()
    assert observed_rate_limit_fields([Exchange(200, {})]) == ()


def test_observing_transport_drops_unsanctioned_headers():
    """Reports must never carry arbitrary provider headers -- the allowlist is
    the client's existing one, reused rather than redefined."""
    inner = ReplayTransport([response({"data": []}, headers={
        "X-RateLimit-Limit": "10", "Set-Cookie": "session=secret", "Authorization": "Bearer x",
    })])
    observer = ObservingTransport(inner)
    observer.request("GET", "https://host", params={}, timeout=1)
    assert dict(observer.exchanges[0].headers) == {"x-ratelimit-limit": "10"}
