/**
 * @jest-environment jsdom
 *
 * The Calendar's fluid sizing: what the board decides from its width (window, columns, header) and what the
 * stylesheet scopes to the wide workspace. jsdom has no layout, so the width is injected where the board
 * measures it (the rows container's clientWidth through a ResizeObserver) and the stylesheet is read as text.
 */
jest.mock('@/lib/presentation-access', () => ({
  usePresentationAccess: () => false,
}));

// These snapshots describe the bundle as it stood when they were recorded. The live bundle is regenerated
// weekly (it moves 'actualizado el ...', the short-sample warning and the verdicts), so pin it.
jest.mock('@/lib/data/fixture-outlook-2026-27.json', () => jest.requireActual('./fixtures/fixture-outlook-2026-27.pinned.json'));

import { readFileSync } from 'fs';
import { join } from 'path';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { FixturesBoard } from '@/components/intents/FixturesBoard';
import { TeamHeader } from '@/components/intents/FixtureTickerRow';
import { buildRealSeasonOutlook } from '@/lib/fixture-outlook-real';

jest.setTimeout(60_000);

const CSS = readFileSync(join(__dirname, '..', 'app', 'globals.css'), 'utf-8');

let width = 1490;
let observers: Array<() => void> = [];
const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth');

beforeEach(() => {
  width = 1490;
  observers = [];
  (global as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
    constructor(cb: () => void) { observers.push(cb); }
    observe() {}
    disconnect() {}
  };
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true,
    get(this: HTMLElement) { return this.getAttribute('data-testid') === 'fixture-board-rows' ? width : 0; },
  });
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ next_gw: 8, finished_gw: 7 }),
  }) as unknown as typeof fetch;
});

afterEach(() => {
  if (original) Object.defineProperty(HTMLElement.prototype, 'clientWidth', original);
});

const resize = (next: number) => act(() => { width = next; observers.forEach((cb) => cb()); });
const click = (el: HTMLElement) => act(() => { fireEvent.click(el); });
const view = (name: 'Detallado' | 'Compacto' | 'Tendencia') => click(screen.getByRole('button', { name }));

function renderBoard(workspace: boolean) {
  const board = <FixturesBoard onAsk={() => {}} />;
  return render(workspace ? <div className="wide-workspace">{board}</div> : board);
}

const windowLabel = () => screen.getByText(/^J\d+–J\d+$/).textContent;
/** The live status arrives after the first paint (J1 until it lands): wait for the window to start at J8. */
const settled = () => waitFor(() => expect(windowLabel()).toMatch(/^J8–/));
const rows = () => screen.getByTestId('fixture-board-rows');
const ranks = () => Array.from(rows().querySelectorAll('.fx-rank')).map((el) => el.textContent);

describe('Compact window follows the width (one table, never split)', () => {
  test('1490 px shows 12 gameweeks, 770 px shows 10, 500 px shows 5', async () => {
    renderBoard(true);
    await waitFor(() => expect(windowLabel()).toBe('J8–J15')); // Detailed at 1490: 2 columns x 8
    view('Compacto');
    expect(windowLabel()).toBe('J8–J19');
    expect(rows().querySelector('.fx-compact')).toHaveStyle({ '--n': '12' });
    resize(770);
    expect(windowLabel()).toBe('J8–J17');
    resize(500);
    expect(windowLabel()).toBe('J8–J12');
  });

  test('an explicit pick keeps winning over the fit', async () => {
    renderBoard(true);
    await settled();
    view('Compacto');
    click(screen.getByRole('button', { name: '5' }));
    expect(windowLabel()).toBe('J8–J12');
    resize(2020);
    expect(windowLabel()).toBe('J8–J12');
  });
});

describe('ranks and column-first fill', () => {
  test('every view numbers the teams 1..20 in the board order', async () => {
    renderBoard(true);
    const expected = Array.from({ length: 20 }, (_, i) => String(i + 1));
    await waitFor(() => expect(ranks()).toEqual(expected)); // Detailed
    view('Compacto');
    expect(ranks()).toEqual(expected);
    view('Tendencia');
    expect(ranks()).toEqual(expected);
  });

  test('the team header of the in-chat card carries no rank', () => {
    const team = buildRealSeasonOutlook('attack').teams[0];
    const { container } = render(<TeamHeader team={team} />);
    expect(container.querySelector('.fx-rank')).toBeNull();
  });

  test('the Detailed grid is told how many rows each column holds (ceil(20 / columns))', async () => {
    renderBoard(true);
    await waitFor(() => expect(windowLabel()).toBe('J8–J15'));
    const grid = () => rows().querySelector('.fixture-rows') as HTMLElement;
    expect(grid()).toHaveStyle({ '--row-cols': '2', '--row-rows': '10' });
    resize(2026);
    expect(grid()).toHaveStyle({ '--row-cols': '2', '--row-rows': '10' }); // 2 x 12
    resize(880);
    expect(grid()).toHaveStyle({ '--row-cols': '1', '--row-rows': '20' });
  });

  test('the stylesheet fills the grid by columns, so the left column holds ranks 1..10', () => {
    const rule = CSS.match(/\.wide-workspace \.fixture-rows \{[^}]*\}/)?.[0] ?? '';
    expect(rule).toContain('grid-auto-flow: column');
    expect(rule).toContain('grid-template-rows: repeat(var(--row-rows');
    expect(rule).toContain('grid-template-columns: repeat(var(--row-cols');
  });
});

describe('Compact header is one line in the workspace, and nothing is dropped', () => {
  test('title, axis, window, legend and a note icon share one header; the long blocks are gone', async () => {
    renderBoard(true);
    await settled();
    view('Compacto');
    const header = screen.getByTestId('compact-header');
    expect(within(header).getByRole('heading', { name: 'Liga · orden por calendario' })).toBeInTheDocument();
    expect(within(header).getByText('Ataque')).toBeInTheDocument();
    expect(within(header).getByText(/Mejor calendario primero · FDR promedio J8–J19/)).toBeInTheDocument();
    expect(within(header).getByTestId('band-legend-inline')).toBeInTheDocument();
    expect(within(header).getByRole('button', { name: 'Nota sobre los datos' })).toBeInTheDocument();
    expect(screen.queryByTestId('fixture-provenance')).toBeNull();
    expect(screen.queryByText(/Calendario real desde la API oficial/)).toBeNull();
    // the standalone legend bar above the card is not rendered twice
    expect(screen.getAllByText('FDR')).toHaveLength(1);
  });

  test('the note stays reachable: tooltip and an inline panel with the stamp, the warning and the footer', async () => {
    renderBoard(true);
    await settled();
    view('Compacto');
    const icon = screen.getByRole('button', { name: 'Nota sobre los datos' });
    expect(icon.getAttribute('title')).toMatch(/La liga va por la jornada 7/);
    expect(icon).toHaveAttribute('aria-expanded', 'false');
    click(icon);
    expect(icon).toHaveAttribute('aria-expanded', 'true');
    const note = screen.getByTestId('compact-note');
    expect(within(note).getByTestId('fixture-provenance-warning').textContent).toMatch(/La liga va por la jornada 7/);
    expect(within(note).getByText(/Temporada 2026-27/)).toBeInTheDocument();
    expect(within(note).getByText(/Calendario real desde la API oficial de FPL/)).toBeInTheDocument();
    click(icon);
    expect(screen.queryByTestId('compact-note')).toBeNull();
  });

  test('Detailed keeps its full block in the workspace', async () => {
    renderBoard(true);
    await waitFor(() => expect(windowLabel()).toBe('J8–J15'));
    expect(screen.queryByTestId('compact-header')).toBeNull();
    expect(screen.getByTestId('fixture-provenance')).toBeInTheDocument();
    expect(screen.getByText(/Calendario real desde la API oficial/)).toBeInTheDocument();
  });
});

describe('mobile and the pager are unchanged', () => {
  test('outside the workspace Compact keeps the full block, the 5/8/10 selector and the 8-gameweek default', async () => {
    renderBoard(false);
    await settled();
    view('Compacto');
    expect(screen.queryByTestId('compact-header')).toBeNull();
    expect(screen.getByTestId('fixture-provenance')).toBeInTheDocument();
    expect(screen.getByText(/Calendario real desde la API oficial/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Liga · orden por calendario' })).toBeInTheDocument();
    expect(windowLabel()).toBe('J8–J15');
    expect(screen.queryByRole('button', { name: '12' })).toBeNull();
    expect(rows().querySelector('.fx-compact')).not.toBeNull();
  });

  test('the base tokens are the sizes Compact always had', () => {
    const base = CSS.match(/\n\.fx-compact \{[^}]*\}/)?.[0] ?? '';
    for (const token of ['--fx-team-col: 50px', '--fx-cell: 54px', '--fx-row-h: 24px', '--fx-opp: 12px',
      '--fx-venue: 8.5px', '--fx-gw: 11px', '--fx-team: 13px', '--fx-gap: 4px']) {
      expect(base).toContain(token);
    }
  });

  test('everything fluid, sticky or viewport-sized lives under .wide-workspace', () => {
    const rules = CSS.split('}').map((r) => r.trim()).filter(Boolean);
    const fluid = rules.filter((r) => /cqw|100dvh|container-type|position: sticky/.test(r));
    expect(fluid.length).toBeGreaterThan(0);
    for (const rule of fluid) expect(rule.startsWith('.wide-workspace')).toBe(true);
  });

  test('the rank is hidden by default and shown only in the workspace', () => {
    expect(CSS).toMatch(/\n\.fx-rank \{ display: none; \}/);
    expect(CSS).toMatch(/\.wide-workspace \.fx-rank \{ display: inline-block;/);
  });
});
