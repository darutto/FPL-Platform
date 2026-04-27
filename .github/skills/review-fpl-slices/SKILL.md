---
name: review-fpl-slices
description: 'Review completed FPL grounded assistant development slices, inspect the actual changed files and new functions, evaluate logic gaps and FPL-domain risks, preserve grounded architecture, explain the value of the new work, and draft a narrow next-slice Claude Code prompt. Use when reviewing phase handoffs, completed slices, roadmap increments, critical game-logic slices, or when deciding the next additive implementation slice.'
argument-hint: 'Provide the completed slice, phase, handoff, or docs to review'
user-invocable: true
disable-model-invocation: false
---

# Review FPL Slices

Use this skill to review completed FPL grounded assistant implementation slices and propose the next narrow slice without breaking the grounded architecture.

This skill is only for slices in `fpl-grounded-assistant`.
Do not use it to review adjacent package slices unless the user explicitly asks for a different workflow.

The assistant being reviewed is grounded by design:

- Deterministic backend is authoritative.
- LLMs may interpret, resolve bounded references, and phrase answers.
- LLMs must not become the source of football truth.
- Changes should remain additive, narrow, testable, and consistent across CLI, HTTP, and session flows.

## When to Use

- Review a completed FPL assistant phase or slice.
- Evaluate a handoff document or end-of-slice report.
- Decide the next narrow Claude Code implementation slice.
- Turn repeated review methodology into a consistent output format.
- Review critical FPL logic changes where football-domain correctness matters as much as code quality.

## Required Output

Always output these sections in this order:

1. Slice Evaluation
2. Next Recommended Slice
3. Claude Code Prompt
4. Optional Review Note

The first two sections must be brief and non-redundant.
They are for operator judgment, not for restating the full implementation plan.
Put the detailed implementation guidance only in the Claude Code Prompt section.

## Review Procedure

1. Read the current grounded architecture before evaluating the slice.
   Minimum sources when available:
   - `orchestrator-instructions.md`
   - `HANDOFF.md`
   - any slice-specific prompt pack, roadmap, package audit, or handoff artifact

2. Confirm the reviewed work is a grounded-assistant slice.
   - Prefer `packages/fpl-grounded-assistant` as the implementation boundary.
   - Adjacent package changes may be mentioned only as dependencies or context.
   - Do not turn the review into a cross-package planning exercise.

3. Read the actual implementation changes, not just the handoff summary.
   - Open the files the handoff says were changed or created.
   - Identify the new, removed, or materially changed functions, constants, tests, fixtures, and contract surfaces.
   - Trace how the new logic flows through the grounded chain when that is relevant.
   - If the handoff is incomplete or imprecise, prefer the code over the handoff narrative.

4. Identify what the completed slice actually changed.
   Check for:
   - new or updated intent coverage
   - contract changes
   - tool or runner changes
   - renderer or explainer changes
   - dispatch or adapter changes
   - CLI, HTTP, and session parity
   - tests, fixtures, docs, and validation updates

5. Evaluate the slice result.
   Cover these points explicitly:
   - what is complete and working
   - what architectural intent was preserved
   - what remains intentionally deferred
   - any risks, asymmetries, or hidden follow-up work

6. Review the code for logic gaps, not just implementation completeness.
   Look for:
   - edge cases the tests do not cover
   - misleading fallback behavior
   - threshold or boundary errors
   - silent contract drift
   - inconsistent surface behavior
   - implementation choices that technically pass tests but produce weak user outcomes

7. Give feedback on quality.
   Focus on:
   - groundedness and deterministic authority
   - contract stability
   - bounded LLM usage
   - safe fallback behavior
   - additive scope discipline
   - consistency across user-facing surfaces

8. Review the slice from an FPL domain perspective whenever the logic touches football rules, chip usage, fixture structure, player availability, or strategic advice.
   Explicitly assess:
   - whether the implemented logic matches real FPL rules and common edge cases
   - whether doubles, blanks, fixtures, chips, captaincy, transfers, or thresholds are modeled in a strategically credible way
   - whether the output would mislead an experienced FPL manager even if the code is internally consistent
   - whether later slices would inherit a flawed foundational assumption if this slice were accepted unchanged

9. Explain why the completed work is useful.
   Tie usefulness to one or more of:
   - stronger caller-facing contract
   - better operator experience
   - improved auditability
   - higher parity across CLI, HTTP, and sessions
   - reduced ambiguity for future slices
   - safer or more deterministic behavior

10. Select the next recommended slice.
   The next slice must be:
   - narrow
   - additive
   - testable
   - architecturally adjacent to the completed work
   - aligned with current project gate conditions

11. Draft the Claude Code prompt.
   Include all of the following:
   - short feedback on current state
   - explicit context
   - goals
   - constraints
   - suggested implementation direction when useful
   - deliverables
   - exact reporting requirements
   - success criteria
   - request for a short end-of-slice handoff summary

## Architecture Guardrails

Preserve this chain and do not collapse responsibilities across it unless the slice explicitly requires a narrow, justified change:

`route -> tool/contract -> runner -> renderer/explainer -> dispatch -> adapter -> final response`

Guardrails:

- Backend truth must stay deterministic.
- LLM layers may not invent football facts, scores, or recommendations.
- Unsupported prompts must remain explicit and safe.
- Stable contracts should be extended additively, not casually reshaped.
- Keep CLI, HTTP, and session behavior aligned unless a surface-specific difference is intentional and documented.
- Prefer the smallest slice that closes the highest-value nearby gap.

## Decision Rules For The Next Slice

Prefer next slices in this order:

1. Close parity or contract gaps created by the completed slice.
2. Add missing structured metadata for already-supported deterministic behavior.
3. Add debug, example, validation, or auditability parity for behavior that already exists.
4. Add narrow follow-up resolution or routing improvements that remain bounded and safe.
5. Add a new deterministic intent only when it is grounded, retrieval-oriented or narrowly-scoped, and supported by existing data.

Avoid recommending:

- broad roadmap expansion with unclear contracts
- open-ended chat behavior
- LLM-first football reasoning
- UI-heavy work unless the user explicitly requests it
- persistence, auth, or infrastructure expansion unless that is the current gate

If the project is in a manual UAT or stabilization gate, always prefer the next slice to focus on:

- defect closure
- parity fixes
- documentation and runbook accuracy
- operator-facing evidence capture

Do not recommend new capability growth in that state unless the user explicitly asks for it.

## Output Guidance

Use this structure:

- You may add a one-line lead-in before the headings only when it makes the review clearer.
- The section headings themselves should remain exact literals.
- Avoid writing the same reasoning twice.
- Keep the human-facing review short, then put the full detail in the Claude Code Prompt.

### Slice Evaluation

- Keep this section punctual.
- State whether the slice is good or not good enough yet.
- Mention only the most important caution, gap, or thing to watch.
- If a material logic defect or FPL-domain flaw exists, say so directly here even if tests are green.
- Use 3 to 6 short bullets maximum.
- Do not repeat the full next-step plan here.

### Next Recommended Slice

- Keep this section short.
- Name one narrow next slice.
- Give a brief reason it is the right next move.
- Optionally state one thing it should avoid.
- Do not expand into full goals, deliverables, or success criteria here.

### Claude Code Prompt

Write a ready-to-use prompt that:

- preserves deterministic backend authority
- keeps LLM usage bounded
- asks for additive, testable implementation only
- requests contract and documentation updates only when materially necessary
- requests exact deliverables and exact report-back points

This is the only section that should contain the full implementation brief.

### Optional Review Note

Include only when one of these applies:

- there is a material architectural caution
- the project gate has shifted to UAT or stabilization
- the user should avoid feature growth until a blocker is closed
- the reviewed slice left a meaningful asymmetry that should shape the next prompt

## Completion Check

Before finalizing, verify:

- the review explains whether the slice is good enough and what to watch
- the review is based on the actual changed files and functions, not only the handoff summary
- the review identifies any important logic gap, edge case, or missing test coverage
- when the slice affects FPL gameplay logic, the review checks football-domain correctness and strategic credibility
- the first two sections stay brief and do not duplicate the prompt
- the next slice is narrower than the completed slice, not broader
- the prompt is ready to paste into Claude Code
- deterministic authority is explicitly preserved
- the required four output sections are present