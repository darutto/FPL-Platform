/**
 * Component helper tests — V2 Phase 2c
 *
 * Tests the pure utility functions exported from intent components.
 * No React, no DOM, no jsdom required.
 *
 * These tests cover component-level output logic beyond renderer selection:
 *   - FixtureRunTable: fdrColor, formatVenue
 *   - DifferentialTable: formatOwnership, formatCost
 */
import { fdrColor, formatVenue, fixtureKey } from '../components/intents/FixtureRunTable';
import { formatOwnership, formatCost } from '../components/intents/DifferentialTable';
import { fixtureRunDgwResponse } from './fixtures/sample-responses';

// ---------------------------------------------------------------------------
// FixtureRunTable — fdrColor
// ---------------------------------------------------------------------------

describe('fdrColor — FDR difficulty to hex colour', () => {
  test('difficulty 1 → #2ecc71 (easy, emerald green)', () => {
    expect(fdrColor(1)).toBe('#2ecc71');
  });

  test('difficulty 2 → #a8d8a8 (light green)', () => {
    expect(fdrColor(2)).toBe('#a8d8a8');
  });

  test('difficulty 3 → #f7f7a8 (pale yellow)', () => {
    expect(fdrColor(3)).toBe('#f7f7a8');
  });

  test('difficulty 4 → #f4a262 (orange)', () => {
    expect(fdrColor(4)).toBe('#f4a262');
  });

  test('difficulty 5 → #e74c3c (hard, red)', () => {
    expect(fdrColor(5)).toBe('#e74c3c');
  });

  test('all 5 values return distinct colours', () => {
    const colours = [1, 2, 3, 4, 5].map((d) => fdrColor(d as 1 | 2 | 3 | 4 | 5));
    expect(new Set(colours).size).toBe(5);
  });
});

// ---------------------------------------------------------------------------
// FixtureRunTable — formatVenue
// ---------------------------------------------------------------------------

describe('formatVenue — Spanish venue abbreviation', () => {
  test('is_home true → "L" (local)', () => {
    expect(formatVenue(true)).toBe('L');
  });

  test('is_home false → "V" (visitante)', () => {
    expect(formatVenue(false)).toBe('V');
  });
});

// ---------------------------------------------------------------------------
// DifferentialTable — formatOwnership
// ---------------------------------------------------------------------------

describe('formatOwnership — ownership float to percentage string', () => {
  test('1.0 → "1.0%"', () => {
    expect(formatOwnership(1.0)).toBe('1.0%');
  });

  test('8.2 → "8.2%"', () => {
    expect(formatOwnership(8.2)).toBe('8.2%');
  });

  test('12.345 rounds to one decimal → "12.3%"', () => {
    expect(formatOwnership(12.345)).toBe('12.3%');
  });

  test('0.0 → "0.0%"', () => {
    expect(formatOwnership(0.0)).toBe('0.0%');
  });

  test('100.0 → "100.0%"', () => {
    expect(formatOwnership(100.0)).toBe('100.0%');
  });
});

// ---------------------------------------------------------------------------
// DifferentialTable — formatCost
// ---------------------------------------------------------------------------

describe('formatCost — now_cost (tenths of £) to price string', () => {
  test('75 → "£7.5m"', () => {
    expect(formatCost(75)).toBe('£7.5m');
  });

  test('70 → "£7.0m"', () => {
    expect(formatCost(70)).toBe('£7.0m');
  });

  test('65 → "£6.5m"', () => {
    expect(formatCost(65)).toBe('£6.5m');
  });

  test('45 → "£4.5m"', () => {
    expect(formatCost(45)).toBe('£4.5m');
  });

  test('125 → "£12.5m"', () => {
    expect(formatCost(125)).toBe('£12.5m');
  });

  test('50 → "£5.0m" (no trailing zero lost)', () => {
    expect(formatCost(50)).toBe('£5.0m');
  });
});

// ---------------------------------------------------------------------------
// FixtureRunTable — fixtureKey (DGW-safe composite identity)
// ---------------------------------------------------------------------------

describe('fixtureKey — composite fixture identity for React keys', () => {
  test('home fixture → "{gw}-{opp}-H"', () => {
    expect(fixtureKey({ gameweek: 28, opponent_short: 'ARS', is_home: true, difficulty: 2 }))
      .toBe('28-ARS-H');
  });

  test('away fixture → "{gw}-{opp}-A"', () => {
    expect(fixtureKey({ gameweek: 29, opponent_short: 'MUN', is_home: false, difficulty: 3 }))
      .toBe('29-MUN-A');
  });

  test('same GW, different opponent+venue → distinct keys (DGW safety)', () => {
    const a = fixtureKey({ gameweek: 29, opponent_short: 'ARS', is_home: true,  difficulty: 2 });
    const b = fixtureKey({ gameweek: 29, opponent_short: 'MUN', is_home: false, difficulty: 3 });
    expect(a).not.toBe(b);
  });

  test('DGW response: all fixture keys are unique — no collision', () => {
    const fixtures = fixtureRunDgwResponse.fixture_run!.fixtures;
    const keys = fixtures.map(fixtureKey);
    expect(new Set(keys).size).toBe(fixtures.length);
  });

  test('DGW response: both GW29 fixtures are present after keying', () => {
    const fixtures = fixtureRunDgwResponse.fixture_run!.fixtures;
    const keys = fixtures.map(fixtureKey);
    expect(keys).toContain('29-ARS-H');
    expect(keys).toContain('29-MUN-A');
  });
});
