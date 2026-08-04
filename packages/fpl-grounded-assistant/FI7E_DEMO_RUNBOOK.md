# FI-7e deterministic demo runbook

Authoritative source is `119f5e601456a928ad83cb5965e219e85c0e8ff8`; fixture clock is `2026-08-01T12:00:00Z`. Only loopback is permitted. The fixture server and UI are separate long-lived processes.

## PowerShell

```powershell
git fetch origin --prune
git checkout --detach <accepted-artifact-sha>
git status --porcelain=v1 --untracked-files=all
git rev-parse HEAD
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r packages\fpl-grounded-assistant\requirements.txt -r packages\football-intelligence\requirements.txt
Push-Location packages\fpl-ui; npm ci; Pop-Location
$out='C:\tmp\fi7e-rerun-<short-sha>'
.\.venv\Scripts\python.exe packages\fpl-grounded-assistant\scripts\capture_fi7e_demo.py --fixture packages\fpl-grounded-assistant\tests\fixtures\fi7e_demo_inputs.json --output $out
```

Terminal 1:

```powershell
.\.venv\Scripts\python.exe packages\fpl-grounded-assistant\scripts\serve_fi7e_demo.py --responses 'C:\tmp\fi7e-rerun-<short-sha>\responses.json' --host 127.0.0.1 --port 8765
```

Terminal 2:

```powershell
$env:FPL_BACKEND_URL='http://127.0.0.1:8765'
Push-Location packages\fpl-ui; npm run dev; Pop-Location
```

Capture A–F in order with Chromium 100% zoom, dark theme, DPR 1, at 1440×900 and B additionally at 390×844. Wait for responses and reduced-motion stability. Stop both foreground processes with `Ctrl+C`, never a broad process kill. Then run:

```powershell
Push-Location packages\fpl-grounded-assistant
..\..\.venv\Scripts\python.exe -m pytest tests\test_fi7b1_tool_shells.py tests\test_fi7b2_runtime_integration.py tests\test_fi7b3_rendering_session_evidence.py tests\test_fi7c_existing_intent_evidence.py
Pop-Location
Push-Location packages\fpl-ui
npm test -- --runInBand __tests__\fi7d-evidence-ui.test.tsx
npm test -- --runInBand
npx tsc --noEmit
npm run build
Pop-Location
& 'C:\Program Files\Git\bin\bash.exe' 'scripts/run_contract_gate.sh'
git diff --check
git status --porcelain=v1 --untracked-files=all
```

## POSIX

```sh
git fetch origin --prune && git checkout --detach <accepted-artifact-sha>
git status --porcelain=v1 --untracked-files=all && git rev-parse HEAD
python3 -m venv .venv
.venv/bin/python -m pip install -r packages/fpl-grounded-assistant/requirements.txt -r packages/football-intelligence/requirements.txt
(cd packages/fpl-ui && npm ci)
out=/tmp/fi7e-rerun-<short-sha>
.venv/bin/python packages/fpl-grounded-assistant/scripts/capture_fi7e_demo.py --fixture packages/fpl-grounded-assistant/tests/fixtures/fi7e_demo_inputs.json --output "$out"
```

Terminal 1 runs `.venv/bin/python packages/fpl-grounded-assistant/scripts/serve_fi7e_demo.py --responses "$out/responses.json" --host 127.0.0.1 --port 8765`. Terminal 2 runs `cd packages/fpl-ui && FPL_BACKEND_URL=http://127.0.0.1:8765 npm run dev`. Use the same capture and validation matrix; run `bash scripts/run_contract_gate.sh` from the repository root.

## Artifact and privacy verification

Regenerate JSON only with the Python capture command into a new empty directory and byte-compare it. Verify `sha256sum -c packages/fpl-grounded-assistant/fi7e_evidence/SHA256SUMS`; use `ffprobe` for PNG/WebM dimensions and codec, and download/hash the external WebM. Check JSON files have their recorded byte lengths, no trailing newline, and canonical SHA-256. Scan with `rg -n -i 'token|key|auth|cookie|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|sportmonks|understat|railway|vercel|[A-Z]:\\Users\\|/home/|https?://(?!127\.0\.0\.1|localhost|github\.com)' <FI-7e paths>` and manually review every match. Confirm zero unresolved findings. Remove only the rerun directory and stop only owned processes.

## Adversarial detection matrix

| misleading mutation | detecting artifact | detecting command or assertion | expected failure |
|---|---|---|---|
| stale SHA | environment/fixture | capture SHA check | capture exits nonzero |
| dirty worktree | capture runner | full porcelain check | capture exits nonzero |
| live provider data | runner/redaction | provider-env guard and scan | blocked |
| non-loopback socket | fixture server | bind/client checks | 403 or startup failure |
| post-capture JSON edit | manifest/SHA256SUMS | canonical regeneration and checksum | hash mismatch |
| response/hash mismatch | manifest | byte-length and SHA assertion | assertion fails |
| trailing newline drift | manifest | recorded byte length/hash | hash mismatch |
| Unicode reserialization | manifest | direct-Unicode regeneration | hash mismatch |
| numeric representation change | equality/manifest | canonical byte compare | hash mismatch |
| missing OFF or ON scenario | trace | required scenario-ID set | assertion fails |
| evidence without execution proof | trace | B order/count assertions | assertion fails |
| repeated/reordered M1/M2/M3 | trace/focused tests | exact `M1,M2,M3` and count=1 | assertion fails |
| M4/M5 execution | trace | both counts zero | assertion fails |
| replay as reevaluation | responses/trace | stored/replay hash plus zero replay counters | assertion fails |
| replay nonzero FI counts | trace | replay module/tool/enrichment zero | assertion fails |
| hidden parent payload or parent aggregation | responses/trace | parent omission and child-owner assertion | assertion fails |
| merged child lists | responses | separate ordered child arrays | assertion fails |
| recommendation change outside `/evidence` | equality | full canonical comparison after only evidence removal | unexpected diff |
| null/omission collapse or array reorder | equality | canonical whole-object compare | hash/diff failure |
| internal ID exposure | screenshots/redaction | visual and text scan | unresolved finding |
| desktop-only or responsive mismatch | screenshots | required file/dimension and B item-order check | artifact missing/mismatch |
| missing zero confidence or source fallback | B screenshots/UI test | visible text assertions | test/review failure |
| hidden failure or swallowed primary | F screenshot/focused tests | primary visible and boundary-null assertions | failure |
| UI FI request | trace/UI test | UI request count zero/source scan | assertion fails |
| secret/personal data | redaction statement | deterministic scan/manual review | blocks acceptance |
| checksum missing/mismatch | SHA256SUMS | `sha256sum -c` | nonzero |
| inaccessible/unhashed WebM | manifest | download then byte hash | blocks acceptance |
| committed WebM | Git path review | `git ls-files '*.webm'` empty | scope failure |
| Railway reliance | known issues/server | fixture backend URL assertion | scope failure |
| FI-7f, `@minutes`, or `@role` | trace/path scan | absence assertions | scope failure |

On failure preserve raw output outside `fi7e_evidence`, record command/exit/SHA and classify product regression, fixture drift, environment, or recording-only. Never hand-edit generated JSON. A recording-only rerun is allowed only with unchanged canonical hashes; any accepted rerun requires the separately reviewed `fi7e_evidence_rerun_<YYYYMMDD>_<short-sha>` directory.
