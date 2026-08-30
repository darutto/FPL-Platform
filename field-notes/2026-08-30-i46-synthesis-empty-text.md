# i46 — the synthesis call is not running out of budget. It is calling another tool.

**2026-08-30.** Base `8ddd734` (origin/main). Provider/model passed explicitly:
`openai` / `gpt-5.6-luna`, every call's `fpl_provider_event` checked against
them. Bootstrap frozen: `agentic-loop-bootstrap-2026-08-18.json`, sha256
`4cbb9fa18a5852c73a54fbe24a03b34e0c33ae5b3c549171cbcb02568d8b2aae`.
10 calls, **$0.0265**, 0 exceptions.

Instrument: `scripts/measure_i46_synthesis_instrument.py`. Data:
`field-notes/artifacts/i46-instrument-probe-2026-08-30.jsonl`.

**This is Step 1 only. The six-arm payload×budget experiment was NOT run**, on
the brief's own instruction: instrument first, and if that answers the
question, stop and report instead of spending. It answered the question.

## What was measured

Nobody had ever looked at `finish_reason` or the usage breakdown on the
synthesis call. `OrchCallResult` carries `input_tokens` / `output_tokens` /
`cache_read_tokens` and nothing else — no finish reason, no reasoning-token
split — so the standing hypothesis ("a reasoning model burns its output budget
thinking and never emits text") had never been tested against a single
observation.

The instrument wraps `call_orch_provider` in the orchestrator's own module
namespace for the duration of one `ask_orchestrated()` call and records, per
provider call: `status`, `incomplete_details.reason`, `usage.input_tokens`,
`usage.output_tokens`, `usage.output_tokens_details.reasoning_tokens`,
`usage.input_tokens_details.cached_tokens`, the **types of the output items**,
the bytes of tool payload actually serialized into the request, and whether the
product's own `_extract_text_from_response` would find text. The wrapper is
removed in a `finally`, so a crash cannot leave the product patched.

10 reps of `gw-04` — the confirmed repro, 6/9 across three battery runs — at
the production budget of 1024.

## Result: both leading explanations are dead

```
rep   bytes  maxtok       finish   incomplete  out_tok  reason_tok  text  output items
  0     167    1024    completed         None      107          73 False  reasoning,function_call
  1     167    1024    completed         None      218         177 False  reasoning,function_call
  2     167    1024    completed         None       98          59 False  reasoning,function_call
  3     167    1024    completed         None       81          39 False  reasoning,function_call
  4     289    1024    completed         None      153         101  True  reasoning,message
  5    4452    1024    completed         None      213         180 False  reasoning,function_call
  6     167    1024    completed         None       63          21 False  reasoning,function_call
  7     196    1024    completed         None      102          69 False  reasoning,function_call
  8     289    1024    completed         None      191         157 False  reasoning,function_call
  9    4367    1024    completed         None      214         196 False  reasoning,function_call
```

**Every single synthesis call finished cleanly.** `status == "completed"` 10/10,
`incomplete_details.reason == None` 10/10. The largest output was 218 tokens —
**21% of the 1024 budget**. Not one call came within 4x of the ceiling.

The difference between the one call that produced text and the nine that did
not is visible in the last column and nowhere else:

| output items | n | text extracted |
|---|---|---|
| `reasoning, message` | 1 | yes |
| `reasoning, function_call` | 9 | **no** |

The synthesis call is not failing. It is **emitting another `function_call`** —
the model wants to call a second tool — and the single-round path has no round
to give it. `orchestrator.py` looks only for text, finds none, logs *"synthesis
LLM call succeeded but returned no text"*, and falls through to the
deterministic `render()` of the first tool. That is the raw table the user sees.

`rounds_used == 0` on all 10. `is_orch_loop_enabled()` reads
`FPL_ORCH_LOOP_ENABLED`, which is **off by default** and is not set locally, so
this is the single-round path — one primary call, one synthesis call, no
capacity for a follow-up tool call by construction.

### H-presupuesto (`max_tokens`) — falsified, and not marginally

0/10 calls were truncated. Raising `max_tokens` cannot fix a call that used 21%
of what it already had. **The one-line server change is not the mitigation**;
had the six arms been run, they would have bought ~$0.35 of evidence for a
hypothesis that ten calls refute outright.

### H-payload — unsupported on this evidence

Payload ranged 167 B → 4452 B, a 27x spread, inside one question. Both the
smallest (167 B) and the largest (4452 B) failed. The single success sat at
289 B, mid-range. There is no monotone relationship here to find.

The captaincy track's counter-evidence now has a mechanism rather than just a
shrug: payload size was never the axis.

### The confound in `gw-04`, stated plainly

6 of the 10 turns had `tool_output_status != "ok"` — `web_fetch` returning
HTTP 404 — and a model that reacts to a failed fetch by trying a different URL
is behaving *sensibly*. Those 6 are contaminated as evidence about synthesis.

The four turns whose tool actually succeeded are the clean ones, and they carry
the finding on their own:

```
rep4  get_gameweek_context   289 B   out 153  reasoning,message         -> text
rep5  web_fetch             4452 B   out 213  reasoning,function_call   -> NO TEXT
rep8  get_gameweek_context   289 B   out 191  reasoning,function_call   -> NO TEXT
rep9  web_fetch             4367 B   out 214  reasoning,function_call   -> NO TEXT
```

3/4 successful-tool turns still lost their synthesis. rep4 and rep8 are the
same tool, the same 289 bytes, the same budget — one spoke, one called another
tool. **The behaviour is nondeterministic at identical inputs**, which is why 3
reps were never going to be enough and why 10 were specified.

## What this does not settle

- **Tool identity remains confounded.** Deliberately: this probe was one
  question. It says nothing about why `get_gameweek_context` failed 2/4 in the
  captaincy track versus `get_my_squad` at 0/6. Do not read this note as
  closing all three factors — it closes budget, weakens payload, and leaves
  identity exactly where it was.
- **Generality is unmeasured.** 10 calls, one question, one model. The 5.2%
  battery-wide rate is not re-derived here. What is established is the
  *mechanism* on a confirmed repro, not its share of all failures.
- **Whether prod sets `FPL_ORCH_LOOP_ENABLED`** could not be verified from this
  worktree. It is absent from the local `.env` and undocumented in-repo. If
  Railway sets it, the bounded loop path needs the same instrumentation before
  any of this transfers. **Check this before designing the fix.**

## Two collateral findings about the instruments

1. **`golden_battery.py`'s `--max-tokens` flag is inert.** It defaults to 1024,
   is printed into the report header, and is never passed to anything:
   `base.run_one()` hardcodes `max_tokens=1024` inline. Running
   `--max-tokens 4096` produces a report that *says* 4096 over calls made at
   1024. A pinned header that can disagree with the run is worse than no
   header. (Not touched here — this note is an instrument, not a gate, and
   must not disturb i25's reference row.)

2. **The "all probes ran at 2048" premise is stale.** `measure_tool_routing.py`
   has pinned `max_tokens=1024` since `2555dc9` (2026-08-25), and every probe —
   i41, the squad-routing verify, the golden battery — goes through
   `base.run_one`. The i25 battery and the i41 probe both already ran at the
   production budget. The "we measured the favourable case at double the real
   budget" framing in `2026-08-28-captain-answer-nondeterminism-prod.md` and on
   the i46 card describes the pre-08-25 state and should be corrected: the
   5.2% **is** the production-budget rate.

## Where to go next

The question is no longer *why is there no text*. It is **what should happen
when the synthesis call asks for another tool**, on a path built to allow
exactly one. Three shapes, not costed here:

- honour one follow-up round on the single-round path (converges it toward
  `_run_bounded_loop`, which already handles this);
- feed the refusal back and re-ask for prose;
- keep the fallback but stop rendering a raw table when the model's actual
  output was "I need another tool".

The first is the least new machinery and the most existing precedent. Choosing
between them is a design decision, not a measurement one, and this note does
not make it.
