/**
 * QuotaIndicator helper tests — P3.2
 *
 * Tests the pure color-classification logic extracted from QuotaIndicator.
 * No React / DOM / jsdom required — same pattern as component-helpers.test.ts.
 *
 * Covers:
 *   - pctThreshold: correct bucket assignment (green / amber / red)
 *   - Outcome type: 'quota_exceeded' added to the Outcome union in types.ts
 */

// ---------------------------------------------------------------------------
// Pure helper — mirrors QuotaIndicator internal logic exactly
// (duplicated here to avoid a React import chain in a plain ts-jest env)
// ---------------------------------------------------------------------------

type ColorBucket = 'green' | 'amber' | 'red';

function classifyQuota(remaining: number, cap: number): ColorBucket {
  if (cap <= 0) return 'red';
  const pct = remaining / cap;
  if (pct > 0.5) return 'green';
  if (pct > 0.2) return 'amber';
  return 'red';
}

// ---------------------------------------------------------------------------
// QuotaStatus shape guard — mirrors types.ts QuotaStatus interface
// ---------------------------------------------------------------------------

import type { QuotaStatus, Outcome } from '../lib/types';

function makeQuotaStatus(overrides: Partial<QuotaStatus> = {}): QuotaStatus {
  return {
    allowed: true,
    tier: 'free',
    daily_tokens_used: 0,
    daily_message_count: 0,
    monthly_tokens_used: 0,
    monthly_message_count: 0,
    daily_token_cap: 50_000,
    monthly_token_cap: 500_000,
    daily_message_cap: 5,
    monthly_message_cap: 30,
    reason: null,
    upgrade_prompt_es: null,
    upgrade_prompt_en: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// pct color logic
// ---------------------------------------------------------------------------

describe('classifyQuota — percentage threshold color buckets', () => {
  test('full quota (5/5 remaining) → green', () => {
    expect(classifyQuota(5, 5)).toBe('green');
  });

  test('exactly above 50% (3/5 remaining = 60%) → green', () => {
    expect(classifyQuota(3, 5)).toBe('green');
  });

  test('exactly 50% (5/10 remaining) → amber (not > 0.5)', () => {
    expect(classifyQuota(5, 10)).toBe('amber');
  });

  test('30% remaining → amber', () => {
    expect(classifyQuota(3, 10)).toBe('amber');
  });

  test('exactly 20% (2/10 remaining) → red (not > 0.2)', () => {
    expect(classifyQuota(2, 10)).toBe('red');
  });

  test('0 remaining → red', () => {
    expect(classifyQuota(0, 10)).toBe('red');
  });

  test('cap=0 guard → red', () => {
    expect(classifyQuota(0, 0)).toBe('red');
  });
});

// ---------------------------------------------------------------------------
// QuotaStatus type shape
// ---------------------------------------------------------------------------

describe('QuotaStatus — type shape contract', () => {
  test('makeQuotaStatus default satisfies all required fields', () => {
    const qs = makeQuotaStatus();
    expect(qs.allowed).toBe(true);
    expect(qs.tier).toBe('free');
    expect(qs.daily_message_cap).toBe(5);
    expect(qs.monthly_message_cap).toBe(30);
    expect(qs.reason).toBeNull();
    expect(qs.upgrade_prompt_es).toBeNull();
    expect(qs.upgrade_prompt_en).toBeNull();
  });

  test('allowed=false with reason is representable', () => {
    const qs = makeQuotaStatus({
      allowed: false,
      daily_message_count: 5,
      reason: 'daily_message_cap',
      upgrade_prompt_es: 'Has alcanzado tu límite diario.',
      upgrade_prompt_en: 'You have reached your daily limit.',
    });
    expect(qs.allowed).toBe(false);
    expect(qs.reason).toBe('daily_message_cap');
    expect(qs.upgrade_prompt_es).toMatch(/límite/);
  });

  test('remaining = cap - used is positive when not exhausted', () => {
    const qs = makeQuotaStatus({ daily_message_count: 3, daily_message_cap: 5 });
    const remaining = qs.daily_message_cap - qs.daily_message_count;
    expect(remaining).toBe(2);
    expect(classifyQuota(remaining, qs.daily_message_cap)).toBe('amber'); // 2/5 = 40% → amber
  });
});

// ---------------------------------------------------------------------------
// Outcome type — quota_exceeded must be present
// ---------------------------------------------------------------------------

describe('Outcome type — quota_exceeded value', () => {
  test('quota_exceeded is an assignable Outcome value', () => {
    const outcome: Outcome = 'quota_exceeded';
    expect(outcome).toBe('quota_exceeded');
  });

  test('ok is still a valid Outcome value (no regression)', () => {
    const outcome: Outcome = 'ok';
    expect(outcome).toBe('ok');
  });
});
