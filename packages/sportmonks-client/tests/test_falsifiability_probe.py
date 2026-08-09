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


def test_the_probe_never_shells_out_to_git_to_restore():
    """A restore scoped to a *file* is wider than a restore scoped to a
    *change*. `git checkout -- <file>` reverted an unrelated edit made minutes
    earlier in the same file. Byte-scoped restore or nothing."""
    import ast

    tree = ast.parse(Path(fp.__file__).read_text(encoding="utf-8"))
    executed = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and not isinstance(getattr(node, "parent", None), ast.Expr)
    ]
    # Docstrings legitimately discuss `git checkout` — that is the finding this
    # exists to record. What must not appear is git in anything *executed*.
    docstrings = {ast.get_docstring(n) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))}
    code_strings = [s for s in executed if s not in docstrings]
    assert not [s for s in code_strings if "git" in s.split()], (
        f"probe must not shell out to git: {[s for s in code_strings if 'git' in s]}"
    )


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
    once, up front, against the platform actually running."""
    with pytest.raises(ProbeAbort, match="not a usable basetemp"):
        fp.validate_basetemp_root(tmp_path / "no:such" / "dir")


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
