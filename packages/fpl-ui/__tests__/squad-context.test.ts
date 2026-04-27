/**
 * Squad context tests — V2 Phase 2f (corrected Phase 2g)
 *
 * Pure function tests: validateTeamId and normalizeSquadContext.
 * No fetch mocking, no React, no DOM required.
 *
 * Coverage:
 *   1. validateTeamId — valid IDs, invalid inputs, boundary values
 *   2. normalizeSquadContext — ITB derivation, free_transfers is null (not
 *      derived — FPL API does not expose a reliable source for it),
 *      chips_remaining mapping from FPL API codes to backend names
 *   3. Free-transfer user input — FT_OPTIONS range and SquadContext merging
 *   4. Request wiring — squad_context flows through both ask modes
 *      (structural test: verifies it is present on AskRequest)
 *   5. No-context regression — null squad_context is valid on AskRequest
 */
import {
  validateTeamId,
  normalizeSquadContext,
  FT_OPTIONS,
  type FplEntryRaw,
  type FplHistoryRaw,
} from '../lib/squad-context';
import type { AskRequest, SquadContext } from '../lib/types';

// ---------------------------------------------------------------------------
// Helpers — minimal raw data builders
// ---------------------------------------------------------------------------

function makeEntry(overrides: Partial<FplEntryRaw> = {}): FplEntryRaw {
  return {
    id: 12345,
    player_first_name: 'Leo',
    player_last_name: 'Test',
    name: 'My FPL Team',
    last_deadline_bank: 50,             // £5.0m in bank
    summary_event_transfers: 1,
    summary_event_transfers_cost: 0,
    ...overrides,
  };
}

function makeHistory(overrides: Partial<FplHistoryRaw> = {}): FplHistoryRaw {
  return {
    current: [],
    chips: [],
    ...overrides,
  };
}

function makeGwEntry(event: number, transfers: number, cost = 0) {
  return { event, event_transfers: transfers, event_transfers_cost: cost };
}

// ---------------------------------------------------------------------------
// validateTeamId
// ---------------------------------------------------------------------------

describe('validateTeamId — valid inputs', () => {
  test('"1" → 1', () => expect(validateTeamId('1')).toBe(1));
  test('"12345" → 12345', () => expect(validateTeamId('12345')).toBe(12345));
  test('"  987  " (whitespace) → 987', () => expect(validateTeamId('  987  ')).toBe(987));
  test('"20000000" (upper bound) → 20000000', () => expect(validateTeamId('20000000')).toBe(20_000_000));
});

describe('validateTeamId — invalid inputs', () => {
  test('"0" → null', () => expect(validateTeamId('0')).toBeNull());
  test('"-1" → null (negative)', () => expect(validateTeamId('-1')).toBeNull());
  test('"abc" → null (non-numeric)', () => expect(validateTeamId('abc')).toBeNull());
  test('"12.5" → null (decimal)', () => expect(validateTeamId('12.5')).toBeNull());
  test('"" → null (empty)', () => expect(validateTeamId('')).toBeNull());
  test('"  " → null (whitespace only)', () => expect(validateTeamId('  ')).toBeNull());
  test('"20000001" → null (above upper bound)', () => expect(validateTeamId('20000001')).toBeNull());
  test('"1e5" → null (scientific notation rejected)', () => expect(validateTeamId('1e5')).toBeNull());
});

// ---------------------------------------------------------------------------
// normalizeSquadContext — ITB
// ---------------------------------------------------------------------------

describe('normalizeSquadContext — itb derivation', () => {
  test('last_deadline_bank=50 → itb=50 (£5.0m)', () => {
    const ctx = normalizeSquadContext(makeEntry({ last_deadline_bank: 50 }), makeHistory());
    expect(ctx.itb).toBe(50);
  });

  test('last_deadline_bank=5 → itb=5 (£0.5m)', () => {
    const ctx = normalizeSquadContext(makeEntry({ last_deadline_bank: 5 }), makeHistory());
    expect(ctx.itb).toBe(5);
  });

  test('last_deadline_bank=0 → itb=0', () => {
    const ctx = normalizeSquadContext(makeEntry({ last_deadline_bank: 0 }), makeHistory());
    expect(ctx.itb).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// normalizeSquadContext — free_transfers is always null (not derivable)
// ---------------------------------------------------------------------------

describe('normalizeSquadContext — free_transfers is null from API data', () => {
  test('no history → free_transfers is null (not 1)', () => {
    const ctx = normalizeSquadContext(makeEntry(), makeHistory({ current: [] }));
    expect(ctx.free_transfers).toBeNull();
  });

  test('history with 0 transfers last GW → free_transfers still null (not 2)', () => {
    // Previously the heuristic would return 2 here. The correct answer is: unknown.
    const ctx = normalizeSquadContext(
      makeEntry(),
      makeHistory({ current: [makeGwEntry(27, 0)] }),
    );
    expect(ctx.free_transfers).toBeNull();
  });

  test('history with transfers made → free_transfers still null', () => {
    const ctx = normalizeSquadContext(
      makeEntry(),
      makeHistory({ current: [makeGwEntry(27, 1, 0)] }),
    );
    expect(ctx.free_transfers).toBeNull();
  });

  test('free_transfers field is present in returned context (key exists)', () => {
    const ctx = normalizeSquadContext(makeEntry(), makeHistory());
    expect('free_transfers' in ctx).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Free transfer user input — FT_OPTIONS and SquadContext merging
// ---------------------------------------------------------------------------

describe('FT_OPTIONS — user-selectable free transfer values', () => {
  test('FT_OPTIONS contains null (unset option)', () => {
    expect(FT_OPTIONS).toContain(null);
  });

  test('FT_OPTIONS contains 1 through 5', () => {
    for (let i = 1; i <= 5; i++) {
      expect(FT_OPTIONS).toContain(i);
    }
  });

  test('null is the first option (default unset state)', () => {
    expect(FT_OPTIONS[0]).toBeNull();
  });

  test('merging user FT into context from normalizeSquadContext works', () => {
    const base = normalizeSquadContext(makeEntry(), makeHistory());
    // Simulate SquadContextPanel merging user selection
    const withFt = { ...base, free_transfers: 2 };
    expect(withFt.free_transfers).toBe(2);
    expect(withFt.itb).toBe(base.itb);        // other fields preserved
    expect(withFt.chips_remaining).toBe(base.chips_remaining);
  });

  test('merging null FT into context leaves free_transfers null', () => {
    const base = normalizeSquadContext(makeEntry(), makeHistory());
    const withNull = { ...base, free_transfers: null };
    expect(withNull.free_transfers).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// normalizeSquadContext — chips_remaining
// ---------------------------------------------------------------------------

describe('normalizeSquadContext — chips_remaining', () => {
  test('no chips used → all 4 backend chip names present', () => {
    const ctx = normalizeSquadContext(makeEntry(), makeHistory({ chips: [] }));
    expect(ctx.chips_remaining).toContain('wildcard');
    expect(ctx.chips_remaining).toContain('triple_captain');
    expect(ctx.chips_remaining).toContain('bench_boost');
    expect(ctx.chips_remaining).toContain('free_hit');
    expect(ctx.chips_remaining).toHaveLength(4);
  });

  test('triple_captain used → not in chips_remaining', () => {
    const ctx = normalizeSquadContext(
      makeEntry(),
      makeHistory({ chips: [{ name: '3xc', event: 10 }] }),
    );
    expect(ctx.chips_remaining).not.toContain('triple_captain');
    expect(ctx.chips_remaining).toHaveLength(3);
  });

  test('bench_boost used → not in chips_remaining', () => {
    const ctx = normalizeSquadContext(
      makeEntry(),
      makeHistory({ chips: [{ name: 'bboost', event: 15 }] }),
    );
    expect(ctx.chips_remaining).not.toContain('bench_boost');
  });

  test('free_hit used → not in chips_remaining', () => {
    const ctx = normalizeSquadContext(
      makeEntry(),
      makeHistory({ chips: [{ name: 'freehit', event: 20 }] }),
    );
    expect(ctx.chips_remaining).not.toContain('free_hit');
  });

  test('first wildcard used → wildcard still in chips_remaining (second half available)', () => {
    const ctx = normalizeSquadContext(
      makeEntry(),
      makeHistory({ chips: [{ name: 'wildcard', event: 5 }] }),
    );
    expect(ctx.chips_remaining).toContain('wildcard');
  });

  test('both wildcards used → wildcard not in chips_remaining', () => {
    const ctx = normalizeSquadContext(
      makeEntry(),
      makeHistory({
        chips: [
          { name: 'wildcard', event: 5 },
          { name: 'wildcard', event: 25 },
        ],
      }),
    );
    expect(ctx.chips_remaining).not.toContain('wildcard');
  });

  test('all chips used → empty chips_remaining', () => {
    const ctx = normalizeSquadContext(
      makeEntry(),
      makeHistory({
        chips: [
          { name: 'wildcard', event: 5 },
          { name: 'wildcard', event: 25 },
          { name: '3xc',     event: 10 },
          { name: 'bboost',  event: 15 },
          { name: 'freehit', event: 20 },
        ],
      }),
    );
    expect(ctx.chips_remaining).toHaveLength(0);
  });

  test('wildcard appears exactly once in chips_remaining even with both uses available', () => {
    const ctx = normalizeSquadContext(makeEntry(), makeHistory({ chips: [] }));
    const wildcardCount = ctx.chips_remaining!.filter((c) => c === 'wildcard').length;
    expect(wildcardCount).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Request wiring — squad_context flows through AskRequest
// ---------------------------------------------------------------------------

describe('squad_context request wiring', () => {
  test('SquadContext is structurally assignable to AskRequest.squad_context', () => {
    // Type-level test: construct an AskRequest with squad_context populated.
    // This will fail to compile if the types diverge.
    const ctx: SquadContext = {
      itb: 50,
      free_transfers: 2,
      chips_remaining: ['wildcard', 'triple_captain'],
    };
    const req: AskRequest = {
      question: '¿Debería capitanear a Haaland?',
      squad_context: ctx,
    };
    expect(req.squad_context).toBe(ctx);
    expect(req.squad_context!.itb).toBe(50);
    expect(req.squad_context!.free_transfers).toBe(2);
    expect(req.squad_context!.chips_remaining).toEqual(['wildcard', 'triple_captain']);
  });

  test('null squad_context is valid on AskRequest (no-context regression)', () => {
    const req: AskRequest = { question: '¿Cuál es el mejor capitán?', squad_context: null };
    expect(req.squad_context).toBeNull();
  });

  test('omitted squad_context is valid on AskRequest (no-context regression)', () => {
    const req: AskRequest = { question: '¿Cuál es el mejor capitán?' };
    expect(req.squad_context).toBeUndefined();
  });

  test('normalizeSquadContext output satisfies all SquadContext fields', () => {
    const ctx = normalizeSquadContext(makeEntry(), makeHistory());
    // TypeScript structural check — all three SquadContext keys are present
    expect('itb' in ctx).toBe(true);
    expect('free_transfers' in ctx).toBe(true);
    expect('chips_remaining' in ctx).toBe(true);
  });
});
