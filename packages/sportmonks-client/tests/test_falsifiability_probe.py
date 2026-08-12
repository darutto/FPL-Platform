"""The probe's own suite, written before the probe.

A probe is the one tool here whose failure mode is *silent false confidence*:
when it breaks it does not go red, it reports a clean sweep. Four instrumentation
failures were measured while running this experiment by hand, and every one of
them would have been read as a passing result:

1. a seed whose search string never matched (LF written, CRLF on disk) — would
   have run the suite on an unmodified tree and reported no survivors;
2. a run where every `tmp_path` test *errored* rather than failed, because the
   `--basetemp` parent did not exist — twelve seeds scored as kills while
   measuring nothing;
3. a `--basetemp` path containing a colon, invalid on Windows — same shape,
   discovered 39 errors in;
4. a restore performed with `git checkout -- <file>`, which reverted unrelated
   edits in the same file along with the seed.

So each test below seeds the probe the way the probe seeds the suite, and
asserts it **aborts or refuses to score** rather than returning a number.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import falsifiability_probe as fp  # noqa: E402
from falsifiability_probe import (  # noqa: E402
    INVALID, KILLED, SURVIVED, ProbeAbort, Seed, SuiteResult,
)


def _runner(*summaries):
    """A fake pytest whose successive runs return the given summaries."""
    queue = list(summaries)

    def run(basetemp: Path) -> SuiteResult:
        assert basetemp.exists(), "the probe must create basetemp before running"
        return SuiteResult(queue.pop(0) if queue else summaries[-1], [])

    return run


# --- Scoring: the errored-run failure (measured twice) -------------------------

@pytest.mark.parametrize("summary,expected", [
    ("134 passed in 1.2s", SURVIVED),
    ("1 failed, 133 passed in 1.3s", KILLED),
    ("2 failed, 120 passed in 1.5s", KILLED),
    ("1 failed, 95 passed, 39 warnings, 39 errors in 3.9s", INVALID),
    ("93 passed, 29 errors in 2.1s", INVALID),
    ("", INVALID),
])
def test_a_run_that_errored_is_never_scored_as_a_kill(summary, expected):
    """The failure that produced twelve false kills. A non-zero exit is not a
    kill — a test that errors cannot falsify anything, so the only honest
    verdict is that the run measured nothing."""
    assert fp.score(SuiteResult(summary, [])) == expected


def test_an_errored_run_aborts_the_probe_rather_than_being_reported(tmp_path):
    target = tmp_path / "t.py"
    target.write_bytes(b"a\r\n")
    seed = Seed("s", target, b"a", b"b")
    with pytest.raises(ProbeAbort, match="measured nothing"):
        fp.run_seed(seed, _runner("93 passed, 29 errors in 2.1s"), tmp_path / "bt", _noop_io())


# --- Seed application: the CRLF failure ---------------------------------------

def test_a_seed_that_does_not_match_aborts_instead_of_reporting_a_clean_run(tmp_path):
    target = tmp_path / "t.py"
    target.write_bytes(b"value = derived()\r\n")
    with pytest.raises(ProbeAbort, match="did not match"):
        fp.apply_seed(target, b"value = derived()\n", b'value = "literal"\n')


def test_seed_sites_are_located_in_the_bytes_on_disk_not_an_assumed_line_ending(tmp_path):
    """CRLF is the platform default here. The dangerous variant is not the miss
    — that aborts — but a *partial* match that applies a malformed seed and
    scores a kill for a reason nobody intended."""
    target = tmp_path / "t.py"
    target.write_bytes(b"a = 1\r\nvalue = derived()\r\nb = 2\r\n")
    held = fp.apply_seed(target, b"value = derived()", b'value = "lit"')
    assert target.read_bytes() == b'a = 1\r\nvalue = "lit"\r\nb = 2\r\n'
    assert held == b"a = 1\r\nvalue = derived()\r\nb = 2\r\n"


def test_an_ambiguous_seed_aborts(tmp_path):
    """Two matches means the probe cannot say which site it measured."""
    target = tmp_path / "t.py"
    target.write_bytes(b"x = f()\r\nx = f()\r\n")
    with pytest.raises(ProbeAbort, match="2 times"):
        fp.apply_seed(target, b"x = f()", b"x = 1")


def test_a_seed_identical_to_the_original_aborts(tmp_path):
    target = tmp_path / "t.py"
    target.write_bytes(b"x = f()\r\n")
    with pytest.raises(ProbeAbort, match="changes nothing"):
        fp.apply_seed(target, b"x = f()", b"x = f()")


# --- Restore: the git-checkout failure ----------------------------------------

def test_restore_writes_back_the_held_bytes_and_verifies_them(tmp_path):
    target = tmp_path / "t.py"
    original = b"x = f()\r\n"
    target.write_bytes(original)
    held = fp.apply_seed(target, b"x = f()", b"x = 1")
    assert target.read_bytes() != original
    fp.restore(target, held)
    assert target.read_bytes() == original


def test_a_corrupted_restore_aborts_rather_than_continuing(tmp_path):
    """A restore that silently leaves the tree wrong poisons every later site.
    The probe stops; it does not carry on producing numbers against a tree it
    no longer understands."""
    target = tmp_path / "t.py"
    target.write_bytes(b"x = f()\r\n")

    class Sabotage:
        def write_bytes(self, path, data):
            path.write_bytes(data + b"# tampered\r\n")

        def read_bytes(self, path):
            return path.read_bytes()

    with pytest.raises(ProbeAbort, match="restore did not reproduce"):
        fp.restore(target, b"x = f()\r\n", io=Sabotage())


#: git subcommands the probe may execute. Read-only only, and pinned so that
#: adding one is a deliberate edit rather than a drift. `checkout`, `restore`,
#: `stash`, `reset` and `clean` are the ones that would silently widen a
#: change-scoped restore into a file-scoped one.
ALLOWED_GIT_SUBCOMMANDS = frozenset({"status"})


def test_the_probe_only_ever_runs_read_only_git_commands():
    """A restore scoped to a *file* is wider than a restore scoped to a
    *change*: `git checkout -- <file>` reverted an unrelated edit made minutes
    earlier in the same file. Byte-scoped restore or nothing.

    This originally banned the string `git` outright, which was the right
    prohibition stated too broadly — it also forbade `git status`, which the
    dirty-tree precondition needs and which cannot restore anything. Narrowed
    to the actual hazard: every git subcommand the probe executes must be on a
    pinned read-only list, so `checkout` cannot re-enter and the allowlist
    cannot grow by accident.
    """
    import ast

    tree = ast.parse(Path(fp.__file__).read_text(encoding="utf-8"))
    subcommands = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.List) or not node.elts:
            continue
        parts = [e.value for e in node.elts if isinstance(e, ast.Constant)
                 and isinstance(e.value, str)]
        if parts and parts[0] == "git":
            subcommands += [part for part in parts[1:] if not part.startswith("-")][:1]

    assert subcommands, "no git invocation found; this test would pass vacuously"
    assert set(subcommands) <= ALLOWED_GIT_SUBCOMMANDS, (
        f"probe executed a git subcommand outside the read-only allowlist: "
        f"{sorted(set(subcommands) - ALLOWED_GIT_SUBCOMMANDS)}"
    )


def test_the_git_allowlist_excludes_every_restoring_subcommand():
    """The allowlist is the load-bearing half; pin what it must never contain."""
    assert ALLOWED_GIT_SUBCOMMANDS.isdisjoint(
        {"checkout", "restore", "stash", "reset", "clean", "revert"})


def test_the_seed_is_restored_even_when_the_run_aborts(tmp_path):
    target = tmp_path / "t.py"
    original = b"x = f()\r\n"
    target.write_bytes(original)
    seed = Seed("s", target, b"x = f()", b"x = 1")
    with pytest.raises(ProbeAbort):
        fp.run_seed(seed, _runner("2 passed, 9 errors"), tmp_path / "bt", _noop_io())
    assert target.read_bytes() == original, "an abort must not leave the tree seeded"


# --- Temp paths: the Windows-colon failure ------------------------------------

@pytest.mark.parametrize("label", [
    "seed: downloaded_files rule", "a/b", "x<y>", 'q"r', "p|q", "s*t", "u?v", "",
])
def test_basetemp_paths_are_sanitized_from_the_label(label):
    safe = fp.sanitize_identifier(label)
    assert safe, "an empty identifier would collide across sites"
    assert not set(safe) & set('<>:"/\\|?*'), f"{safe!r} is not a valid path segment"


def test_two_labels_differing_only_in_forbidden_characters_do_not_collide():
    assert fp.sanitize_identifier("a:b") != fp.sanitize_identifier("a/b")


def test_basetemp_is_validated_before_the_first_run_not_discovered_mid_sweep(tmp_path):
    """The colon failure surfaced 39 errors into a run. The path is checked
    once, up front, against the platform actually running.

    The unusable path here is one *whose parent is a regular file* — invalid on
    every platform. The first version used `no:such/dir`, which is invalid on
    Windows and a perfectly ordinary directory name on Linux, so this test
    passed locally and failed on the runner. That is the same
    ambient-assumption error as #94's ignore check: an assertion about the
    machine it happened to run on, wearing a claim about behaviour.
    """
    blocker = tmp_path / "a-file"
    blocker.write_bytes(b"not a directory")
    with pytest.raises(ProbeAbort, match="not a usable basetemp"):
        fp.validate_basetemp_root(blocker / "child")


@pytest.mark.parametrize("label", ["a:b", "a/b", "a\\b"])
def test_sanitizing_covers_separators_that_differ_by_platform(label):
    """`:` is only special on Windows and `\\` only on Windows, but a probe run
    on either must produce the same directory names, or a survivor's basetemp
    depends on who ran it."""
    assert not set(fp.sanitize_identifier(label)) & set(':/\\')


def test_basetemp_is_created_before_the_suite_runs(tmp_path):
    seed = Seed("s", tmp_path / "t.py", b"a", b"b")
    (tmp_path / "t.py").write_bytes(b"a\r\n")
    # `_runner` asserts basetemp.exists(); a missing directory is the failure
    # that made every tmp_path test error.
    fp.run_seed(seed, _runner("1 failed, 3 passed"), tmp_path / "bt", _noop_io())


# --- Controls -----------------------------------------------------------------

def test_a_negative_control_that_dies_aborts_the_whole_sweep(tmp_path):
    """A no-op edit that "kills" a test means the probe is measuring the
    harness, not the seed. Every verdict in that sweep is worthless."""
    target = tmp_path / "t.py"
    target.write_bytes(b"x = 1\r\n")
    with pytest.raises(ProbeAbort, match="negative control"):
        fp.check_controls(
            target, _runner("1 failed, 3 passed"), tmp_path / "bt", _noop_io(),
            positive=None,
        )


def test_a_positive_control_that_survives_aborts_the_whole_sweep(tmp_path):
    target = tmp_path / "t.py"
    target.write_bytes(b"x = derived()\r\n")
    positive = Seed("known-bad", target, b"x = derived()", b"x = 1")
    with pytest.raises(ProbeAbort, match="positive control"):
        fp.check_controls(
            target, _runner("4 passed", "4 passed"), tmp_path / "bt", _noop_io(),
            positive=positive,
        )


def test_controls_passing_lets_the_sweep_proceed(tmp_path):
    target = tmp_path / "t.py"
    target.write_bytes(b"x = derived()\r\n")
    positive = Seed("known-bad", target, b"x = derived()", b"x = 1")
    fp.check_controls(
        target, _runner("4 passed", "1 failed, 3 passed"), tmp_path / "bt",
        _noop_io(), positive=positive,
    )


def test_a_sweep_without_a_positive_control_refuses_to_run(tmp_path):
    """The probe cannot invent a known-bad edit, so it declines to certify a
    clean sweep it has no way to validate."""
    with pytest.raises(ProbeAbort, match="positive control"):
        fp.require_positive_control(None)


# --- Enumeration: the failure the whole issue exists for ----------------------

SAMPLE = '''
from x import ObservedShape, Objective

TITLE = "API rate limits and pagination"

def collect(records, fields):
    report.objectives.append(Objective(
        17, TITLE,
        OBSERVED if not missing else DEGRADED,
        f"walked {pages} pages; fields: {', '.join(fields)}",
    ))
    report.observed_shapes.append(ObservedShape("pagination", derive(page_location)))
    report.observed_shapes.append(ObservedShape("static", "always-this"))
'''


def test_enumeration_finds_every_construction_site_without_a_hand_written_list(tmp_path):
    """`--sites auto`. The measured failure this closes: a hand-listed probe
    reported 0 survivors of 11 sites while 12 sites it never listed went
    unswept — one of which still held a literal. A probe built from the
    author's list inherits the author's sweep."""
    target = tmp_path / "s.py"
    target.write_bytes(SAMPLE.replace("\n", "\r\n").encode())
    labels = {seed.label for seed in fp.enumerate_construction_sites(target)}

    assert any("Objective" in l and "status" in l for l in labels)
    assert any("Objective" in l and "evidence" in l for l in labels)
    assert any("pagination" in l for l in labels)
    # f-string components are enumerated individually: the measured defects were
    # sub-fields of an evidence string, not the whole string.
    assert sum(1 for l in labels if "component" in l) >= 2
    assert len(labels) == len(fp.enumerate_construction_sites(target)), (
        "labels must be unique — duplicates collide into one basetemp directory"
    )


def test_enumeration_skips_arguments_that_are_already_constants(tmp_path):
    """`ObservedShape("static", "always-this")` has nothing to falsify: a
    literal replacing a literal is not a measurement."""
    target = tmp_path / "s.py"
    target.write_bytes(SAMPLE.replace("\n", "\r\n").encode())
    labels = {seed.label for seed in fp.enumerate_construction_sites(target)}
    assert not any("static" in l for l in labels)


def test_every_enumerated_seed_applies_cleanly_to_the_file_it_came_from(tmp_path):
    """An enumerated seed that does not match is the CRLF failure produced by
    the probe itself, at scale and silently."""
    target = tmp_path / "s.py"
    original = SAMPLE.replace("\n", "\r\n").encode()
    target.write_bytes(original)
    for seed in fp.enumerate_construction_sites(target):
        held = fp.apply_seed(seed.path, seed.old, seed.new)
        fp.restore(seed.path, held)
    assert target.read_bytes() == original


def test_enumeration_of_the_real_exemplar_covers_the_site_the_hand_list_missed():
    """Regression on the specific miss: the `pagination` entry's *location*."""
    trial_auth = Path(fp.__file__).parent / "trial_auth.py"
    seeds = fp.enumerate_construction_sites(trial_auth)
    assert any(b"page_location" in seed.old for seed in seeds), (
        "the location half of the pagination entry must be enumerated"
    )
    assert len(seeds) >= 11


# --- Subject deletion ---------------------------------------------------------

def test_deleting_a_subject_is_a_seed_like_any_other(tmp_path):
    """A test whose assertion passes when the artifact under test is deleted is
    not testing that artifact. Measured on the `downloaded_files/` ignore rule,
    which was proven by observing its effect rather than by anything asserted."""
    target = tmp_path / ".gitignore"
    target.write_bytes(b"a/\r\ndownloaded_files/\r\nb/\r\n")
    seed = fp.subject_deletion_seed(target, "downloaded_files/")
    held = fp.apply_seed(seed.path, seed.old, seed.new)
    assert b"downloaded_files" not in target.read_bytes()
    fp.restore(seed.path, held)
    assert target.read_bytes() == b"a/\r\ndownloaded_files/\r\nb/\r\n"


def test_deleting_an_absent_subject_aborts(tmp_path):
    target = tmp_path / ".gitignore"
    target.write_bytes(b"a/\r\n")
    with pytest.raises(ProbeAbort, match="did not match"):
        fp.apply_seed(*_seed_parts(fp.subject_deletion_seed(target, "nope/")))


# --- Exit code ----------------------------------------------------------------

def test_any_survivor_exits_non_zero():
    assert fp.exit_code([KILLED, KILLED]) == 0
    assert fp.exit_code([KILLED, SURVIVED]) != 0
    assert fp.exit_code([]) != 0, "a sweep with no seeds certifies nothing"


# --- Exemptions must be visible, never silent ---------------------------------

def test_an_exempt_survivor_does_not_fail_the_gate():
    """Item 10 governs `status`, `evidence`, and `observed_shapes[]`. A title
    and an entry name are identifiers, and a constant is the correct
    implementation of both."""
    labels = ["Objective:x.py:1:arg1[t]:title", "ObservedShape:x.py:2:arg1[e]:shape"]
    assert fp.exit_code([SURVIVED, KILLED], labels) == 0
    assert fp.exit_code([KILLED, SURVIVED], labels) != 0


def test_the_exemption_list_is_pinned_so_growth_is_an_event_not_a_drift():
    """The one place this gate can quietly lose its teeth.

    Every exemption will look justified at the moment it is added — exactly as
    each unswept sibling did. Pinning the set means going from two to three is
    a deliberate change with a diff someone has to write a reason into, rather
    than a line that accretes. Same move as the pinned suite counts, aimed at
    the gate's own escape valve.

    Adding a role here is legitimate. Doing it without noticing is not.
    """
    assert fp.EXEMPT_ROLES == frozenset({"title", "entry-name"})
    assert len(fp.EXEMPT_ROLES) == 2


def test_the_exempt_site_count_in_the_exemplar_is_pinned():
    """The other half: a role can stay fixed while the number of *sites* it
    excuses grows. Two `Objective` titles today, both constants by design."""
    trial_auth = Path(fp.__file__).parent / "trial_auth.py"
    exempt = [s for s in fp.enumerate_construction_sites(trial_auth) if fp.is_exempt(s.label)]
    assert len(exempt) == 2, [s.label for s in exempt]


def test_exempt_sites_are_still_enumerated_and_seeded(tmp_path):
    """An exemption that hides its subject is indistinguishable from an
    enumeration gap — which is the failure this instrument exists to prevent.
    Exempt sites are run and printed; they only stop short of failing the gate.
    """
    target = tmp_path / "s.py"
    target.write_bytes(SAMPLE.replace("\n", "\r\n").encode())
    labels = [seed.label for seed in fp.enumerate_construction_sites(target)]
    assert any(fp.is_exempt(label) for label in labels), (
        "exempt roles must appear in the enumeration, not be filtered out of it"
    )


def _seed_parts(seed):
    return seed.path, seed.old, seed.new


def _noop_io():
    class IO:
        def write_bytes(self, path, data):
            path.write_bytes(data)

        def read_bytes(self, path):
            return path.read_bytes()
    return IO()


# --- The sweep's own preconditions ---------------------------------------------
#
# Both refusals below exist because the conditions they check were violated in
# practice, not anticipated in design: a background sweep and a foreground
# hand-seed ran against one checkout, five tests from an unrelated module failed
# in the seeded run, and both results were void. The rule form of this
# ("one worktree per agent, or serialize") was being actively restated by its
# author at the time. An instrument that can be invalidated by a condition it
# does not check will be.

def test_a_verdict_carries_the_summary_it_was_scored_from(tmp_path):
    """Two runs, two different summaries, two different outcomes — a verdict
    alone cannot distinguish a genuine SURVIVED from a KILLED produced by an
    unrelated flaky test, which is exactly the ambiguity that cost a sweep."""
    target = tmp_path / "t.py"
    target.write_bytes(b"a" + bytes((13, 10)))
    seed = fp.Seed("s", target, b"a", b"b")
    io = _noop_io()
    first = fp.run_seed(seed, _runner("1 failed, 3 passed"), tmp_path / "bt", io)
    second = fp.run_seed(seed, _runner("4 passed"), tmp_path / "bt", io)
    assert (first.verdict, first.summary) == (fp.KILLED, "1 failed, 3 passed")
    assert (second.verdict, second.summary) == (fp.SURVIVED, "4 passed")


def test_a_second_sweep_in_the_same_tree_is_refused(tmp_path):
    with fp._SweepLock(tmp_path):
        with pytest.raises(fp.ProbeAbort, match="another sweep holds"):
            with fp._SweepLock(tmp_path):
                pass


def test_the_lock_is_released_even_when_the_sweep_aborts(tmp_path):
    with pytest.raises(ValueError):
        with fp._SweepLock(tmp_path):
            raise ValueError("boom")
    assert not (tmp_path / fp.LOCK_NAME).exists()
    with fp._SweepLock(tmp_path):  # the next sweep can start
        pass


def test_a_dirty_tree_is_refused_but_untracked_files_are_not(tmp_path, monkeypatch):
    """Untracked files must be allowed: a new slice's scripts are untracked by
    definition, and refusing them would disable the probe exactly when a slice
    most needs sweeping."""
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        import types
        return types.SimpleNamespace(returncode=0, stdout=_fake_run.stdout, stderr="")

    monkeypatch.setattr(fp.subprocess, "run", _fake_run)

    _fake_run.stdout = ""
    fp.require_clean_tree(tmp_path)

    _fake_run.stdout = " M scripts/trial_auth.py\n"
    with pytest.raises(fp.ProbeAbort, match="uncommitted changes"):
        fp.require_clean_tree(tmp_path)

    assert all("--untracked-files=no" in cmd for cmd in calls)


def test_a_tree_dirtied_during_the_sweep_voids_it(tmp_path, monkeypatch):
    """The start check is a t=0 check. The lock stops a second process; nothing
    stops a hand edit mid-sweep, which is materially what the incident was. Two
    phases, two different refusals — and the end-of-sweep one must say the run
    is void, not merely that the tree is dirty."""
    import types
    dirty = " M scripts/trial_auth.py\n"
    monkeypatch.setattr(
        fp.subprocess, "run",
        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=dirty, stderr=""))

    with pytest.raises(fp.ProbeAbort, match="Commit or stash first") as at_start:
        fp.require_clean_tree(tmp_path, phase="start")
    with pytest.raises(fp.ProbeAbort, match="THIS SWEEP IS VOID") as at_end:
        fp.require_clean_tree(tmp_path, phase="end")
    assert str(at_start.value) != str(at_end.value)


def test_a_verdict_carries_the_node_ids_that_failed(tmp_path):
    """Two runs with identical summaries and different failing tests.

    `1 failed, 3 passed` cannot distinguish a seed killed by the test that
    targets it from a seed killed by an unrelated flaky test -- identical
    counts, opposite meanings. The names are what make a flip read itself off
    the log rather than needing a diff of two job logs.
    """
    target = tmp_path / "t.py"
    target.write_bytes(b"a" + bytes((13, 10)))
    seed = fp.Seed("s", target, b"a", b"b")

    def _runner_with(failed):
        return lambda _bt: fp.SuiteResult("1 failed, 3 passed", failed)

    on_target = fp.run_seed(seed, _runner_with(["tests/test_x.py::test_the_site"]),
                            tmp_path / "bt", _noop_io())
    elsewhere = fp.run_seed(seed, _runner_with(["tests/test_other.py::test_unrelated"]),
                            tmp_path / "bt", _noop_io())

    assert on_target.summary == elsewhere.summary
    assert on_target.failed == ("tests/test_x.py::test_the_site",)
    assert elsewhere.failed == ("tests/test_other.py::test_unrelated",)
    assert on_target.failed != elsewhere.failed


def test_the_runner_captures_full_node_ids_from_pytest_output(tmp_path, monkeypatch):
    """Behavioural, not a grep of the source. Asserting that the file contains
    a particular slicing expression answers "does this code look right", which
    is the adjacent-question family the plan names. This drives the parser."""
    import types
    stdout = chr(10).join([
        "FAILED tests/test_trial_harness.py::test_one - AssertionError: x",
        "FAILED tests/test_trial_discovery.py::test_two[trial_fixtures] - E",
        "2 failed, 3 passed in 1.0s",
    ])
    monkeypatch.setattr(
        fp.subprocess, "run",
        lambda *a, **k: types.SimpleNamespace(returncode=1, stdout=stdout, stderr=""))

    result = fp.pytest_runner(tmp_path)(tmp_path / "bt")

    assert result.failed == [
        "tests/test_trial_harness.py::test_one",
        "tests/test_trial_discovery.py::test_two[trial_fixtures]",
    ]
    assert result.summary == "2 failed, 3 passed in 1.0s"


def test_the_runner_disables_bytecode_caching(tmp_path, monkeypatch):
    """A seed on disk that the child process never executes is a false survivor.

    CPython invalidates a cached .pyc on source mtime+size; a probe seed is a
    similar-length replacement written milliseconds after the original, so a
    same-second write can hit a stale cache. Measured at 4 flips in 20 CI runs,
    in both directions -- a false survivor when the seeded module is stale, and
    failures in an *unrelated* module when a previous seed's cache is still
    live. Behavioural: the env actually handed to the subprocess is captured.
    """
    import types
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured.update(kwargs.get("env") or {})
        return types.SimpleNamespace(returncode=0, stdout="1 passed in 0.1s", stderr="")

    monkeypatch.setattr(fp.subprocess, "run", _fake_run)
    fp.pytest_runner(tmp_path)(tmp_path / "bt")

    assert captured.get("PYTHONDONTWRITEBYTECODE") == "1"
    assert captured.get("PYTHONIOENCODING") == "utf-8"


def test_a_seed_that_is_on_disk_but_not_loaded_by_the_child_aborts(tmp_path):
    """The mechanism assertion. `apply_seed` proves the *bytes changed* -- a
    property. This proves the *seeded code executes* -- the mechanism. They came
    apart: a stale .pyc gave a fully green suite with the seed genuinely
    written, 3 times in 20 CI runs, reported as a survivor.

    PYTHONDONTWRITEBYTECODE fixes that one cause; this detects the class,
    including sys.modules reuse, a shadowing installed copy, and causes nobody
    has thought of. The fix addresses a mechanism, the detector outlives it.
    """
    target = tmp_path / "m.py"
    target.write_text("X = 'probe-literal'" + chr(10), encoding="utf-8")
    fp.require_seed_reaches_the_child(target, b"ORIGINAL", b'"probe-literal"')

    target.write_text("X = 'something-else'" + chr(10), encoding="utf-8")
    with pytest.raises(fp.ProbeAbort, match="does not load it"):
        fp.require_seed_reaches_the_child(target, b"ORIGINAL", b'"probe-literal"')


def test_a_seed_introducing_no_literal_skips_the_load_check(tmp_path):
    """Numeric or expression-only seeds have nothing quoted to look for; the
    check must decline rather than invent a needle and abort every sweep."""
    assert fp.seed_literal(b"len(a)", b"len(b)") is None
    fp.require_seed_reaches_the_child(tmp_path / "missing.py", b"len(a)", b"len(b)")


def test_the_detector_fires_on_a_genuinely_stale_bytecode_cache(tmp_path):
    """Constructs the real scenario rather than a stand-in for it.

    A working safeguard and an unnecessary one produce identical observations:
    zero flips is what you see if this detector is redundant AND what you see if
    it is the thing preventing them. That is the same unfalsifiability this
    phase keeps finding, aimed at a control instead of a claim -- so the value
    is demonstrated here, not inferred.

    Note what this also shows: PYTHONDONTWRITEBYTECODE stops the child *writing*
    a cache, not *reading* one that already exists. The env var is therefore not
    a complete fix on a tree where any earlier process left caches behind, and
    the detector covers that residue.
    """
    import os
    import py_compile

    module = tmp_path / "stale.py"
    module.write_text("X = 'aaaaaaaaaaaaa'" + chr(10), encoding="utf-8")
    py_compile.compile(str(module), doraise=True)
    before = module.stat()

    # The "seed": identical byte length, different content, mtime restored --
    # exactly what CPython's mtime+size validation cannot distinguish.
    module.write_text("X = 'probe-literal'" + chr(10), encoding="utf-8")
    os.utime(module, (before.st_atime, before.st_mtime))
    assert module.stat().st_size == before.st_size

    with pytest.raises(fp.ProbeAbort, match="does not load it"):
        fp.require_seed_reaches_the_child(module, b"ORIGINAL", b'"probe-literal"')


def test_the_same_seed_passes_once_the_stale_cache_is_gone(tmp_path):
    """The other half: without the stale cache the identical seed is accepted,
    so the abort above is attributable to staleness and not to the seed."""
    import shutil

    module = tmp_path / "fresh.py"
    module.write_text("X = 'probe-literal'" + chr(10), encoding="utf-8")
    shutil.rmtree(tmp_path / "__pycache__", ignore_errors=True)
    fp.require_seed_reaches_the_child(module, b"ORIGINAL", b'"probe-literal"')


def test_the_detector_survives_a_live_sweep_of_every_trial_script(tmp_path):
    """Coverage geometry, not mechanism.

    The detector's other tests use inputs its author constructed for it: a
    deliberately same-size string pair, and files it had already seen. The first
    real script with a different seed shape aborted 3 of 3 -- a component seed
    inside an f-string, whose replacement is a bare name in co_names and never a
    constant. Constructed tests certify the mechanism; only a live sweep
    certifies it against shapes nobody anticipated.

    Every trial_*.py, because the shapes differ per file and that is exactly
    where it broke. Seeds are applied to a copy, so the tree is never mutated.
    """
    import shutil

    scripts = sorted((Path(fp.__file__).parent).glob("trial_*.py"))
    assert scripts, "no trial scripts found; this test would pass vacuously"

    total = 0
    for script in scripts:
        copy = tmp_path / script.name
        shutil.copy2(script, copy)
        seeds = fp.enumerate_construction_sites(copy)
        assert seeds, f"no construction sites enumerated in {script.name}"
        for seed in seeds:
            total += 1
            held = fp.apply_seed(seed.path, seed.old, seed.new)
            try:
                fp.require_seed_reaches_the_child(seed.path, seed.old, seed.new)
            finally:
                fp.restore(seed.path, held)

    assert total > 0


# --- Owner attribution ---------------------------------------------------------
#
# The gate books a kill when *any* test fails under a seed. That is the right
# default and it has a gap: a test that reads a seeded file at runtime fails
# whatever the seed was, so its failure is not evidence that the seeded value is
# falsifiable. `test_falsifiability_probe.py` does exactly that to
# `trial_auth.py` -- it enumerates the real exemplar from disk -- and fires on 7
# of that file's 12 sites.
#
# It has never inflated anything: the owning suite fires on all 12, so no kill
# rests on the coupling alone. These tests exist so that stops being a fact
# somebody has to keep re-measuring.

def test_the_owner_mapping_is_not_derivable_from_the_name():
    """The three cases a name-matching heuristic gets wrong. This is the whole
    reason the mapping is written out rather than computed."""
    assert fp.OWNERS["trial_injuries.py"] == frozenset({"test_trial_health_stats.py"})
    assert fp.OWNERS["trial_entities.py"] == frozenset({"test_trial_discovery.py"})
    assert fp.OWNERS["trial_fixtures.py"] == frozenset({"test_trial_discovery.py"})


def test_every_swept_script_has_a_declared_owner():
    """Coverage of the mapping itself. A script the gate sweeps but nobody owns
    is a script whose kills cannot be attributed."""
    scripts = sorted(p.name for p in Path(fp.__file__).parent.glob("trial_*.py"))
    assert scripts, "no trial scripts found; this test would pass vacuously"
    undeclared = [name for name in scripts if not fp.owners_for(name)]
    assert undeclared == [], f"no owner declared for {undeclared}"


def test_an_owner_among_the_killers_is_not_silent():
    assert not fp.owner_was_silent(
        "trial_auth.py",
        ["tests/test_trial_harness.py::test_x", "tests/test_falsifiability_probe.py::test_y"],
    )


def test_a_kill_with_only_foreign_killers_is_owner_silent():
    """The case that matters: the probe's own tests fired and the owning suite
    did not. Today this returns False for every real site; it is the regression
    that would make it True which the gate now names."""
    assert fp.owner_was_silent(
        "trial_auth.py", ["tests/test_falsifiability_probe.py::test_y"])


def test_a_seed_that_killed_nothing_is_not_owner_silent():
    """A survivor has no killers to attribute. Reporting it here would double-count
    it as both a survivor and an attribution failure."""
    assert not fp.owner_was_silent("trial_auth.py", [])


def test_owner_silence_is_decided_per_file_not_globally():
    """Two files, same killer, opposite answers -- so the check cannot be
    passing on a constant."""
    failed = ["tests/test_trial_discovery.py::test_x"]
    assert not fp.owner_was_silent("trial_entities.py", failed)
    assert fp.owner_was_silent("trial_squads.py", failed)


def test_the_owner_flag_extends_the_mapping():
    extra = {"trial_new.py": frozenset({"test_trial_new.py"})}
    assert fp.owner_was_silent("trial_new.py", ["tests/test_other.py::t"], extra)
    assert not fp.owner_was_silent("trial_new.py", ["tests/test_trial_new.py::t"], extra)


def test_an_undeclared_file_aborts_before_the_sweep():
    """Non-vacuity. An attribution check that skips what it cannot attribute
    passes by measuring nothing -- the enumerator-that-scanned-nothing failure,
    one layer up."""
    with pytest.raises(fp.ProbeAbort) as excinfo:
        fp.require_owners(["trial_auth.py", "trial_unmapped.py"], {})
    assert "trial_unmapped.py" in str(excinfo.value)
    fp.require_owners(["trial_auth.py"], {})


def test_killer_files_reads_the_module_not_the_test_name():
    assert fp.killer_files(
        ["tests/test_a.py::test_one", "tests/sub/test_b.py::TestC::test_two"]
    ) == frozenset({"test_a.py", "test_b.py"})
    assert fp.killer_files(["not-a-node-id"]) == frozenset()


# --- Owner attribution: the wiring, not just the predicate ----------------------
#
# The tests above exercise `owner_was_silent` and `require_owners` directly. That
# proves the predicates are right and says nothing about whether `main()` calls
# them -- and an outcome nobody asserts is the layer that gets deleted silently.
# These drive `main()` end to end with a stubbed suite runner and assert the
# thing that actually matters: the gate FAILS.

def _drive_main(monkeypatch, tmp_path, killer_module, owner_args):
    """Run fp.main() over a fake script with a stubbed pytest and git."""
    import types

    target = tmp_path / "trial_fake.py"
    target.write_text(SAMPLE, encoding="utf-8")
    pristine = target.read_bytes()
    basetemp = tmp_path / "bt"
    basetemp.mkdir()

    real_run = fp.subprocess.run

    def _fake_run(cmd, **kwargs):
        # The seed-reaches-child detector spawns its own interpreter. Delegate
        # it to the real subprocess so that layer stays genuinely exercised --
        # stubbing it would be deleting a layer to make a test pass, which is
        # the failure this file exists to catch.
        if "-c" in cmd:
            return real_run(cmd, **kwargs)
        if "pytest" not in cmd:                      # git status -> clean tree
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        body = target.read_bytes()
        # "Is this file seeded?" is answered by comparing against the pristine
        # bytes, never by sniffing for a token. Replacements are role-specific:
        # a status site gets `"observed"`, an f-string component gets a bare
        # `probe`, and only some sites get `fp.LITERAL`. A token check scored
        # three of six seeds as survivors and the test measured the wrong thing
        # while appearing to work -- the failure this file is about, committed
        # inside a test written to catch it.
        if b"# probe no-op" in body:                 # negative control must SURVIVE
            out = "1 passed in 0.01s"
        elif body != pristine:                       # seeded: the suite notices
            out = (f"FAILED {killer_module}::test_notices\n"
                   "1 failed, 1 passed in 0.01s")
        else:
            out = "1 passed in 0.01s"
        return types.SimpleNamespace(returncode=0, stdout=out, stderr="")

    monkeypatch.setattr(fp.subprocess, "run", _fake_run)
    code = fp.main([
        "--file", str(target),
        "--positive-control", f"{target}::always-this::pc-broken",
        "--basetemp-root", str(basetemp),
        *owner_args,
    ])
    return code


def test_main_passes_when_the_owning_suite_catches_every_seed(
        monkeypatch, tmp_path, capsys):
    code = _drive_main(monkeypatch, tmp_path, "tests/test_owner.py",
                       ["--owner", "trial_fake.py::test_owner.py"])
    out = capsys.readouterr().out
    assert "owner-silent kills: 0" in out
    assert "OWNER-SILENT" not in out
    assert code == 0


def test_main_fails_the_gate_when_only_foreign_tests_caught_the_seed(
        monkeypatch, tmp_path, capsys):
    """The case the check exists for, asserted as the *outcome*: a non-zero exit.

    Same inputs as the passing test except which module the failures name, so a
    gate that ignored attribution would return 0 here and be caught."""
    code = _drive_main(monkeypatch, tmp_path, "tests/test_stranger.py",
                       ["--owner", "trial_fake.py::test_owner.py"])
    out = capsys.readouterr().out
    assert "OWNER-SILENT" in out
    assert "owner-silent kills: 0" not in out
    assert code == 1


def test_main_aborts_when_the_swept_file_declares_no_owner(
        monkeypatch, tmp_path, capsys):
    """Non-vacuity at the entry point: an undeclared file must stop the sweep
    rather than be attributed as trivially owned."""
    code = _drive_main(monkeypatch, tmp_path, "tests/test_owner.py", [])
    out = capsys.readouterr().out
    assert "ABORT" in out and "trial_fake.py" in out
    assert code == 3
