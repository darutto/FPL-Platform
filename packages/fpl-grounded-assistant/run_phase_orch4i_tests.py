"""
run_phase_orch4i_tests.py
==========================
Phase Orch-4i: Gate scope parity checker.

Validates that the CI workflow and the local convenience script enumerate
the exact same contract-gate runners in the exact same order.

Files checked:
  .github/workflows/contract-drift-gate.yml   (CI job)
  scripts/run_contract_gate.sh                (local wrapper)

Invariants enforced:
  1.  Both files reference exactly the canonical set of runner files.
  2.  Both files reference the runners in the canonical order.
  3.  Neither file references unknown runners not in the canonical list.
  4.  The two files agree with each other (independent of the canonical list).

Canonical runner order:
  run_phase_orch4i_tests.py   (this file — gate scope parity, runs first)
  run_phase_orch4f_tests.py   (contract/fixture drift checker)
  run_phase_orch4e_tests.py   (orch_outcome contract parity)
  run_phase_orch4d_tests.py   (squad_context override parity)
  run_phase_orch4c_tests.py   (orchestration audit parity)
  run_phase_orch4a_tests.py   (orchestration enable/disable flag parity)
  run_phase_orch4b_tests.py   (orch_outcome serialization parity)

All checks are pure string / structure-based — no network calls, no LLM calls,
no runtime respond() calls.

Sections:
  A   File presence
  B   CI workflow runner extraction and order
  C   Shell script runner extraction and order
  D   Cross-file parity (yml == sh)
  E   Canonical order invariants
  F   Seeded mutation proofs (missing / swapped / extra runner)
  G   Regression sanity
"""
from __future__ import annotations

import copy
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))   # two levels up from pkg dir

_YML_PATH = os.path.join(_REPO_ROOT, ".github", "workflows", "contract-drift-gate.yml")
_SH_PATH  = os.path.join(_REPO_ROOT, "scripts", "run_contract_gate.sh")

# ---------------------------------------------------------------------------
# Canonical ordered runner list — single source of truth for this checker
# ---------------------------------------------------------------------------

CANONICAL_RUNNERS: list[str] = [
    "run_phase_orch4i_tests.py",   # gate scope parity (this runner — must be first)
    "run_phase_orch4f_tests.py",   # contract/fixture drift
    "run_phase_orch4e_tests.py",   # orch_outcome parity
    "run_phase_orch4d_tests.py",   # squad_context override parity
    "run_phase_orch4c_tests.py",   # orchestration audit parity
    "run_phase_orch4a_tests.py",   # orchestration enable/disable flag parity
    "run_phase_orch4b_tests.py",   # orch_outcome serialization parity
]

# Slices implemented without a standalone runner file.
# Each entry must be documented by name in CONTRACT_GATE.md (enforced by G7).
# If a runner is later created for a slice, move it to CANONICAL_RUNNERS and
# remove it from this list — in the same commit.
NON_RUNNER_SLICES: list[str] = [
    "Orch-4g",   # CI gate wiring — implemented as CI/script config, no runner
    "Orch-4h",   # session_id envelope invariant — enforced inside Orch-4f (Section A2)
]

# Expected assertion counts for all canonical runners as published in CONTRACT_GATE.md.
# G8 checks this runner's own count; G9 checks the full table.
# When a runner's count changes, update both this mapping and the CONTRACT_GATE.md table
# in the same commit — G9 will fail until both are aligned.
RUNNER_EXPECTED_COUNTS: dict[str, int] = {
    "run_phase_orch4i_tests.py": 70,   # includes G8 + G9 + G10 + F-G/H/I/J (Orch-4k5)
    "run_phase_orch4f_tests.py": 125,
    "run_phase_orch4e_tests.py": 122,
    "run_phase_orch4d_tests.py": 84,
    "run_phase_orch4c_tests.py": 120,
    "run_phase_orch4a_tests.py": 193,
    "run_phase_orch4b_tests.py": 239,
}

# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0


def ok(cond: bool, label: str, detail: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  PASS  {label}")
    else:
        _FAIL += 1
        msg = f"  FAIL  {label}"
        if detail:
            msg += f"  [{detail}]"
        print(msg)


def ok_not(cond: bool, label: str, detail: str = "") -> None:
    """Assert cond is False — used for mutation proofs."""
    ok(not cond, label, detail)


# ---------------------------------------------------------------------------
# Parsing helpers — pure functions, accept text so mutation tests work
# ---------------------------------------------------------------------------

def extract_yml_runners(yml_text: str) -> list[str]:
    """Extract runner filenames from CI workflow `run: python <file>` steps.

    Matches lines of the form (anywhere in the YAML):
        run: python run_phase_<something>.py
        run: python run_phase_<something>.py  # comment

    Returns an ordered list of runner filenames.
    """
    pattern = re.compile(r'^\s*run:\s*python\s+(run_phase_\w+\.py)', re.MULTILINE)
    return [m.group(1) for m in pattern.finditer(yml_text)]


def extract_sh_runners(sh_text: str) -> list[str]:
    """Extract runner filenames from the bash script `run_runner` invocations.

    Matches lines of the form:
        run_runner "label"  "run_phase_<something>.py"
        run_runner "label" "run_phase_<something>.py"

    Returns an ordered list of runner filenames.
    """
    pattern = re.compile(r'run_runner\s+"[^"]*"\s+"(run_phase_\w+\.py)"')
    return [m.group(1) for m in pattern.finditer(sh_text)]


# ---------------------------------------------------------------------------
# Core checker functions — accept parsed lists so mutation tests can call them
# ---------------------------------------------------------------------------

def check_runner_list(
    source_name: str,
    actual: list[str],
    canonical: list[str],
) -> list[tuple[bool, str, str]]:
    """Check that `actual` matches `canonical` in content and order.

    Returns a list of (pass, label, detail) tuples covering:
      - Count parity
      - Missing runners (in canonical but absent from actual)
      - Extra runners (in actual but absent from canonical)
      - Ordered-list exact match
      - First-runner constraint (gate scope parity runner must be first)
    """
    results = []
    actual_set   = set(actual)
    canonical_set = set(canonical)

    missing = sorted(canonical_set - actual_set)
    extra   = sorted(actual_set - canonical_set)

    results.append((
        len(missing) == 0,
        f"{source_name}: no runners missing from canonical list",
        f"missing: {missing}" if missing else "",
    ))

    results.append((
        len(extra) == 0,
        f"{source_name}: no extra unknown runners",
        f"extra: {extra}" if extra else "",
    ))

    results.append((
        actual == canonical,
        f"{source_name}: runner order matches canonical exactly",
        _order_diff(actual, canonical) if actual != canonical else "",
    ))

    # First runner must be the gate scope parity checker itself
    first_runner = canonical[0] if canonical else ""
    results.append((
        (actual[0] == first_runner) if actual else False,
        f"{source_name}: first runner is '{first_runner}' (gate scope parity runs first)",
        f"got first runner: {actual[0]!r}" if actual and actual[0] != first_runner else (
            "list is empty" if not actual else ""
        ),
    ))

    return results


def check_cross_file_parity(
    yml_runners: list[str],
    sh_runners: list[str],
) -> list[tuple[bool, str, str]]:
    """Check that yml and sh agree on runner list and order, independent of canonical."""
    results = []

    results.append((
        yml_runners == sh_runners,
        "CI yml and shell script enumerate runners in the same order",
        _order_diff(yml_runners, sh_runners) if yml_runners != sh_runners else "",
    ))

    yml_set = set(yml_runners)
    sh_set  = set(sh_runners)
    only_yml = sorted(yml_set - sh_set)
    only_sh  = sorted(sh_set - yml_set)

    results.append((
        len(only_yml) == 0,
        "no runners in CI yml that are absent from shell script",
        f"yml-only: {only_yml}" if only_yml else "",
    ))

    results.append((
        len(only_sh) == 0,
        "no runners in shell script that are absent from CI yml",
        f"sh-only: {only_sh}" if only_sh else "",
    ))

    return results


def _order_diff(actual: list[str], expected: list[str]) -> str:
    """Produce a human-readable order diff for failure diagnostics."""
    lines = []
    max_len = max(len(actual), len(expected))
    for i in range(max_len):
        a = actual[i]  if i < len(actual)    else "<missing>"
        e = expected[i] if i < len(expected) else "<missing>"
        marker = "  " if a == e else "!!"
        lines.append(f"{marker} pos {i}: got={a!r} want={e!r}")
    return "; ".join(lines)


def check_canonical_count_alignment(
    canonical: list[str],
    count_keys: list[str],
) -> list[tuple[bool, str, str]]:
    """Assert that a count-map key list is aligned with the canonical runner list.

    Returns (pass, label, detail) tuples covering:
      - No canonical runners missing from the count map.
      - No extra runners in the count map not in canonical list.
      - Count map key order matches canonical order exactly.

    Accepts the count-map keys as a plain list so callers can pass mutated
    copies for mutation-proof testing without touching real data.
    """
    results = []
    canonical_set = set(canonical)
    count_set     = set(count_keys)

    missing = sorted(canonical_set - count_set)
    extra   = sorted(count_set - canonical_set)

    results.append((
        len(missing) == 0,
        "G10 alignment: no canonical runners missing from RUNNER_EXPECTED_COUNTS",
        f"missing: {missing}" if missing else "",
    ))
    results.append((
        len(extra) == 0,
        "G10 alignment: no extra runners in RUNNER_EXPECTED_COUNTS not in CANONICAL_RUNNERS",
        f"extra: {extra}" if extra else "",
    ))
    results.append((
        count_keys == canonical,
        "G10 alignment: RUNNER_EXPECTED_COUNTS key order matches CANONICAL_RUNNERS",
        _order_diff(count_keys, canonical) if count_keys != canonical else "",
    ))

    return results


# ---------------------------------------------------------------------------
# Load real files
# ---------------------------------------------------------------------------

def _apply_results(results: list[tuple[bool, str, str]]) -> None:
    for cond, label, detail in results:
        ok(cond, label, detail)


# ===========================================================================
# Section A — File presence
# ===========================================================================

print("\n--- A: File presence ---")
ok(os.path.isfile(_YML_PATH),  "A1 contract-drift-gate.yml exists", detail=_YML_PATH)
ok(os.path.isfile(_SH_PATH),   "A2 run_contract_gate.sh exists",    detail=_SH_PATH)

# Read files (gate continues even if a file is missing — later checks will fail)
_yml_text = ""
_sh_text  = ""

if os.path.isfile(_YML_PATH):
    with open(_YML_PATH, encoding="utf-8") as _f:
        _yml_text = _f.read()

if os.path.isfile(_SH_PATH):
    with open(_SH_PATH, encoding="utf-8") as _f:
        _sh_text = _f.read()

ok(len(_yml_text) > 500,  "A3 CI yml is non-trivially long", detail=f"len={len(_yml_text)}")
ok(len(_sh_text)  > 200,  "A4 shell script is non-trivially long", detail=f"len={len(_sh_text)}")


# ===========================================================================
# Section B — CI workflow runner extraction and order
# ===========================================================================

print("\n--- B: CI workflow runner order ---")
_yml_runners = extract_yml_runners(_yml_text)
ok(
    len(_yml_runners) > 0,
    "B1 at least one runner extracted from CI yml",
    detail=f"extracted: {_yml_runners}",
)
_apply_results(check_runner_list("CI yml", _yml_runners, CANONICAL_RUNNERS))


# ===========================================================================
# Section C — Shell script runner extraction and order
# ===========================================================================

print("\n--- C: Shell script runner order ---")
_sh_runners = extract_sh_runners(_sh_text)
ok(
    len(_sh_runners) > 0,
    "C1 at least one runner extracted from shell script",
    detail=f"extracted: {_sh_runners}",
)
_apply_results(check_runner_list("shell script", _sh_runners, CANONICAL_RUNNERS))


# ===========================================================================
# Section D — Cross-file parity
# ===========================================================================

print("\n--- D: Cross-file parity (yml == sh) ---")
_apply_results(check_cross_file_parity(_yml_runners, _sh_runners))


# ===========================================================================
# Section E — Canonical order invariants (count + each runner present)
# ===========================================================================

print("\n--- E: Canonical order invariants ---")
ok(
    len(_yml_runners) == len(CANONICAL_RUNNERS),
    f"E1 CI yml has exactly {len(CANONICAL_RUNNERS)} runners",
    detail=f"got {len(_yml_runners)}: {_yml_runners}",
)
ok(
    len(_sh_runners) == len(CANONICAL_RUNNERS),
    f"E2 shell script has exactly {len(CANONICAL_RUNNERS)} runners",
    detail=f"got {len(_sh_runners)}: {_sh_runners}",
)

for _i, _runner in enumerate(CANONICAL_RUNNERS):
    ok(
        (_yml_runners[_i] if _i < len(_yml_runners) else None) == _runner,
        f"E3.{_i+1} CI yml position {_i} is '{_runner}'",
        detail=f"got {_yml_runners[_i]!r}" if _i < len(_yml_runners) else "position missing",
    )
    ok(
        (_sh_runners[_i] if _i < len(_sh_runners) else None) == _runner,
        f"E4.{_i+1} shell script position {_i} is '{_runner}'",
        detail=f"got {_sh_runners[_i]!r}" if _i < len(_sh_runners) else "position missing",
    )


# ===========================================================================
# Section F — Seeded mutation proofs
# ===========================================================================

print("\n--- F: Seeded mutation proofs ---")

# F-A: Remove a runner from the yml list (yml missing orch4e)
_mA_yml = [r for r in _yml_runners if r != "run_phase_orch4e_tests.py"]
_mA_sh  = list(_sh_runners)
_mA_results = check_runner_list("CI yml", _mA_yml, CANONICAL_RUNNERS)
_mA_fails = [r for r in _mA_results if "missing" in r[1].lower() and not r[0]]
ok(
    len(_mA_fails) >= 1,
    "F-A mutation: removing run_phase_orch4e_tests.py from yml is detected (missing runner)",
    detail=f"expected >=1 failure, got {len(_mA_fails)}",
)
# Cross-file parity also fails
_mA_cross = check_cross_file_parity(_mA_yml, _mA_sh)
_mA_cross_fails = [r for r in _mA_cross if not r[0]]
ok(
    len(_mA_cross_fails) >= 1,
    "F-A mutation: yml/sh cross-file parity also fails when yml is missing a runner",
    detail=f"expected >=1 failure, got {len(_mA_cross_fails)}",
)

# F-B: Swap two runners in the shell script (swap orch4f and orch4e)
_mB_sh = list(_sh_runners)
if len(_mB_sh) >= 3:
    _mB_sh[1], _mB_sh[2] = _mB_sh[2], _mB_sh[1]   # swap positions 1 and 2
_mB_results = check_runner_list("shell script", _mB_sh, CANONICAL_RUNNERS)
_mB_order_fails = [r for r in _mB_results if "order" in r[1].lower() and not r[0]]
ok(
    len(_mB_order_fails) >= 1,
    "F-B mutation: swapping orch4f and orch4e in shell script is detected (order mismatch)",
    detail=f"expected >=1 failure, got {len(_mB_order_fails)}",
)
# Cross-file parity fails too
_mB_cross = check_cross_file_parity(_yml_runners, _mB_sh)
_mB_cross_fails = [r for r in _mB_cross if not r[0]]
ok(
    len(_mB_cross_fails) >= 1,
    "F-B mutation: yml/sh cross-file parity also fails on swapped shell script order",
    detail=f"expected >=1 failure, got {len(_mB_cross_fails)}",
)

# F-C: Add an extra unknown runner to the yml list
_mC_yml = list(_yml_runners) + ["run_phase_unknown_tests.py"]
_mC_results = check_runner_list("CI yml", _mC_yml, CANONICAL_RUNNERS)
_mC_extra_fails = [r for r in _mC_results if "extra" in r[1].lower() and not r[0]]
ok(
    len(_mC_extra_fails) >= 1,
    "F-C mutation: injecting unknown runner into yml is detected (extra runner)",
    detail=f"expected >=1 failure, got {len(_mC_extra_fails)}",
)
# Cross-file parity fails too
_mC_cross = check_cross_file_parity(_mC_yml, _sh_runners)
_mC_cross_fails = [r for r in _mC_cross if not r[0]]
ok(
    len(_mC_cross_fails) >= 1,
    "F-C mutation: yml/sh cross-file parity also fails when yml has extra unknown runner",
    detail=f"expected >=1 failure, got {len(_mC_cross_fails)}",
)

# F-D: Wrong first runner in yml (gate scope parity runner moved to second)
_mD_yml = list(_yml_runners)
if len(_mD_yml) >= 2:
    _mD_yml[0], _mD_yml[1] = _mD_yml[1], _mD_yml[0]   # move orch4i to position 1
_mD_results = check_runner_list("CI yml", _mD_yml, CANONICAL_RUNNERS)
_mD_first_fails = [r for r in _mD_results if "first runner" in r[1].lower() and not r[0]]
ok(
    len(_mD_first_fails) >= 1,
    "F-D mutation: moving gate scope runner from first position is detected",
    detail=f"expected >=1 failure, got {len(_mD_first_fails)}",
)

# F-F: Real data passes all checks (sanity — proves mutations are tight, not vacuous)
_real_yml_results  = check_runner_list("CI yml",       _yml_runners, CANONICAL_RUNNERS)
_real_sh_results   = check_runner_list("shell script", _sh_runners,  CANONICAL_RUNNERS)
_real_cross        = check_cross_file_parity(_yml_runners, _sh_runners)
_all_real = _real_yml_results + _real_sh_results + _real_cross
_real_failures = [r for r in _all_real if not r[0]]
ok(
    len(_real_failures) == 0,
    f"F-F sanity: all core checks pass on real (unmodified) data (checked {len(_all_real)} assertions)",
    detail=f"unexpected failures: {[r[1] for r in _real_failures]}" if _real_failures else "",
)

# F-G/H/I/J: Mutation proofs for check_canonical_count_alignment (G10 coverage).
# Proves the alignment helper catches each failure mode it is designed to prevent.
_real_count_keys = list(RUNNER_EXPECTED_COUNTS.keys())

# F-G: Remove one canonical runner from the count-map keys → "missing" check must fail.
_mG_keys = [k for k in _real_count_keys if k != "run_phase_orch4c_tests.py"]
_mG_results = check_canonical_count_alignment(CANONICAL_RUNNERS, _mG_keys)
_mG_fails = [r for r in _mG_results if "missing" in r[1] and not r[0]]
ok(
    len(_mG_fails) >= 1,
    "F-G mutation: removing a runner from count-map keys is caught by alignment 'missing' check",
    detail=f"expected >=1 failure, got {len(_mG_fails)}",
)

# F-H: Add a phantom runner to count-map keys → "extra" check must fail.
_mH_keys = _real_count_keys + ["run_phase_phantom_tests.py"]
_mH_results = check_canonical_count_alignment(CANONICAL_RUNNERS, _mH_keys)
_mH_fails = [r for r in _mH_results if "extra" in r[1] and not r[0]]
ok(
    len(_mH_fails) >= 1,
    "F-H mutation: injecting a phantom runner into count-map keys is caught by alignment 'extra' check",
    detail=f"expected >=1 failure, got {len(_mH_fails)}",
)

# F-I: Swap two count-map keys (same set, wrong order) → order check must fail.
_mI_keys = list(_real_count_keys)
if len(_mI_keys) >= 3:
    _mI_keys[1], _mI_keys[2] = _mI_keys[2], _mI_keys[1]  # swap positions 1 and 2
_mI_results = check_canonical_count_alignment(CANONICAL_RUNNERS, _mI_keys)
_mI_fails = [r for r in _mI_results if "order" in r[1] and not r[0]]
ok(
    len(_mI_fails) >= 1,
    "F-I mutation: swapping count-map key order is caught by alignment 'order' check",
    detail=f"expected >=1 failure, got {len(_mI_fails)}",
)

# F-J: Real count-map keys pass the alignment check (proves F-G/H/I are tight, not vacuous).
_real_align = check_canonical_count_alignment(CANONICAL_RUNNERS, _real_count_keys)
_real_align_failures = [r for r in _real_align if not r[0]]
ok(
    len(_real_align_failures) == 0,
    f"F-J sanity: alignment check passes on real (unmodified) data (checked {len(_real_align)} assertions)",
    detail=f"unexpected failures: {[r[1] for r in _real_align_failures]}" if _real_align_failures else "",
)


# ===========================================================================
# Section G — Regression sanity
# ===========================================================================

print("\n--- G: Regression sanity ---")

# All canonical runner files must exist in the package directory
for _runner in CANONICAL_RUNNERS:
    _runner_path = os.path.join(_HERE, _runner)
    ok(
        os.path.isfile(_runner_path),
        f"G1 canonical runner exists: {_runner}",
        detail=_runner_path,
    )

# CONTRACT_GATE.md must mention gate scope parity
_gate_doc_path = os.path.join(_HERE, "CONTRACT_GATE.md")
_gate_doc = ""
if os.path.isfile(_gate_doc_path):
    with open(_gate_doc_path, encoding="utf-8") as _f:
        _gate_doc = _f.read()
    ok(
        "scope" in _gate_doc.lower() or "parity" in _gate_doc.lower(),
        "G2 CONTRACT_GATE.md mentions gate scope or parity",
    )
    ok(
        "orch4i" in _gate_doc.lower() or "Orch-4i" in _gate_doc,
        "G3 CONTRACT_GATE.md references Orch-4i",
    )
else:
    ok(False, "G2 CONTRACT_GATE.md exists", detail=_gate_doc_path)
    ok(False, "G3 CONTRACT_GATE.md references Orch-4i")

# Both runner files are non-empty
ok(len(_yml_text) > 0, "G4 CI yml non-empty")
ok(len(_sh_text)  > 0, "G5 shell script non-empty")

# ---------------------------------------------------------------------------
# Orch-4k governance checks
# ---------------------------------------------------------------------------

# G6: Canonical runner list governance — every entry in CANONICAL_RUNNERS must
# correspond to a file that actually exists in the package directory.
# A phantom entry (runner listed but file missing) would make the gate silently
# incomplete: CI would error on the missing file, but the scope parity check
# would still "pass" because both yml and sh agree on the phantom name.
_missing_canonical = [
    r for r in CANONICAL_RUNNERS
    if not os.path.isfile(os.path.join(_HERE, r))
]
ok(
    len(_missing_canonical) == 0,
    "G6 governance: all canonical runners exist on disk (no phantom entries)",
    detail=f"missing: {_missing_canonical}" if _missing_canonical else "",
)

# G7: Non-runner slice documentation — every slice in NON_RUNNER_SLICES must be
# mentioned by name in CONTRACT_GATE.md so maintainers can find the rationale for
# why it has no standalone runner. String-level check only; no markdown parsing.
if _gate_doc:
    for _slice in NON_RUNNER_SLICES:
        ok(
            _slice in _gate_doc,
            f"G7 non-runner slice '{_slice}' documented in CONTRACT_GATE.md",
            detail=f"'{_slice}' not found — add to runner-backed vs non-runner section",
        )
else:
    for _slice in NON_RUNNER_SLICES:
        ok(
            False,
            f"G7 non-runner slice '{_slice}' documented in CONTRACT_GATE.md",
            detail="CONTRACT_GATE.md could not be read",
        )

# G8: CONTRACT_GATE.md must show the correct assertion count for this runner.
# Derives expected count from RUNNER_EXPECTED_COUNTS (single source of truth).
_g8_self = "run_phase_orch4i_tests.py"
_g8_count = RUNNER_EXPECTED_COUNTS[_g8_self]
_g8_expected_cell = f"| {_g8_count} |"
if _gate_doc:
    _orch4i_doc_rows = [
        line for line in _gate_doc.splitlines()
        if _g8_self in line and line.strip().startswith("|")
    ]
    _count_row_found = any(_g8_expected_cell in row for row in _orch4i_doc_rows)
    ok(
        bool(_orch4i_doc_rows) and _count_row_found,
        f"G8 governance: CONTRACT_GATE.md Orch-4i assertion count is {_g8_count}",
        detail=(
            f"expected '{_g8_expected_cell}' in a table row, got rows: {_orch4i_doc_rows!r}"
            if _orch4i_doc_rows
            else "Orch-4i table row not found in CONTRACT_GATE.md"
        ),
    )
else:
    ok(
        False,
        f"G8 governance: CONTRACT_GATE.md Orch-4i assertion count is {_g8_count}",
        detail="CONTRACT_GATE.md could not be read",
    )


# G9: CONTRACT_GATE.md assertion count parity for all canonical runners.
# Uses RUNNER_EXPECTED_COUNTS as the single source of truth.
# For each runner, finds all markdown table rows (| prefix) containing the
# runner filename, then asserts at least one contains the expected cell | N |.
# The any() over all matching rows is intentional: the doc has two tables that
# reference runner filenames (canonical-order table and assertion-count table),
# and the count cell only appears in the latter.
print("\n--- G9: assertion count parity for all runners ---")
for _runner_file, _expected_count in RUNNER_EXPECTED_COUNTS.items():
    _g9_cell = f"| {_expected_count} |"
    if _gate_doc:
        _g9_rows = [
            line for line in _gate_doc.splitlines()
            if _runner_file in line and line.strip().startswith("|")
        ]
        _g9_found = any(_g9_cell in row for row in _g9_rows)
        ok(
            bool(_g9_rows) and _g9_found,
            f"G9 count parity: CONTRACT_GATE.md shows {_expected_count} for {_runner_file}",
            detail=(
                f"expected '{_g9_cell}' in a table row, got: {_g9_rows!r}"
                if _g9_rows
                else f"no table row found for '{_runner_file}' in CONTRACT_GATE.md"
            ),
        )
    else:
        ok(
            False,
            f"G9 count parity: CONTRACT_GATE.md shows {_expected_count} for {_runner_file}",
            detail="CONTRACT_GATE.md could not be read",
        )


# G10: CANONICAL_RUNNERS and RUNNER_EXPECTED_COUNTS must stay aligned.
# Adding a canonical runner requires updating BOTH in the same commit.
# A mismatch here means G9 is silently missing coverage for a runner (if the
# count map is short) or asserting a count for a phantom runner (if the count
# map has extras the canonical list doesn't).
# Adding a canonical runner requires updating BOTH CANONICAL_RUNNERS and
# RUNNER_EXPECTED_COUNTS in the same commit. This check fails until both align.
print("\n--- G10: CANONICAL_RUNNERS / RUNNER_EXPECTED_COUNTS alignment ---")
_apply_results(check_canonical_count_alignment(CANONICAL_RUNNERS, list(RUNNER_EXPECTED_COUNTS.keys())))


# ===========================================================================
# Summary
# ===========================================================================

print(f"\n{'=' * 50}")
total = _PASS + _FAIL
print(f"Phase Orch-4i: {_PASS}/{total} assertions passed.")
if _FAIL:
    print(f"               {_FAIL} FAILED.")
    sys.exit(1)
else:
    print("               All assertions passed.")
    sys.exit(0)
