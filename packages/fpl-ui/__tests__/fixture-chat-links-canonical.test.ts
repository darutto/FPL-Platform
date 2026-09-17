/**
 * i78-A — the canonical fixture-click phrases are a CONTRACT with the routing
 * measurement, and the contract file is generated from the functions, never
 * typed by hand.
 *
 * `field-notes/artifacts/i78a-canonical-phrases.json` (repo root) is what
 * `packages/fpl-grounded-assistant/scripts/tool_routing_corpus.py` loads to
 * measure which tool the orchestrator picks when a /fixtures cell or team row
 * is tapped. If someone rewrites `teamOutlookQuestion` / `fixtureCellQuestion`
 * (step 2c of the i78-A plan is exactly that), the measurement must run on
 * the NEW phrases, so this test fails the moment the JSON and the functions
 * disagree.
 *
 * Regenerate (then commit the JSON and re-measure):
 *
 *     I78A_WRITE_CANONICAL_PHRASES=1 npx jest __tests__/fixture-chat-links-canonical.test.ts
 *
 * Inputs: four teams x two axes for the team-row phrase; one phrase per cell
 * (the cell tap is axis-independent since i93-b: it asks for BOTH sides of
 * the match, so a cell is one phrase, not two). The non-DGW cells mirror the real 2026-27
 * bundle (`lib/data/fixture-outlook-2026-27.json`) as of 2026-09-13 — GW1
 * because that is the current/next GW of the frozen measurement bootstrap
 * (`field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json`), GW4 as
 * the plan's "future cell" example. The 2026-27 bundle has no double
 * gameweek yet, so the DGW cells are synthetic (flagged `dgw_synthetic`);
 * the phrase is still produced by the real function from a real-shaped cell.
 */
import * as fs from 'fs';
import * as path from 'path';

import { fixtureCellQuestion, teamOutlookQuestion } from '../lib/fixture-chat-links';
import type { FixtureAxis, FixtureOutlookGW } from '../lib/types';

export const CANONICAL_PHRASES_PATH = path.resolve(
  __dirname,
  '../../../field-notes/artifacts/i78a-canonical-phrases.json',
);

const AXES: readonly FixtureAxis[] = ['attack', 'defence'];

interface TeamInputs {
  /** Bundle `team_name` — exactly what the UI passes to the functions. */
  team_name: string;
  team_short: string;
  /** Real GW1 cell (frozen-bootstrap current GW). */
  gw1: FixtureOutlookGW;
  /** Real GW4 cell (the plan's future-cell example). */
  gw4: FixtureOutlookGW;
  /**
   * i101: more real future cells, each at least 2 GWs past the frozen
   * bootstrap's current GW (1). The argument measurement needs phrases
   * whose gameweek the model cannot get right by guessing horizon=1.
   */
  future_extra: FixtureOutlookGW[];
  /** Synthetic second fixture appended to GW1 to form a DGW cell. */
  dgw_extra: { opponent_short: string; is_home: boolean; band: number };
}

function cell(
  gameweek: number,
  fixtures: { opponent_short: string; is_home: boolean; band: number }[],
): FixtureOutlookGW {
  const band = Math.round(fixtures.reduce((s, f) => s + f.band, 0) / fixtures.length);
  return {
    gameweek,
    band,
    klass: band <= 2 ? 'good' : band >= 4 ? 'bad' : 'neutral',
    is_dgw: fixtures.length >= 2,
    is_bgw: false,
    fixtures,
  };
}

/** Real cells copied from lib/data/fixture-outlook-2026-27.json (attack axis). */
const TEAMS: readonly TeamInputs[] = [
  {
    team_name: 'Newcastle', team_short: 'NEW',
    gw1: cell(1, [{ opponent_short: 'LIV', is_home: true, band: 4 }]),
    gw4: cell(4, [{ opponent_short: 'LEE', is_home: false, band: 3 }]),
    dgw_extra: { opponent_short: 'SUN', is_home: false, band: 3 },
    future_extra: [
      cell(3, [{ opponent_short: 'BOU', is_home: true, band: 3 }]),
      cell(5, [{ opponent_short: 'HUL', is_home: true, band: 2 }]),
      cell(6, [{ opponent_short: 'COV', is_home: false, band: 2 }]),
    ],
  },
  {
    team_name: 'Man City', team_short: 'MCI',
    gw1: cell(1, [{ opponent_short: 'BOU', is_home: true, band: 3 }]),
    gw4: cell(4, [{ opponent_short: 'MUN', is_home: false, band: 4 }]),
    dgw_extra: { opponent_short: 'HUL', is_home: false, band: 2 },
    future_extra: [
      cell(3, [{ opponent_short: 'COV', is_home: true, band: 2 }]),
      cell(5, [{ opponent_short: 'SUN', is_home: true, band: 2 }]),
      cell(6, [{ opponent_short: 'LIV', is_home: false, band: 4 }]),
    ],
  },
  {
    team_name: 'Liverpool', team_short: 'LIV',
    gw1: cell(1, [{ opponent_short: 'NEW', is_home: false, band: 3 }]),
    gw4: cell(4, [{ opponent_short: 'FUL', is_home: true, band: 2 }]),
    dgw_extra: { opponent_short: 'IPS', is_home: true, band: 2 },
    future_extra: [
      cell(3, [{ opponent_short: 'IPS', is_home: false, band: 2 }]),
      cell(5, [{ opponent_short: 'BOU', is_home: false, band: 3 }]),
      cell(6, [{ opponent_short: 'MCI', is_home: true, band: 4 }]),
    ],
  },
  {
    team_name: 'Spurs', team_short: 'TOT',
    gw1: cell(1, [{ opponent_short: 'BRE', is_home: false, band: 3 }]),
    gw4: cell(4, [{ opponent_short: 'EVE', is_home: true, band: 3 }]),
    dgw_extra: { opponent_short: 'COV', is_home: true, band: 2 },
    future_extra: [
      cell(3, [{ opponent_short: 'NFO', is_home: false, band: 3 }]),
      cell(5, [{ opponent_short: 'AVL', is_home: true, band: 3 }]),
      cell(6, [{ opponent_short: 'MUN', is_home: false, band: 4 }]),
    ],
  },
];

export interface CanonicalPhrase {
  id: string;
  kind: 'teamOutlookQuestion' | 'fixtureCellQuestion';
  team_name: string;
  team_short: string;
  /** 'both' for fixtureCellQuestion (the cell phrase asks both axes). */
  axis: FixtureAxis | 'both';
  /** null for teamOutlookQuestion (it has no gameweek argument). */
  gameweek: number | null;
  is_dgw: boolean;
  dgw_synthetic: boolean;
  /** 'current' = the frozen bootstrap's GW; 'future' = a later cell. */
  cell_position: 'current' | 'future' | null;
  question: string;
}

function axisTag(axis: FixtureAxis): string {
  return axis === 'attack' ? 'att' : 'def';
}

/** The whole corpus, produced by the functions the UI actually calls. */
export function buildCanonicalPhrases(): CanonicalPhrase[] {
  const out: CanonicalPhrase[] = [];
  for (const t of TEAMS) {
    const slug = t.team_short.toLowerCase();
    for (const axis of AXES) {
      out.push({
        id: `fc-${slug}-${axisTag(axis)}-team`,
        kind: 'teamOutlookQuestion',
        team_name: t.team_name, team_short: t.team_short, axis,
        gameweek: null, is_dgw: false, dgw_synthetic: false, cell_position: null,
        question: teamOutlookQuestion(t.team_name, axis),
      });
    }
    // Cell phrases (i93-b): one per cell, both axes in the same question.
    out.push({
      id: `fc-${slug}-cell`,
      kind: 'fixtureCellQuestion',
      team_name: t.team_name, team_short: t.team_short, axis: 'both',
      gameweek: t.gw1.gameweek, is_dgw: false, dgw_synthetic: false, cell_position: 'current',
      question: fixtureCellQuestion(t.team_name, t.gw1),
    });
    const dgw = cell(t.gw1.gameweek, [...t.gw1.fixtures, t.dgw_extra]);
    out.push({
      id: `fc-${slug}-cell-dgw`,
      kind: 'fixtureCellQuestion',
      team_name: t.team_name, team_short: t.team_short, axis: 'both',
      gameweek: dgw.gameweek, is_dgw: true, dgw_synthetic: true, cell_position: 'current',
      question: fixtureCellQuestion(t.team_name, dgw),
    });
    // Future cell (the plan's example): does a cell that is not the current
    // GW route the same way?
    out.push({
      id: `fc-${slug}-cell-future`,
      kind: 'fixtureCellQuestion',
      team_name: t.team_name, team_short: t.team_short, axis: 'both',
      gameweek: t.gw4.gameweek, is_dgw: false, dgw_synthetic: false, cell_position: 'future',
      question: fixtureCellQuestion(t.team_name, t.gw4),
    });
    // i101: further future cells (J3, J5, J6 -- all >= current+2 on the frozen
    // bootstrap). The i78-A routing matrix keeps its base set by id suffix;
    // the i101 argument measurement selects these by cell_position + gameweek.
    for (const fx of t.future_extra) {
      out.push({
        id: `fc-${slug}-cell-j${fx.gameweek}`,
        kind: 'fixtureCellQuestion',
        team_name: t.team_name, team_short: t.team_short, axis: 'both',
        gameweek: fx.gameweek, is_dgw: false, dgw_synthetic: false, cell_position: 'future',
        question: fixtureCellQuestion(t.team_name, fx),
      });
    }
  }
  return out;
}

export interface CanonicalPhrasesFile {
  generated_by: string;
  source: string;
  note: string;
  phrases: CanonicalPhrase[];
}

export function buildCanonicalPhrasesFile(): CanonicalPhrasesFile {
  return {
    generated_by: 'packages/fpl-ui/__tests__/fixture-chat-links-canonical.test.ts',
    source: 'packages/fpl-ui/lib/fixture-chat-links.ts',
    note:
      'GENERATED — do not edit by hand. Regenerate with ' +
      'I78A_WRITE_CANONICAL_PHRASES=1 npx jest __tests__/fixture-chat-links-canonical.test.ts ' +
      'and re-run the i78-A routing measurement.',
    phrases: buildCanonicalPhrases(),
  };
}

describe('i78-A canonical fixture-click phrases', () => {
  const built = buildCanonicalPhrasesFile();

  test('4 teams x (2 team-row axes + cell + dgw cell + future cell + 3 i101 cells) = 32 unique phrases', () => {
    expect(built.phrases).toHaveLength(32);
    expect(new Set(built.phrases.map((p) => p.id)).size).toBe(32);
    expect(new Set(built.phrases.map((p) => p.question)).size).toBe(32);
  });

  test('every phrase names its team and its axis in the words the UI uses', () => {
    for (const p of built.phrases) {
      expect(p.question).toContain(p.team_name);
      if (p.axis === 'attack') expect(p.question).toMatch(/ofensiv/);
      else if (p.axis === 'defence') expect(p.question).toMatch(/portería a cero/);
      else {
        // i93-b: the cell phrase asks both sides of the match, whatever view
        // it was tapped from.
        expect(p.kind).toBe('fixtureCellQuestion');
        expect(p.question).toMatch(/ofensivamente y defensivamente/);
      }
      if (p.kind === 'fixtureCellQuestion') {
        expect(p.axis).toBe('both');
        expect(p.question).toContain(`J${p.gameweek}`);
        expect(p.question.includes('doble jornada')).toBe(p.is_dgw);
      }
    }
  });

  test('the committed JSON is exactly what the functions generate today', () => {
    if (process.env.I78A_WRITE_CANONICAL_PHRASES === '1') {
      fs.mkdirSync(path.dirname(CANONICAL_PHRASES_PATH), { recursive: true });
      fs.writeFileSync(CANONICAL_PHRASES_PATH, JSON.stringify(built, null, 2) + '\n', 'utf8');
    }
    expect(fs.existsSync(CANONICAL_PHRASES_PATH)).toBe(true);
    const onDisk = JSON.parse(fs.readFileSync(CANONICAL_PHRASES_PATH, 'utf8'));
    // Whole-object equality: a phrase rewrite, a renamed id, a changed input
    // cell — any of them means the measurement no longer describes the UI.
    expect(onDisk).toEqual(built);
  });
});
