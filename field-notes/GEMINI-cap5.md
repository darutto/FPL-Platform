# Agentic loop experiment results

## Pinned configuration

- Generated: 2026-08-22T14:21:52.642330+00:00
- Bootstrap: `C:\Users\thera\fpl-platform\.claude\worktrees\agentic-loop\field-notes\artifacts\agentic-loop-bootstrap-2026-08-18.json`
- Bootstrap SHA-256: `4cbb9fa18a5852c73a54fbe24a03b34e0c33ae5b3c549171cbcb02568d8b2aae`
- Bootstrap captured at: `2026-08-19T02:43:43.220549+00:00`
- Bootstrap fixture coverage: `{"fixtures_dropped_no_event": 0, "fixtures_returned": 380, "fixtures_scheduled": 380, "gameweeks_covered": 38, "teams_with_fixtures": 20}`
- Providers: `gemini` @ `gemini-3.5-flash`
- max_tokens: `4096`. Sampling per provider (temperature / top_p): gemini `0.0` / `1.0`.
- OpenAI's GPT-5.6 family rejects temperature and top_p (HTTP 400), so those observations run at the model's default sampling rather than pinned determinism. Treat cross-provider variance accordingly.
- Anthropic decoding default not otherwise overridden: extended thinking off.
- Gemini decoding default not otherwise overridden: thinking level `medium`.
- Evaluator: same-provider cheapest model, verdict-only; no primary retry
- FPL_ORCH_MAX_ROUNDS: `5` tool-execution rounds
- Repetitions per critical scenario/configuration: `3`
- Scope: direct `ask_orchestrated`; not an end-to-end UI/session test
- Cost note: evaluator tokens are combined by the current API and conservatively charged at output price.
- Price sources: https://platform.claude.com/docs/en/about-claude/pricing , https://ai.google.dev/gemini-api/docs/pricing and https://developers.openai.com/api/docs/models/

### Model pricing used (USD per 1M tokens)

```json
{
  "claude-haiku-4-5-20251001": {
    "cache_read": 0.1,
    "input": 1.0,
    "output": 5.0
  },
  "gemini-3.5-flash": {
    "cache_read": 0.15,
    "input": 1.5,
    "output": 9.0
  },
  "gpt-4o-mini": {
    "cache_read": 0.075,
    "input": 0.15,
    "output": 0.6
  },
  "gpt-5.6-luna": {
    "cache_read": 0.02,
    "input": 0.2,
    "output": 1.2
  },
  "gpt-5.6-sol": {
    "cache_read": 0.5,
    "input": 5.0,
    "output": 30.0
  },
  "gpt-5.6-terra": {
    "cache_read": 0.2,
    "input": 2.0,
    "output": 12.0
  }
}
```

## Three separate axes

- Axis 1: user-visible catastrophic failure versus substantive answer.
- Axis 2: deterministic legality; `structured_output_missing` is never treated as invalid.
- Axis 2 is grouped by source. Raw-tool fallbacks never share a pass rate with model JSON; their bootstrap-synthesized price and arithmetic checks are non-comparable.
- Axis 3: human semantic score using the scenario-specific rubric; legality is not a proxy.

## Summary

| Provider / model | Arm | Scenario | Catastrophic rate | Axis 2 | Composition | Human semantic | Avg rounds | Avg tokens | Avg USD |
|---|---|---|---:|---|---|---|---:|---:|---:|
| gemini / gemini-3.5-flash | D loop+prompt | Q10 | 3/3 | {"none": {"structured_output_missing": 3}} | ✓0 ✗3 | pending | 5.00 | 86266 | 0.145513 |
| gemini / gemini-3.5-flash | D loop+prompt | Q11 | 3/3 | {"none": {"structured_output_missing": 3}} | ✓0 ✗3 | pending | 5.00 | 80986 | 0.129507 |

## Answers: gemini / gemini-3.5-flash

### Q10

¿Qué media es la mejor opción en el rango de precio entre 6.0m y 8.0m para los próximos 5 partidos? Justifica tu respuesta según el fixture.

Human rubric: Names a MID £6.0m-£8.0m, justifies via fixture difficulty and form.

#### Repetition 1

| Arm | Outcome | Axis 1 | Axis 2 source/status | Axis 3 | Rounds / tools | Tokens / USD | Answer |
|---|---|---|---|---|---|---|---|
| D loop+prompt | ok | catastrophic_failure | none / structured_output_missing | pending_human_review | 5 / get_transfer_suggestion → get_player_fixture_run → get_player_fixture_run → get_player_fixture_run → get_player_fixture_run → get_player_snapshot → get_player_fixture_run → compare_players → compare_players | 86266 / $0.145516 | <details><summary>answer</summary>Respuesta incompleta (round limit reached): Gibbs-White (48.65) edges Bruno G. (48.14) — narrow margin (0.51).  Advantages: set-piece advantage (pen2).</details> |
#### Repetition 2

| Arm | Outcome | Axis 1 | Axis 2 source/status | Axis 3 | Rounds / tools | Tokens / USD | Answer |
|---|---|---|---|---|---|---|---|
| D loop+prompt | ok | catastrophic_failure | none / structured_output_missing | pending_human_review | 5 / get_transfer_suggestion → get_player_fixture_run → get_player_fixture_run → get_player_fixture_run → get_player_fixture_run → get_player_snapshot → get_player_fixture_run → compare_players → compare_players | 86253 / $0.145399 | <details><summary>answer</summary>Respuesta incompleta (round limit reached): Gibbs-White (48.65) edges Bruno G. (48.14) — narrow margin (0.51).  Advantages: set-piece advantage (pen2).</details> |
#### Repetition 3

| Arm | Outcome | Axis 1 | Axis 2 source/status | Axis 3 | Rounds / tools | Tokens / USD | Answer |
|---|---|---|---|---|---|---|---|
| D loop+prompt | ok | catastrophic_failure | none / structured_output_missing | pending_human_review | 5 / get_transfer_suggestion → get_player_fixture_run → get_player_fixture_run → get_player_fixture_run → get_player_fixture_run → get_player_snapshot → get_player_fixture_run → compare_players → compare_players | 86278 / $0.145624 | <details><summary>answer</summary>Respuesta incompleta (round limit reached): Gibbs-White (48.65) edges Bruno G. (48.14) — narrow margin (0.51).  Advantages: set-piece advantage (pen2).</details> |
### Q11

¿Qué defensa es la mejor opción en el rango de precio entre 4.5m y 6.0m para los próximos 5 partidos? Justifica tu respuesta según el fixture.

Human rubric: Names a DEF £4.5m-£6.0m, justifies via fixture difficulty and clean-sheet risk.

#### Repetition 1

| Arm | Outcome | Axis 1 | Axis 2 source/status | Axis 3 | Rounds / tools | Tokens / USD | Answer |
|---|---|---|---|---|---|---|---|
| D loop+prompt | ok | catastrophic_failure | none / structured_output_missing | pending_human_review | 5 / get_transfer_suggestion → get_player_fixture_run → get_player_fixture_run → get_player_fixture_run → get_player_fixture_run → get_player_snapshot → get_player_snapshot → get_player_snapshot | 80990 / $0.129540 | <details><summary>answer</summary>Respuesta incompleta (round limit reached): **Van Hecke** (TOT, DEF)<br>  Precio: £5.0m &#124; Propiedad: 9.0% &#124; Estado: Available<br>  Pts totales: 148 &#124; PPG: 4.1 &#124; Forma: 0.0<br>  xG: 3.31 &#124; xA: 1.57 &#124; xGI: 4.87 &#124; ICT: 152.0<br>  Minutos: 3210</details> |
#### Repetition 2

| Arm | Outcome | Axis 1 | Axis 2 source/status | Axis 3 | Rounds / tools | Tokens / USD | Answer |
|---|---|---|---|---|---|---|---|
| D loop+prompt | ok | catastrophic_failure | none / structured_output_missing | pending_human_review | 5 / get_transfer_suggestion → get_player_fixture_run → get_player_fixture_run → get_player_fixture_run → get_player_fixture_run → get_player_snapshot → get_player_snapshot → get_player_snapshot | 80994 / $0.129576 | <details><summary>answer</summary>Respuesta incompleta (round limit reached): **Van Hecke** (TOT, DEF)<br>  Precio: £5.0m &#124; Propiedad: 9.0% &#124; Estado: Available<br>  Pts totales: 148 &#124; PPG: 4.1 &#124; Forma: 0.0<br>  xG: 3.31 &#124; xA: 1.57 &#124; xGI: 4.87 &#124; ICT: 152.0<br>  Minutos: 3210</details> |
#### Repetition 3

| Arm | Outcome | Axis 1 | Axis 2 source/status | Axis 3 | Rounds / tools | Tokens / USD | Answer |
|---|---|---|---|---|---|---|---|
| D loop+prompt | ok | catastrophic_failure | none / structured_output_missing | pending_human_review | 5 / get_transfer_suggestion → get_player_fixture_run → get_player_fixture_run → get_player_fixture_run → get_player_fixture_run → get_player_snapshot → get_player_snapshot → get_player_snapshot | 80975 / $0.129405 | <details><summary>answer</summary>Respuesta incompleta (round limit reached): **Van Hecke** (TOT, DEF)<br>  Precio: £5.0m &#124; Propiedad: 9.0% &#124; Estado: Available<br>  Pts totales: 148 &#124; PPG: 4.1 &#124; Forma: 0.0<br>  xG: 3.31 &#124; xA: 1.57 &#124; xGI: 4.87 &#124; ICT: 152.0<br>  Minutos: 3210</details> |

## Decision gate

Do not call this launch-ready, buy paid data, or collapse the arms into one headline. If C/D pass simple retrieval but fail legality or the human semantic rubrics for Q6/Q7/Q9, the next milestone is a decision-layer constraint solver, not Sportmonks.
