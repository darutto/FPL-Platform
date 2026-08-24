# OpenAI empty-response investigation — blocked at Step 1, no cause named

**Date:** 2026-08-24
**Branch:** `claude/openai-empty-response-debug-hyn3bs`
**Base:** `cc6c3d6` (main)
**Status:** **Diagnosis not completed.** Step 1 could not be performed. Per the
brief's own instruction ("If you cannot determine it from the dump, say so and
stop"), no fix was attempted.

## Why Step 1 could not be performed

Dumping the raw `responses.create` object for a failing and a succeeding
question requires a live call to `gpt-5.6-luna`. Three independent blockers:

1. **No credentials.** `packages/fpl-grounded-assistant/.env` does not exist —
   `.env` is gitignored and only `.env.template` is committed. No key-shaped
   environment variables are present in this container.
2. **No egress to the provider.** `api.openai.com:443` is refused at the
   network gateway: `CONNECT tunnel failed, response 403`. The proxy status
   endpoint reports this as a policy denial, and its allowlist covers
   `api.anthropic.com`, PyPI and npm but not OpenAI or Google. Anthropic and
   Gemini comparison runs are equally unavailable (Gemini for the same reason).
3. **The referenced evidence is absent from the repository.** Commit
   `8487f76`, branch `measure/tool-routing-confusion`, and
   `field-notes/artifacts/tool-routing-observations-2026-08-23.jsonl` do not
   exist on any ref (verified after fetching all 100+ remote branches).

The code landmarks in the brief *do* check out — `responses.create` at
`provider_client.py:1297`, `_parse_all_openai_tool_calls` at
`orchestrator.py:888`, `_extract_openai_usage` at `provider_client.py:985`,
and `gpt-5.6-luna` as a configured model. It is only the measurement evidence
and live access that are missing.

## What was established instead

With the SDKs installed and the frozen bootstrap, the *observed state* was
driven through the real orchestrator via `_orch_request_fn` injection — no
network required. Script: `packages/fpl-grounded-assistant/scripts/probe_openai_empty_response.py`.
Output: `field-notes/artifacts/openai-empty-response-probe-2026-08-24.txt`.

Three candidate shapes were tested, all with `provider="openai"`:

| shape | outcome | error | tokens | answer_text |
|---|---|---|---|---|
| A: `completed`, empty `output`, no `usage` | `no_tool` | `no tool-call block in response` | 0/0/0 | `No encontré una herramienta para responder a esto.` |
| B: `incomplete` / `max_output_tokens`, reasoning-only `output` | `no_tool` | `no tool-call block in response` | 0/0/0 | `No encontré una herramienta para responder a esto.` |
| C: response object is `None` | `no_tool` | `no tool-call block in response` | 0/0/0 | `No encontré una herramienta para responder a esto.` |

**All three reproduce the reported `outcome`, `error` and `0/0/0` tokens
exactly. None reproduces `answer_text = ''`.**

This is the finding that stops the investigation rather than advancing it:

- Every `OUTCOME_NO_TOOL` exit in `orchestrator.py` (lines 1459, 1733, 1872,
  2231) sets a non-empty answer.
- The `ask_v2` harness branch that a `no_tool` result lands in
  (`harness.py:1159`) additionally guards with
  `orch_result.answer_text or _unrecognised_message(locale)`.
- The Spanish fallback at the `no_tool` exit landed **2026-08-09** (PR #115),
  two weeks *before* the 2026-08-23 measurement. It was present when the
  measurement ran, so `''` cannot be explained as "already fixed since".

So the reported field combination — `outcome=no_tool` **and**
`error="no tool-call block in response"` **and** `answer_text=''` — is not
producible by this orchestrator at either layer. The `''` is coming from a
layer not visible here, most plausibly the missing measurement harness on
`measure/tool-routing-confusion`. (For reference, the committed experiment
harness at `scripts/run_agentic_loop_experiment.py:636` synthesises records
with hardcoded `0` token counts on worker failure — a structurally similar
"zero tokens with a success-shaped record" path, but it emits
`outcome="worker_error"` and a stderr tail, not `no_tool`/`''`.)

## Why no fix was made

The brief authorises landing observability "regardless of the root cause", and
names the empty string as the part that cannot ship. But the probe shows that
on current `main` **the empty string does not reach the user on this path**.
Building the required regression test would mean hand-writing a payload whose
production provenance I cannot establish — which the brief explicitly forbids
("do not hand-write a payload production never emits"). A speculative change to
the live provider path, untestable against the provider, is not worth the risk
here.

## The one genuine, cause-independent gap found

`_log_orch_provider_event` (`orchestrator.py:297`) keys solely on
`result.error_code is None`. A call that completes HTTP but yields no tool
call, no text and no usage is therefore logged as `provider_call_success` with
nothing recording that it yielded nothing. That matches the reported log line
and is worth closing on its own merits — but it is an observability change, not
the diagnosis, and it does not explain the `''`.

## What would unblock this

Any one of: OpenAI egress + a key in this environment; or the raw serialised
responses captured wherever the measurement was run; or the
`measure/tool-routing-confusion` branch pushed so its harness can be read.
The probe script is committed and will do the diff as soon as a live call is
possible.

## Suite baseline

`1286 passed, 1 skipped` on this branch (unmodified production code). Note this
differs from the `1274 passed, 1 skipped` quoted in the brief — main has gained
12 tests since. Environment fix required to collect at all: the container's
Debian `cryptography` needs `_cffi_backend` (`pip install cffi`), without which
45 test files fail collection with a `pyo3_runtime.PanicException`.
