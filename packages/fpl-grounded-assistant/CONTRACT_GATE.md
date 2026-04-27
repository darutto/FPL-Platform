# Contract Drift Gate — Maintainer Guide

*Added in Orch-4g. Describes the CI contract/fixture parity gate and how to maintain it.*

---

## Why this gate exists

`FINAL_RESPONSE_CONTRACT.md` and `http_contract_fixtures.json` are the two
authoritative sources of truth for the `respond()` / `FinalResponse` public
surface.  Without an automated check, edits to one file can silently diverge
from the other — field lists, orch_outcome semantics, override order, HTTP
presence invariants — without any immediate signal.

The Orch-4f runner (`run_phase_orch4f_tests.py`) is a deterministic,
read-only checker that enforces cross-file consistency as an executable test.
It runs in CI on every PR and on every push to `main`.

---

## Gate scope parity (Orch-4i)

The CI workflow (`contract-drift-gate.yml`) and the local convenience script
(`scripts/run_contract_gate.sh`) are two separate entry points for the same
gate.  Without an automated check they can silently diverge — a runner added
to one but forgotten in the other, or runners listed in different orders.

The Orch-4i runner (`run_phase_orch4i_tests.py`) is a pure string-based
checker that runs **first** in both files and verifies they enumerate the exact
same runner files in the exact same order.  If either file drifts from the
canonical list, Orch-4i fails before any semantic runner executes.

**Canonical runner order** (enforced by Orch-4i):

| Position | Runner | Role |
|----------|--------|------|
| 1 | `run_phase_orch4i_tests.py` | Gate scope parity (this checker — must be first) |
| 2 | `run_phase_orch4f_tests.py` | Contract/fixture drift |
| 3 | `run_phase_orch4e_tests.py` | orch_outcome contract parity |
| 4 | `run_phase_orch4d_tests.py` | squad_context override parity |
| 5 | `run_phase_orch4c_tests.py` | Orchestration audit parity |
| 6 | `run_phase_orch4a_tests.py` | Orchestration enable/disable flag parity |
| 7 | `run_phase_orch4b_tests.py` | orch_outcome serialization parity |

Four seeded mutation proofs in Orch-4i (F-A through F-D) verify:
- F-A: Missing runner in yml → detected
- F-B: Swapped runner order in shell script → detected
- F-C: Extra unknown runner in yml → detected
- F-D: Gate scope parity runner not first → detected

---

## Runner-backed slices vs non-runner slices

Not every stabilization slice has a standalone runner file.  Some slices are
implemented entirely as configuration changes (CI wiring, shell scripts, docs)
and are therefore not in the canonical gate list.  This table is the definitive
register — Orch-4i asserts that each non-runner slice is mentioned here by name.

| Slice | Runner file exists? | In canonical gate list? | Reason |
|-------|--------------------|-----------------------|--------|
| Orch-4g | No | No | Implemented as CI workflow + local script config only; the gate *is* the artifact |
| Orch-4h | No | No | `session_id` envelope invariant is enforced inside Orch-4f (Section A2); no separate runner needed |

**Update rule:** if a standalone runner is later created for a non-runner slice,
it must be added to `CANONICAL_RUNNERS` in `run_phase_orch4i_tests.py`, the CI
workflow, and the local shell script **in the same commit**.  Orch-4i will fail
in CI until all three are updated.

---

## What the gate catches

The gate runs seven runners in sequence.  Each runner exits nonzero on failure,
which causes CI to fail immediately.

| Runner | Assertions | What it catches |
|--------|-----------|----------------|
| `run_phase_orch4i_tests.py` | 70 | Gate scope parity: CI yml and shell script enumerate the same runners in the same order |
| `run_phase_orch4f_tests.py` | 125 | Cross-file drift: stable field parity, orch_outcome vocabulary parity, HTTP always-present claim, override-order completeness, independence invariants, deferred note parity, conditional field coverage, HTTP status contract |
| `run_phase_orch4e_tests.py` | 122 | Runtime orch_outcome semantics: field presence, value on all 6 non-OK outcomes, independence from `outcome`, override-ordering proof, depth-bypass deferred invariant |
| `run_phase_orch4d_tests.py` | 84 | squad_context override parity: `_apply_squad_overrides` is the single source of truth on both deterministic and orch-success paths |
| `run_phase_orch4c_tests.py` | 120 | Orchestration audit parity: all 6 non-OK outcomes serialized consistently across CLI, HTTP, and session surfaces |
| `run_phase_orch4a_tests.py` | 193 | Orchestration enable/disable: `FPL_ORCH_ENABLED` gates correctly, deterministic path unaffected, provider/model constants stable |
| `run_phase_orch4b_tests.py` | 239 | orch_outcome serialization: values serialize consistently across CLI, HTTP, and session surfaces for all supported intents |

### Specific drift Orch-4f catches (by section)

- **A** — A field added to the FinalResponse stable contract table but not to `response_stable_fields` in the fixture (or vice versa).
- **A2** — `session_id` HTTP-envelope boundary violation: `session_id` must be present in the session endpoint stable fields, absent from the ask endpoint stable fields, and absent from the FinalResponse contract table. See [session_id envelope invariant](#session_id-http-envelope-only-invariant) below.
- **B** — A new non-OK `orch_outcome` string added to the orchestrator but not documented in both files.
- **C** — `always_present_in_json` changed to `false`, or the contract doc no longer asserting HTTP always-present behavior.
- **D** — An override type (`budget_constraint`, `hit_warning`, `chip_unavailable`) renamed or removed without updating both files; missing step numbers; `_apply_squad_overrides` renamed.
- **E** — Independence invariant text removed from either file.
- **F** — Deferred note for `sub_responses[i].orch_outcome` removed from the Out of Scope table.
- **G** — A conditional metadata field added to `FinalResponse` but not documented in the fixture `response_conditional_fields`.
- **H** — The fixture no longer lists `http_contract_fixtures.json` as the HTTP authority in the contract doc.
- **I** — Mutation proof: 7 seeded mutations verified to be caught (proves the checker is not vacuous, includes I-G and I-H for the session_id envelope).

---

## `session_id` HTTP-envelope-only invariant

`session_id` is added by the HTTP server layer (`SessionAskResponse`), not by `respond()` /
`FinalResponse`.  It is therefore intentionally exempt from the cross-file parity check that
compares `FinalResponse` contract table fields against fixture `response_stable_fields`.

Three invariants are enforced by Section A2 of `run_phase_orch4f_tests.py`:

| Invariant | Why |
|-----------|-----|
| `session_id` IS in session endpoint stable fields (`POST /session/{id}/ask`) | HTTP clients need it to correlate responses to sessions. |
| `session_id` is NOT in ask endpoint stable fields (`POST /ask`) | `POST /ask` is stateless; no session exists. |
| `session_id` is NOT in the FinalResponse contract table | It is an HTTP envelope field, not a `FinalResponse` field. `FinalResponse.respond()` never sets it. |

The derived superset invariant (`session endpoint ⊇ ask endpoint`) is also enforced: every field
in `POST /ask` stable fields must also appear in `POST /session/{id}/ask` stable fields.

Two seeded mutation proofs (I-G, I-H) verify that violations are caught:

- **I-G** — Inject `session_id` into ask endpoint stable fields → A2 "absent from ask endpoint" check fails.
- **I-H** — Remove `session_id` from session endpoint stable fields → A2 "present in session endpoint" check fails.

### When to update

If you add a new HTTP-envelope-only field (a field added by the server layer, not by `FinalResponse`),
add it to the `_HTTP_ENVELOPE_ONLY` set in `check_stable_field_parity` and add a corresponding
assertion in `check_session_id_envelope`. Orch-4f Section A2 will fail until both are updated.

---

## How to run locally before pushing

From the repo root, with the venv activated:

```bash
cd packages/fpl-grounded-assistant

# Run the full gate (same order as CI)
python run_phase_orch4i_tests.py   # gate scope parity (fast, stdlib only)
python run_phase_orch4f_tests.py   # doc/fixture drift check (fast, no imports)
python run_phase_orch4e_tests.py   # orch_outcome contract parity
python run_phase_orch4d_tests.py   # squad_context override parity
python run_phase_orch4c_tests.py   # orchestration audit parity
python run_phase_orch4a_tests.py   # orchestration enable/disable flag parity
python run_phase_orch4b_tests.py   # orch_outcome serialization parity
```

Or use the convenience script at the repo root:

```bash
bash scripts/run_contract_gate.sh
```

No API key is required. All runners disable orchestration and mock LLM calls.

---

## When to update the gate

| Change | What to update |
|--------|---------------|
| Add a new field to `FinalResponse` | Add to contract table + fixture `response_stable_fields`. Orch-4f A will fail until both are updated. |
| Add a new non-OK `orch_outcome` string | Add to `orchestrator.py` constants, re-export in `final_response.py`, document in contract table and fixture `orch_outcome_contract.values`. Orch-4f B will fail until both are updated. |
| Add a new conditional metadata field | Add to fixture `response_conditional_fields` and document in contract doc. Orch-4f G will fail until both are updated. |
| Add a new squad_context override | Add to `_apply_squad_overrides`, document in override order table in contract, add `override_invariant` note in fixture. Orch-4f D and Orch-4d will fail until updated. |
| Rename `_apply_squad_overrides` | Update the contract doc reference. Orch-4f D will fail. |
| Add a new HTTP-envelope-only field | Add to `_HTTP_ENVELOPE_ONLY` in `check_stable_field_parity` and add assertion in `check_session_id_envelope`. Orch-4f A2 will fail until updated. |
| Add a new runner to the gate | Add to CI yml, shell script, and `CANONICAL_RUNNERS` in `run_phase_orch4i_tests.py` in the same position. Orch-4i will fail until all three are updated. |
| Reorder gate runners | Update the order in CI yml, shell script, and `CANONICAL_RUNNERS` consistently. Orch-4i will fail until all three match. |
| Promote a non-runner slice to a runner | Create the runner file, add to CI yml + shell script + `CANONICAL_RUNNERS` in the same commit, and remove from the non-runner table above. Orch-4i will fail until all four are updated. |
| Add a new non-runner slice | Add a row to the non-runner table above. Orch-4i G7 check will fail until it is documented here. |

---

## Dependencies and environment

The gate requires only:

```
pip install -r packages/fpl-grounded-assistant/requirements.txt
```

No additional packages. No API keys. No network access at runtime.

The Orch-4i runner (`run_phase_orch4i_tests.py`) imports only Python stdlib
(`re`, `os`, `sys`) and reads two files from the repo root. It can run without
any pip install at all.

The Orch-4f runner (`run_phase_orch4f_tests.py`) imports only Python stdlib
(`json`, `re`, `os`, `sys`, `copy`) and reads two files from the package
directory. It can run without any pip install at all.

The Orch-4e/4d/4c runners import from `fpl_grounded_assistant` and its sibling
packages. They self-manage `sys.path` using `os.path` relative to the runner
file location, so no `PYTHONPATH` export is required when run from within
`packages/fpl-grounded-assistant/`.

---

## Architecture note

The gate enforces stabilization only.  It does not test:

- Live FPL API calls (fixtures use injected bootstrap)
- LLM-generated text quality (deterministic review gate handles this)
- End-to-end HTTP surface (see `http_contract_fixtures.json` for machine-readable shapes)

It is intentionally narrow: no runtime behavior is touched, and no production
code is executed by the drift checker itself.
