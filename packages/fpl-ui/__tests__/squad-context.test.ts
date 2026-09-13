/**
 * Squad context tests — V2 Phase 2f (corrected Phase 2g)
 *
 * Pure function tests: validateTeamId and normalizeSquadContext.
 * No fetch mocking, no React, no DOM required.
 *
 * Coverage:
 *   1. validateTeamId — valid IDs, invalid inputs, boundary values
 *   2. normalizeSquadContext — ITB derivation, free_transfers derived from
 *      the season history, chips_remaining mapping from FPL API codes to
 *      backend names
 *   3. deriveFreeTransfers — accrual, cap, hits, WC/FH hold, inconsistency
 *   4. Request wiring — squad_context flows through both ask modes
 *      (structural test: verifies it is present on AskRequest)
 *   5. No-context regression — null squad_context is valid on AskRequest
 */
import {
  validateTeamId,
  normalizeSquadContext,
  deriveFreeTransfers,
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
// deriveFreeTransfers — free_transfers from public season history
// ---------------------------------------------------------------------------

describe('deriveFreeTransfers — basics', () => {
  test('empty history → null (unknown, not 1)', () => {
    expect(deriveFreeTransfers(makeHistory({ current: [] }))).toBeNull();
  });

  test('only GW1 played → 1 (first GW is unlimited, then 1 FT)', () => {
    expect(deriveFreeTransfers(makeHistory({ current: [makeGwEntry(1, 0)] }))).toBe(1);
  });

  test('late joiner: first entry is GW3 with transfers → still treated as unlimited', () => {
    const h = makeHistory({ current: [makeGwEntry(3, 15, 0), makeGwEntry(4, 0)] });
    expect(deriveFreeTransfers(h)).toBe(2);
  });

  test('no transfers for 3 GWs → accrues to 3', () => {
    const h = makeHistory({ current: [makeGwEntry(1, 0), makeGwEntry(2, 0), makeGwEntry(3, 0)] });
    expect(deriveFreeTransfers(h)).toBe(3);
  });

  test('accrual is capped at 5', () => {
    const current = Array.from({ length: 8 }, (_, i) => makeGwEntry(i + 1, 0));
    expect(deriveFreeTransfers(makeHistory({ current }))).toBe(5);
  });

  test('unsorted history is handled', () => {
    const h = makeHistory({ current: [makeGwEntry(3, 0), makeGwEntry(1, 0), makeGwEntry(2, 0)] });
    expect(deriveFreeTransfers(h)).toBe(3);
  });
});

describe('deriveFreeTransfers — transfers and hits', () => {
  test('1 free transfer used each GW → stays at 1', () => {
    const h = makeHistory({ current: [makeGwEntry(1, 0), makeGwEntry(2, 1), makeGwEntry(3, 1)] });
    expect(deriveFreeTransfers(h)).toBe(1);
  });

  test('2 transfers with a −4 hit on 1 FT → bank empties, back to 1', () => {
    const h = makeHistory({ current: [makeGwEntry(1, 0), makeGwEntry(2, 2, 4)] });
    expect(deriveFreeTransfers(h)).toBe(1);
  });

  test('live sample 2500000: WC GW2, 1 free GW3, 2 transfers −4 GW4 → 1', () => {
    const h = makeHistory({
      current: [makeGwEntry(1, 0), makeGwEntry(2, 0), makeGwEntry(3, 1, 0), makeGwEntry(4, 2, 4)],
      chips: [{ name: 'wildcard', event: 2 }],
    });
    expect(deriveFreeTransfers(h)).toBe(1);
  });

  test('live sample 5387956: FH GW2, 8 transfers −28 GW3, 3 transfers −8 GW4 → 1', () => {
    const h = makeHistory({
      current: [makeGwEntry(1, 0), makeGwEntry(2, 0), makeGwEntry(3, 8, 28), makeGwEntry(4, 3, 8)],
      chips: [{ name: 'freehit', event: 2 }],
    });
    expect(deriveFreeTransfers(h)).toBe(1);
  });
});

describe('deriveFreeTransfers — wildcard / free hit hold the bank', () => {
  test('wildcard GW: transfers are free and no +1 accrues', () => {
    // GW1 → 1 FT. GW2 quiet → 2. GW3 wildcard with 10 transfers → still 2.
    const h = makeHistory({
      current: [makeGwEntry(1, 0), makeGwEntry(2, 0), makeGwEntry(3, 10, 0)],
      chips: [{ name: 'wildcard', event: 3 }],
    });
    expect(deriveFreeTransfers(h)).toBe(2);
  });

  test('free hit GW behaves the same as wildcard', () => {
    const h = makeHistory({
      current: [makeGwEntry(1, 0), makeGwEntry(2, 0), makeGwEntry(3, 10, 0)],
      chips: [{ name: 'freehit', event: 3 }],
    });
    expect(deriveFreeTransfers(h)).toBe(2);
  });

  test('bench boost / triple captain do not exempt the GW', () => {
    const h = makeHistory({
      current: [makeGwEntry(1, 0), makeGwEntry(2, 0), makeGwEntry(3, 1, 0)],
      chips: [{ name: 'bboost', event: 3 }, { name: '3xc', event: 2 }],
    });
    expect(deriveFreeTransfers(h)).toBe(2);
  });
});

describe('deriveFreeTransfers — history contradicting the model → null', () => {
  test('3 free transfers recorded when only 1 FT was available', () => {
    // e.g. a special unlimited-transfer gameweek not visible in the API
    const h = makeHistory({ current: [makeGwEntry(1, 0), makeGwEntry(2, 3, 0)] });
    expect(deriveFreeTransfers(h)).toBeNull();
  });

  test('hit taken while FTs were still banked', () => {
    const h = makeHistory({ current: [makeGwEntry(1, 0), makeGwEntry(2, 0), makeGwEntry(3, 1, 4)] });
    expect(deriveFreeTransfers(h)).toBeNull();
  });
});

describe('normalizeSquadContext — free_transfers comes from the history', () => {
  test('no history → null', () => {
    expect(normalizeSquadContext(makeEntry(), makeHistory()).free_transfers).toBeNull();
  });

  test('history is wired through deriveFreeTransfers', () => {
    const h = makeHistory({ current: [makeGwEntry(1, 0), makeGwEntry(2, 0)] });
    expect(normalizeSquadContext(makeEntry(), h).free_transfers).toBe(2);
    expect(normalizeSquadContext(makeEntry(), h).itb).toBe(50);   // other fields untouched
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
