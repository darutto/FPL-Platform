# Golden battery — gpt-5.6-luna

Diffable: two models compare by reading two of these tables, with no re-run.

| field | value |
|---|---|
| model | `gpt-5.6-luna` |
| provider | `openai` |
| tier | `controls` |
| reps | 3 |
| max_tokens | 1024 |
| temperature | None (unset) |
| bootstrap | `agentic-loop-bootstrap-2026-08-18.json` |
| bootstrap sha256 | `4cbb9fa18a5852c73a54fbe24a03b34e0c33ae5b3c549171cbcb02568d8b2aae` |
| distinct cases | 70 |
| calls | 210 |
| stale cases excluded | 9 |
| spend USD | 1.0062 |
| run at | 2026-08-29T03:46:24.927298+00:00 |

| axis | kind | result | threshold | verdict | excluded | reference |
|---|---|---|---|---|---|---|
| routing | target | 105/117 pass (90%) | >= 80% | PASS | 24 | #171 / i38: the corpus is labelled with acceptable sets, not a single key; luna's rate is the row this run records. |
| metric_resolution | target | 29/30 pass (97%) | >= 95% | PASS |  | i18/i19 after PR #181: unknown_metric on 1 of 26 calls (96%). |
| invented_metric_relay | target | 9/15 pass (60%)<br>no gameweek answer: 15/15 (100%) | >= 80% | **FAIL** |  | i15 live, 2026-08-26: relayed unknown_metric on 8 of 10 calls (80%). |
| order_direction | target | 12/12 pass (100%) | >= 100% | PASS |  | i42/i44 after PR #181: order='asc' applied on every call. |
| ownership_no_possessive | target | 6/6 pass (100%) | >= 80% | PASS |  | i41 after PR #186: sb-02 5/5 and sb-13 5/5. |
| overfire_guards | guard | 0/33 fires (0%) | <= 0% | PASS |  | i41: 0 fires of get_my_squad in 45 negative calls. |
| synthesis_present | target | 175/183 pass (96%) | >= 100% | **FAIL (i46)** | 27 | i46, opened 2026-08-28: 3 of 9 calls in an unrelated probe returned synthesis_turn=False. |

**REJECT — 1 model axis (invented_metric_relay); 1 blocked (synthesis_present blocked by i46).**

## Excluded by preflight

Pinned entities that no longer resolve. Excluded from scoring, not counted as passes or failures — a question about a departed player measures nothing. The questions are deliberately NOT rewritten here: #171, i38 and i41 were scored against this exact text.

| case | reason |
|---|---|
| `ad-01` | player 'Palmer' resolves ambiguous |
| `ad-12` | player 'Sterling' resolves not_found |
| `ad-12` | player 'Gordon' resolves not_found |
| `cp-02` | player 'Salah' resolves not_found |
| `cp-03` | player 'Salah' resolves not_found |
| `cp-03` | player 'Palmer' resolves ambiguous |
| `cp-08` | player 'Son' resolves not_found |
| `neg-comparar` | player 'Salah' resolves not_found |
| `pv-04` | player 'Palmer' resolves ambiguous |
| `pv-10` | player 'Rodri' resolves not_found |
| `pv-11` | player 'Gordon' resolves not_found |

> Guards outrank targets: a breached guard fails the model even when every target passes.
