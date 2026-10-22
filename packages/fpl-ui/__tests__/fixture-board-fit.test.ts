import { fitFixtureWindow, rowColumns, GW_CELL_PX, ROW_GAP_PX } from '../lib/fixture-board-fit';

// Board widths are the rows container inside the Calendar card, measured at
// 2560 with the three panels open (~1488) and with Squad collapsed (~2026).
describe('fitFixtureWindow', () => {
  test('2560 with all three panels open: 2 columns of 8 gameweeks', () => {
    expect(fitFixtureWindow(1488)).toEqual({ horizon: 8, columns: 2 });
  });

  test('2560 with Squad collapsed: 2 columns of 12 gameweeks', () => {
    expect(fitFixtureWindow(2026)).toEqual({ horizon: 12, columns: 2 });
  });

  test('2 x 12 fits exactly at its threshold and not one pixel under', () => {
    const exact = 2 * 12 * GW_CELL_PX + ROW_GAP_PX;
    expect(fitFixtureWindow(exact)).toEqual({ horizon: 12, columns: 2 });
    expect(fitFixtureWindow(exact - 1).horizon).toBe(10);
  });

  test('between 2 x 8 and 2 x 12 it takes the largest window that still gives two columns', () => {
    expect(fitFixtureWindow(1600)).toEqual({ horizon: 10, columns: 2 });
  });

  test('below 2 x 8 it keeps one column with the largest window that fits', () => {
    expect(fitFixtureWindow(1150)).toEqual({ horizon: 12, columns: 1 });
    expect(fitFixtureWindow(700)).toEqual({ horizon: 8, columns: 1 });
    expect(fitFixtureWindow(500)).toEqual({ horizon: 5, columns: 1 });
    expect(fitFixtureWindow(300)).toEqual({ horizon: 5, columns: 1 });
  });
});

describe('rowColumns', () => {
  test('an explicit window decides its own column count from the width', () => {
    expect(rowColumns(1488, 12)).toBe(1);
    expect(rowColumns(1488, 8)).toBe(2);
    expect(rowColumns(2026, 12)).toBe(2);
  });

  test('is never below one column', () => {
    expect(rowColumns(100, 12)).toBe(1);
    expect(rowColumns(0, 5)).toBe(1);
  });
});

describe('fitCompactWindow: one table, the largest window whose cells stay at least 62 px', () => {
  const { fitCompactWindow, COMPACT_MIN_CELL_PX, COMPACT_GAP_PX, COMPACT_TEAM_COL_PX } = require('../lib/fixture-board-fit');
  const needs = (h: number) => COMPACT_TEAM_COL_PX + h * (COMPACT_MIN_CELL_PX + COMPACT_GAP_PX);

  test('thresholds are exact and never split into columns', () => {
    for (const h of [5, 8, 10, 12]) {
      expect(fitCompactWindow(needs(h))).toEqual({ horizon: h, columns: 1 });
    }
    expect(fitCompactWindow(needs(12) - 1).horizon).toBe(10);
    expect(fitCompactWindow(needs(10) - 1).horizon).toBe(8);
    expect(fitCompactWindow(needs(8) - 1).horizon).toBe(5);
  });

  test('wide boards stay at 12 in one column and tiny ones at 5', () => {
    expect(fitCompactWindow(1490)).toEqual({ horizon: 12, columns: 1 });
    expect(fitCompactWindow(5000)).toEqual({ horizon: 12, columns: 1 });
    expect(fitCompactWindow(770).horizon).toBe(10);
    expect(fitCompactWindow(100).horizon).toBe(5);
  });
});
