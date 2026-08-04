# FI-7e deterministic demo evidence

Accepted source: `main@119f5e601456a928ad83cb5965e219e85c0e8ff8`. Frozen fixture: `fi7e-demo-input-v1`; clock: `2026-08-01T12:00:00Z`.

This directory joins canonical backend artifacts to captures of the unchanged FI-7d presentation. `manifest.json` is the authoritative linkage record; `backend-trace.json` records observations and evaluated assertions; `responses.json` contains the exact served payloads. `test-results.json` and `test-summary.txt` record the mandatory focused executions. Scenario C is checked in `recommendation-equality.json`. Scenario E is a deserialization/render replay, not a second prompt evaluation.

The silent WebM is external by contract: [download the immutable corrected recording](https://github.com/darutto/FPL-Platform/releases/download/fi7e-demo-real-6f95d39/fi7e-demo-real-6f95d39.webm). Its byte hash and complete media metadata are pinned in `manifest.json`.

Reviewer entry points:

```text
python scripts/capture_fi7e_demo.py --fixture tests/fixtures/fi7e_demo_inputs.json --output <fresh-empty-directory>
python scripts/serve_fi7e_demo.py --responses <output>/responses.json --host 127.0.0.1 --port 8765
sha256sum -c fi7e_evidence/SHA256SUMS
```

The capture command refuses a dirty tree, executes the real captain, comparison, multi-intent, enrichment-failure, validated-v2 loader/evaluator, runtime-compositor, and replay paths, and fails unless the focused Python suite reports 75 passes and the FI-7d UI suite reports 43 passes. The unchanged FI-7d components were captured through a disposable component-level render route against the loopback fixture payloads; that route and its dependency shim are not part of this package. The production Clerk middleware guard was never modified or bypassed. The over-eight input, exact duplicate collapse, and first-occurrence rule are causal test evidence. Railway is not used. No WebM, production change, credential, user/session datum, FI-7f resource, `@minutes`, or `@role` is stored here.
