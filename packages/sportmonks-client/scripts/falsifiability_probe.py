"""Seed reported values with literals and report which ones nothing notices.

Standing DoD items 10 and 11 say every reported value must be derived from the
response actually received, and that the proof is a two-input equality test.
This is the instrument that checks it, because in this phase the rule never
once caught the defect and the experiment always did: S2 four times, S3, S5,
and the exemplar fix twice. Reading found none of them.

The specific failure this closes is **enumeration**, not rigor. A hand-listed
probe reported 0 survivors of 11 sites while 12 sites it never listed went
unswept, one of which still held a literal — the pagination entry's location,
the exact defect S2 had been rejected for twice. A probe built from the
author's site list inherits the author's sweep, so `--sites auto` derives the
list from the syntax tree instead.

Its own failure mode is silent false confidence: a broken probe does not go
red, it reports a clean sweep. Four instrumentation bugs were measured while
running this by hand, and every one would have read as a pass. Each is a
refusal here, and each is pinned by `tests/test_falsifiability_probe.py`,
which was written first:

- a seed that does not match the bytes on disk aborts (never silently sweeps an
  unmodified tree);
- a run reporting *errors* is scored `INVALID`, never a kill — a test that
  errors cannot falsify anything;
- basetemp paths are sanitized and validated up front, on the platform actually
  running;
- restore is byte-scoped, verified, and aborts on mismatch. No `git` anywhere:
  a restore scoped to a *file* is wider than a restore scoped to a *change*.

Mechanical seeding is a floor, not a ceiling. It replaces a derived value with
a plausible literal; it will not invent the semantic seeds that caught
`{len(retry_afters)}` being satisfiable by `1 if retry_afters else 0`. Those
stay hand-written, and this makes sure the mechanical layer is never the part
that was skipped.
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, NamedTuple, Sequence

KILLED = "killed"
SURVIVED = "SURVIVED"
INVALID = "INVALID"

PACKAGE_ROOT = Path(__file__).resolve().parent.parent

#: Call names whose arguments end up in a report.
REPORTING_CALLS = ("ObservedShape", "Objective")

#: Which argument of each reporting call carries which kind of value.
ROLES = {
    ("Objective", 1): "title",
    ("Objective", 2): "status",
    ("Objective", 3): "evidence",
    ("ObservedShape", 0): "entry-name",
    ("ObservedShape", 1): "shape",
}

#: Roles standing DoD item 10 does not govern: *"Every objective's `status` and
#: `evidence`, and every `observed_shapes[]` entry"*. A title and an entry name
#: are identifiers, not observations, and a constant is the correct
#: implementation of both.
#:
#: Exempt sites are still enumerated, seeded, and printed with their verdict —
#: they simply do not fail the gate. They are never skipped, because silently
#: dropping sites from the list is the failure this whole instrument exists to
#: prevent, and an exemption that hides its subject is indistinguishable from
#: an enumeration gap.
EXEMPT_ROLES = frozenset({"title", "entry-name"})

#: What a seeded value is replaced with. Deliberately plausible-looking rather
#: than obviously wrong: an implausible token fails containment assertions that
#: a realistic literal would pass, which would under-report survivors.
LITERAL = '"probe-literal"'


class ProbeAbort(RuntimeError):
    """The probe cannot honestly score this run, so it refuses to score it."""


@dataclass(frozen=True)
class Seed:
    label: str
    path: Path
    old: bytes
    new: bytes


@dataclass(frozen=True)
class SuiteResult:
    summary: str
    failed: Sequence[str]


class _FileIO:
    """The only writer. Injectable so the tests can sabotage a restore."""

    def write_bytes(self, path: Path, data: bytes) -> None:
        path.write_bytes(data)

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()


def score(result: SuiteResult) -> str:
    """`errors` never counts as a kill.

    A run whose tests errored measured nothing, and scoring it by exit code
    reads twelve broken runs as twelve confirmations — which is what happened
    when `--basetemp`'s parent did not exist.
    """
    summary = result.summary.strip()
    if not summary or "error" in summary:
        return INVALID
    if "failed" in summary:
        return KILLED
    if "passed" in summary:
        return SURVIVED
    return INVALID


def sanitize_identifier(label: str) -> str:
    """A path segment that is valid on this platform, and still unique.

    A `--basetemp` containing `:` is silently invalid on Windows; every
    `tmp_path` test then errors, 39 at a time. Forbidden characters are encoded
    rather than dropped so two labels differing only in punctuation cannot
    collide into one directory.
    """
    encoded = "".join(ch if (ch.isalnum() or ch in "._-") else f"_{ord(ch)}_" for ch in label)
    return encoded[:120] or "site"


def validate_basetemp_root(root: Path) -> Path:
    """Checked once, up front, rather than discovered mid-sweep."""
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".probe-write-check"
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        raise ProbeAbort(f"{root} is not a usable basetemp root: {exc}") from None
    return root


def apply_seed(path: Path, old: bytes, new: bytes, io: _FileIO | None = None) -> bytes:
    """Replace `old` with `new`, returning the held original bytes.

    Matches against the bytes actually on disk. The seed that silently failed
    was written with `\\n` against a file stored `\\r\\n`; a probe that treats a
    miss as "nothing to do" then runs the whole suite on an unmodified tree and
    reports no survivors.
    """
    io = io or _FileIO()
    held = io.read_bytes(path)
    if old == new:
        raise ProbeAbort(f"seed for {path.name} changes nothing")
    count = held.count(old)
    if count == 0:
        raise ProbeAbort(f"seed did not match anything in {path.name}: {old[:60]!r}")
    if count != 1:
        raise ProbeAbort(f"seed matches {path.name} {count} times; cannot attribute a verdict")
    io.write_bytes(path, held.replace(old, new))
    return held


def restore(path: Path, held: bytes, io: _FileIO | None = None) -> None:
    """Write the held bytes back and verify them.

    Never `git checkout`/`stash`/`restore`: those operate on the whole file and
    will discard unrelated edits made since. Verification turns a silent
    corruption into a hard stop, because every later verdict in the sweep would
    otherwise be measured against a tree the probe no longer understands.
    """
    io = io or _FileIO()
    io.write_bytes(path, held)
    if io.read_bytes(path) != held:
        raise ProbeAbort(f"restore did not reproduce {path.name} byte for byte; stopping")


#: Executed in a child interpreter to answer "is the seeded code what actually
#: loads?". Deliberately inspects the **code object**, not the source text:
#: `inspect.getsource` re-reads the `.py` and would report the seed even while
#: stale bytecode executes, which is the exact failure it must detect.
_SEED_REACHED_CHILD = chr(10).join([
    "import importlib.util, sys",
    "spec = importlib.util.spec_from_file_location('_probe_target', sys.argv[1])",
    "code = spec.loader.get_code('_probe_target')",
    "seen = set()",
    "def walk(c):",
    "    for k in c.co_consts:",
    "        if isinstance(k, str): seen.add(k)",
    "        elif hasattr(k, 'co_consts'): walk(k)",
    "walk(code)",
    "print('FOUND' if sys.argv[2] in seen else 'MISSING')",
])


def seed_literal(old: bytes, new: bytes) -> str | None:
    """The string literal a seed introduces, if it introduces one."""
    for match in re.finditer(rb'"([^"]+)"', new):
        value = match.group(1)
        if value not in old:
            return value.decode("utf-8", "replace")
    return None


def require_seed_reaches_the_child(path: Path, old: bytes, new: bytes) -> None:
    """Assert the seeded code is what the child interpreter actually loads.

    `apply_seed` proves the **bytes on disk changed** -- a property. This proves
    the **seeded code executes** -- the mechanism. They came apart in practice:
    a stale `.pyc` produced a fully green suite with the seed genuinely written,
    3 times in 20 CI runs, reported as a survivor.

    `PYTHONDONTWRITEBYTECODE=1` fixes that one cause. This detects the class:
    a module already in `sys.modules`, an installed copy shadowing the tree, an
    editable install resolving elsewhere, and causes nobody has thought of yet.
    The fix addresses a mechanism; the detector outlives it.
    """
    needle = seed_literal(old, new)
    if needle is None:
        return  # nothing quoted to look for; the suite result stands on its own
    result = subprocess.run(
        [sys.executable, "-c", _SEED_REACHED_CHILD, str(path), needle],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.stdout.strip() != "FOUND":
        raise ProbeAbort(
            f"the seed for {path.name} is on disk but the child interpreter does not "
            f"load it (looked for {needle!r}; got {result.stdout.strip() or result.stderr.strip()!r}). "
            "A verdict measured against unseeded code is not a verdict."
        )


class SeedOutcome(NamedTuple):
    """A verdict and the suite summary it was scored from.

    The summary is not decoration. A bare verdict cannot be diagnosed: a
    `SURVIVED` that is genuine and a `KILLED` produced by an unrelated flaky
    test look identical in the output, and telling them apart afterwards means
    re-running the whole sweep. Carrying the line the verdict was read from
    makes each row self-diagnosing.
    """

    verdict: str
    summary: str
    failed: tuple[str, ...] = ()


def run_seed(
    seed: Seed,
    runner: Callable[[Path], SuiteResult],
    basetemp_root: Path,
    io: _FileIO | None = None,
) -> SeedOutcome:
    io = io or _FileIO()
    held = apply_seed(seed.path, seed.old, seed.new, io=io)
    try:
        # EXPERIMENT ARM (#101): detector disabled, env var still set.
        # One variable changed, to tell timing from detection.
        pass  # require_seed_reaches_the_child(seed.path, seed.old, seed.new)
        basetemp = basetemp_root / sanitize_identifier(seed.label)
        basetemp.mkdir(parents=True, exist_ok=True)
        result = runner(basetemp)
    finally:
        restore(seed.path, held, io=io)
    verdict = score(result)
    if verdict == INVALID:
        raise ProbeAbort(
            f"the run for {seed.label!r} measured nothing (summary: {result.summary!r}). "
            "A test that errors cannot falsify anything."
        )
    return SeedOutcome(verdict, result.summary, tuple(result.failed))


def require_positive_control(positive: Seed | None) -> Seed:
    if positive is None:
        raise ProbeAbort(
            "a sweep needs a positive control: a known-bad edit that must be killed. "
            "Without one, a clean sweep cannot be distinguished from a probe that "
            "never modified anything."
        )
    return positive


def check_controls(
    target: Path,
    runner: Callable[[Path], SuiteResult],
    basetemp_root: Path,
    io: _FileIO | None = None,
    *,
    positive: Seed | None,
) -> None:
    """Both controls, before any verdict is believed.

    The negative control is what exposed the errored-run bug: a no-op edit came
    back "killed", which is only possible if the probe is measuring the harness
    rather than the seed.
    """
    io = io or _FileIO()
    held = io.read_bytes(target)
    noop = Seed("negative-control", target, held, held + b"\r\n# probe no-op\r\n")
    if run_seed(noop, runner, basetemp_root, io=io).verdict != SURVIVED:
        raise ProbeAbort(
            "negative control was killed: a no-op edit changed the result, so this "
            "sweep is measuring the harness, not the seeds. Every verdict is void."
        )
    control = require_positive_control(positive)
    if run_seed(control, runner, basetemp_root, io=io).verdict != KILLED:
        raise ProbeAbort(
            f"positive control {control.label!r} survived: a known-bad edit went "
            "unnoticed, so a clean sweep proves nothing."
        )


def _line_starts(source: bytes) -> list[int]:
    offsets, position = [0], 0
    for line in source.splitlines(keepends=True):
        position += len(line)
        offsets.append(position)
    return offsets


def _span(source: bytes, node: ast.AST) -> tuple[int, int]:
    """A node's byte span. `col_offset` is a UTF-8 byte offset, so this is exact
    even on the lines carrying an em dash."""
    starts = _line_starts(source)
    return (starts[node.lineno - 1] + node.col_offset,
            starts[node.end_lineno - 1] + node.end_col_offset)


def _segment(source: bytes, node: ast.AST) -> bytes:
    start, end = _span(source, node)
    return source[start:end]


def _unique_seed(source: bytes, start: int, end: int, replacement: bytes) -> tuple[bytes, bytes] | None:
    """Grow a window around the span until it occurs exactly once.

    Seeding by expression *text* silently drops every site whose text repeats:
    `status`, `reason`, and `{page_location}` each appear several times in the
    exemplar, so a text-keyed probe skipped them — including the `_report_with`
    sites, which is where the branch reached by no test at all lived. That is
    the enumeration gap reproduced inside the instrument built to close it.
    The window keeps `apply_seed`'s single-match guarantee as a real check
    rather than a filter that quietly discards work.
    """
    low, high = start, end
    while True:
        window = source[low:high]
        if source.count(window) == 1:
            return window, source[low:start] + replacement + source[end:high]
        if low == 0 and high == len(source):
            return None
        low, high = max(0, low - 24), min(len(source), high + 24)


def _is_derived(node: ast.AST) -> bool:
    """A constant argument has nothing to falsify — a literal replacing a
    literal is not a measurement."""
    return not isinstance(node, ast.Constant)


def enumerate_construction_sites(path: Path) -> list[Seed]:
    """Every reported value in the file, from the syntax tree rather than a list.

    Each `ObservedShape(...)`/`Objective(...)` argument that is not already a
    constant becomes a seed, and each interpolation inside an f-string argument
    becomes its own seed — the measured defects were sub-fields of an evidence
    string, not whole strings.
    """
    source = path.read_bytes()
    tree = ast.parse(source.decode("utf-8"))
    seeds: list[Seed] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id not in REPORTING_CALLS:
            continue
        for index, arg in enumerate(node.args):
            if not _is_derived(arg):
                continue
            role = ROLES.get((node.func.id, index), "whole")
            # The entry name, when the call carries one as a constant, so a
            # survivor reads as `rejected_envelope` rather than `arg1`.
            named = next((a.value for a in node.args
                          if isinstance(a, ast.Constant) and isinstance(a.value, str)), None)
            where = f"{node.func.id}:{path.name}:{arg.lineno}:arg{index}"
            if named:
                where += f"[{named}]"

            values = arg.values if isinstance(arg, ast.JoinedStr) else []
            for position, part in enumerate(values):
                if not isinstance(part, ast.FormattedValue):
                    continue
                start, end = _span(source, part)
                made = _unique_seed(source, start, end, b"probe")
                if made:
                    # `position` keeps two interpolations on one line distinct;
                    # duplicate labels would collide into one basetemp directory.
                    seeds.append(Seed(f"{where}:component{position}@{part.lineno}", path, *made))

            # A status must stay inside the frozen four, or `Objective` rejects
            # it by construction and the site "dies" for a reason unrelated to
            # whether anything asserts it.
            replacement = b'"observed"' if role == "status" else LITERAL.encode()
            start, end = _span(source, arg)
            made = _unique_seed(source, start, end, replacement)
            if made:
                seeds.append(Seed(f"{where}:{role}", path, *made))
    return seeds


def subject_deletion_seed(path: Path, text: str) -> Seed:
    """Delete the artifact a test claims to cover.

    A test whose assertion passes when its subject is deleted is not testing
    that subject. Measured on an ignore rule proven by *observing* its effect:
    deleting the line left the suite green.
    """
    line = text.encode()
    for terminator in (b"\r\n", b"\n"):
        candidate = line + terminator
        if path.read_bytes().count(candidate) == 1:
            return Seed(f"delete-subject:{path.name}:{text}", path, candidate, b"")
    return Seed(f"delete-subject:{path.name}:{text}", path, line, b"")


def is_exempt(label: str) -> bool:
    return any(label.endswith(f":{role}") for role in EXEMPT_ROLES)


def exit_code(verdicts: Sequence[str], labels: Sequence[str] = ()) -> int:
    """Non-zero on any in-scope survivor, and on an empty sweep — a probe that
    seeded nothing has certified nothing."""
    if not verdicts:
        return 2
    labels = labels or [""] * len(verdicts)
    return 1 if any(v != KILLED and not is_exempt(l)
                    for v, l in zip(verdicts, labels)) else 0


def pytest_runner(package_root: Path) -> Callable[[Path], SuiteResult]:
    def run(basetemp: Path) -> SuiteResult:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", f"--basetemp={basetemp}"],
            cwd=package_root, capture_output=True, text=True,
            # PYTHONDONTWRITEBYTECODE: a seed replaces a derived expression with
            # a literal of similar length, written milliseconds after the
            # original. CPython invalidates a cached .pyc on source mtime+size,
            # so a same-second write of similar size can hit a stale cache and
            # the seeded source never executes -- a fully green suite with the
            # seed genuinely on disk. Measured at 4 flips in 20 CI runs, in both
            # directions: a false survivor when the seeded module is stale, and
            # unrelated failures when a *previous* seed's module is still cached.
            env={**os.environ, "PYTHONIOENCODING": "utf-8",
                 "PYTHONDONTWRITEBYTECODE": "1"},
        )
        lines = completed.stdout.splitlines()
        summaries = [l for l in lines if re.search(r"\d+ (passed|failed|error)", l)]
        # Full node ids, not bare test names: the module matters. When a sweep
        # was invalidated by a concurrent edit, the tell was failures in a
        # module unrelated to the seeded file -- invisible if the path is cut.
        failed = [l[len("FAILED "):].split(" ")[0] for l in lines if l.startswith("FAILED")]
        return SuiteResult(summaries[-1] if summaries else "", failed)
    return run


#: Held for the duration of a sweep. A second probe starting while one is in
#: flight would seed a tree the first is mid-restore on, and neither run's
#: verdicts would be attributable to its own seeds.
LOCK_NAME = ".probe-in-flight"


class _SweepLock:
    """Refuse to start a second sweep in the same package tree.

    Measured, not anticipated: a background sweep and a foreground hand-seed
    ran against one checkout, and five tests from an unrelated module failed in
    the seeded run. Both results were void. The rule "one worktree per agent or
    serialize" was being actively restated by its author at the time — which is
    the cleanest available demonstration that a rule form does not hold, even
    for the person holding it. **An instrument that can be invalidated by a
    condition it does not check will be.**
    """

    def __init__(self, root: Path) -> None:
        self._path = root / LOCK_NAME

    def __enter__(self) -> "_SweepLock":
        try:
            # O_EXCL: the check and the claim are one operation, so two probes
            # starting together cannot both see "no lock" and proceed.
            handle = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise ProbeAbort(
                f"another sweep holds {self._path}. Two probes in one tree cannot "
                "attribute verdicts to their own seeds. Wait for it, or run in a "
                f"separate git worktree. If no sweep is running, delete {LOCK_NAME}."
            ) from None
        os.write(handle, str(os.getpid()).encode())
        os.close(handle)
        return self

    def __exit__(self, *_exc: object) -> None:
        self._path.unlink(missing_ok=True)


def require_clean_tree(package_root: Path, *, phase: str = "start") -> None:
    """Refuse to sweep a tree with uncommitted changes to tracked files.

    A sweep restores every seed it applies, verified byte for byte. It cannot
    restore an edit it did not make — so a crash mid-sweep on a dirty tree
    leaves the author unable to tell their own work from the probe's residue.
    Untracked files are permitted: a new slice's scripts are untracked by
    definition, and refusing them would make the probe unusable exactly when it
    is most needed.

    Called at **both ends** of a sweep. The start check is a t=0 check, and a
    t=0 check certifies nothing about a property that can change per seed: the
    lock stops a second *process*, but nothing stops a hand edit mid-sweep,
    which is materially what the incident was. A tree clean at the start and
    dirty at the finish means something moved underneath the run, and every
    verdict in between is unattributable — the same voiding rule as a negative
    control that survives at the start and dies at the end.
    """
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no", "--", str(package_root)],
        capture_output=True, text=True, cwd=package_root,
    )
    if result.returncode != 0:
        raise ProbeAbort(f"could not determine tree state: {result.stderr.strip()}")
    if result.stdout.strip():
        changed = ", ".join(line[3:] for line in result.stdout.splitlines()[:5])
        if phase == "start":
            raise ProbeAbort(
                f"tracked files have uncommitted changes ({changed}). A sweep restores "
                "only what it seeded; it cannot tell your edits from its own residue "
                "if it stops midway. Commit or stash first."
            )
        raise ProbeAbort(
            f"the tree is dirty at the end of the sweep ({changed}), and it was clean "
            "at the start. Something changed underneath the run, so no verdict above "
            "is attributable to its own seed. THIS SWEEP IS VOID."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", action="append", default=[], type=Path,
                        help="source file to enumerate construction sites in")
    parser.add_argument("--sites", choices=["auto"], default="auto")
    parser.add_argument("--subject", action="append", default=[], metavar="FILE::TEXT",
                        help="delete TEXT from FILE and require a test to notice")
    parser.add_argument("--positive-control", metavar="FILE::OLD::NEW", required=True,
                        help="a known-bad edit that MUST be killed")
    parser.add_argument("--basetemp-root", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        require_clean_tree(PACKAGE_ROOT)
        root = validate_basetemp_root(args.basetemp_root)
        runner = pytest_runner(PACKAGE_ROOT)

        pc_file, pc_old, pc_new = args.positive_control.split("::", 2)
        positive = Seed("positive-control", Path(pc_file), pc_old.encode(), pc_new.encode())
        check_controls(Path(pc_file), runner, root, positive=positive)

        seeds: list[Seed] = []
        for source in args.file:
            seeds += enumerate_construction_sites(source)
        for spec in args.subject:
            path, _, text = spec.partition("::")
            seeds.append(subject_deletion_seed(Path(path), text))

        verdicts, labels, survivors, exempt = [], [], [], []
        for seed in seeds:
            outcome = run_seed(seed, runner, root)
            verdict = outcome.verdict
            verdicts.append(verdict)
            labels.append(seed.label)
            if verdict != KILLED:
                (exempt if is_exempt(seed.label) else survivors).append(seed.label)
            marker = " (exempt)" if is_exempt(seed.label) else ""
            # The node ids are the diagnostic half. Two seeds can share the
            # summary `1 failed, 258 passed` and mean opposite things: killed by
            # the test that targets the site, or killed by an unrelated flaky
            # test. Counts cannot tell those apart; names can, and a flip then
            # reads itself off the log instead of needing a forensic diff.
            names = ", ".join(outcome.failed[:3]) or "-"
            print(f"{verdict:9} {seed.label}{marker}  [{outcome.summary}] {names}")

        # Both ends of the window, same voiding rule.
        require_clean_tree(PACKAGE_ROOT, phase="end")
    except ProbeAbort as exc:
        print(f"ABORT: {exc}")
        return 3

    print(f"\n{len(verdicts) - len(survivors) - len(exempt)}/{len(verdicts)} killed")
    for label in survivors:
        print(f"  SURVIVOR {label}")
    for label in exempt:
        print(f"  exempt survivor (item 10 governs status/evidence/shapes only): {label}")
    return exit_code(verdicts, labels)


if __name__ == "__main__":
    raise SystemExit(main())
