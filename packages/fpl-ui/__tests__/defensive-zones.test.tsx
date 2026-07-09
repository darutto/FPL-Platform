/**
 * @jest-environment jsdom
 *
 * Defensive Zones card tests (T4b).
 *
 * Covers:
 *   - pure helpers in lib/defensive-zones.ts (formatting, level→class maps,
 *     zone-pill labels, verdict splitting, graceful sub-line degradation)
 *   - selectIntentView gating for the zonal_opportunity intent
 *   - DefensiveZonesCard rendering (jsdom + Testing Library): header,
 *     3 zone readings with correct opportunity coding, exploiter table,
 *     penalty footer, IA badge, empty-exploiters fallback
 */
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import {
  LEVEL_PILL_LABEL,
  LEVEL_TEXT_CLASS,
  LEVEL_BAR_HEIGHT_PCT,
  formatPct,
  formatFit,
  formatPenalty,
  rankOpacity,
  zonePillLabel,
  levelForZone,
  positionEs,
  exploiterSub,
  splitVerdict,
} from '../lib/defensive-zones';
import { selectIntentView } from '../lib/intent-renderer';
import DefensiveZonesCard from '../components/intents/DefensiveZonesCard';
import type { AskResponse, DefensiveZonesMeta } from '../lib/types';

// ---------------------------------------------------------------------------
// Fixture — mirrors the real Crystal Palace payload (checkpoint 1)
// ---------------------------------------------------------------------------

const palaceMeta: DefensiveZonesMeta = {
  opponent: 'Crystal Palace',
  weakness_label: 'Débil dentro del área',
  verdict:
    'Crystal Palace concede más de lo normal dentro del área, sobre todo por ' +
    'su costado derecho — un +70% sobre un equipo medio.',
  zones: [
    { lateral: 'left', pct_over_avg: 69.8, opportunity_level: 'opp' },
    { lateral: 'central', pct_over_avg: 1.5, opportunity_level: 'warm' },
    { lateral: 'right', pct_over_avg: -31.7, opportunity_level: 'cool' },
  ],
  exploiters: [
    { rank: 1, web_name: 'Saka', team_short: 'ARS', position: 'MID', zone: 'in-box / left', fit_score: 10.0 },
    { rank: 2, web_name: 'Bowen', team_short: 'WHU', position: 'FWD', zone: 'in-box / left', fit_score: 9.5 },
    { rank: 3, web_name: 'Alejandro Jiménez', team_short: 'BOU', position: '', zone: 'in-box / left', fit_score: 3.2 },
  ],
  penalty_xga_per_game: 0.1402,
  ai_active: true,
};

const zonalOkResponse: AskResponse = {
  final_text: 'Crystal Palace concede más de lo normal dentro del área…',
  outcome: 'ok',
  supported: true,
  intent: 'zonal_opportunity',
  review_passed: true,
  llm_used: true,
  orch_outcome: 'ok',
  captain: null,
  captain_ranking: null,
  comparison: null,
  transfer: null,
  chip: null,
  fixture_run: null,
  differential: null,
  sub_responses: null,
  zonal_opportunity: palaceMeta,
  degraded: false,
  resource_rows: null,
};

// ---------------------------------------------------------------------------
// Helpers — formatting
// ---------------------------------------------------------------------------

describe('formatPct', () => {
  test('real edge rounds to whole percent with +', () => {
    expect(formatPct(69.8)).toBe('+70%');
    expect(formatPct(1.5)).toBe('+2%');
    expect(formatPct(15)).toBe('+15%');
  });

  test('below +0.5% (incl. negatives) reads ≈ 0% — no negative opportunity', () => {
    expect(formatPct(0.4)).toBe('≈ 0%');
    expect(formatPct(0)).toBe('≈ 0%');
    expect(formatPct(-31.7)).toBe('≈ 0%');
  });
});

describe('formatFit / formatPenalty / rankOpacity', () => {
  test('fit renders one decimal', () => {
    expect(formatFit(10)).toBe('10.0');
    expect(formatFit(9.53)).toBe('9.5');
  });

  test('penalty renders three decimals', () => {
    expect(formatPenalty(0.1402)).toBe('0.140');
  });

  test('rank fade 1 → .85 → .72 then held', () => {
    expect(rankOpacity(1)).toBe(1);
    expect(rankOpacity(2)).toBe(0.85);
    expect(rankOpacity(3)).toBe(0.72);
    expect(rankOpacity(5)).toBe(0.72);
  });
});

// ---------------------------------------------------------------------------
// Helpers — zone naming + level lookup
// ---------------------------------------------------------------------------

describe('zonePillLabel', () => {
  test('in-box zones use short lateral labels', () => {
    expect(zonePillLabel('in-box / left')).toBe('Izq');
    expect(zonePillLabel('in-box / central')).toBe('Centro');
    expect(zonePillLabel('in-box / right')).toBe('Der');
  });

  test('edge-of-box zones are prefixed', () => {
    expect(zonePillLabel('edge-of-box / left')).toBe('Frontal izq');
  });

  test('unknown zone strings pass through untouched', () => {
    expect(zonePillLabel('weird')).toBe('weird');
  });
});

describe('levelForZone', () => {
  test('in-box zones read the matching cell level', () => {
    expect(levelForZone('in-box / left', palaceMeta.zones)).toBe('opp');
    expect(levelForZone('in-box / central', palaceMeta.zones)).toBe('warm');
    expect(levelForZone('in-box / right', palaceMeta.zones)).toBe('cool');
  });

  test('edge-of-box weak zones default to warm (not on the pitch view)', () => {
    expect(levelForZone('edge-of-box / left', palaceMeta.zones)).toBe('warm');
  });
});

describe('level maps encode opportunity, never coral', () => {
  test('opp is turquoise, warm gold, cool grey', () => {
    expect(LEVEL_TEXT_CLASS.opp).toContain('turquoise');
    expect(LEVEL_TEXT_CLASS.warm).toContain('gold');
    expect(LEVEL_TEXT_CLASS.cool).toContain('gray');
    for (const cls of Object.values(LEVEL_TEXT_CLASS)) {
      expect(cls).not.toContain('coral');
    }
  });

  test('pill copy matches the handoff', () => {
    expect(LEVEL_PILL_LABEL).toEqual({
      opp: 'tu mejor zona',
      warm: 'ventaja leve',
      cool: 'sin ventaja',
    });
  });

  test('bar heights are level-keyed (opp tallest)', () => {
    const toNum = (pct: string) => parseFloat(pct);
    expect(toNum(LEVEL_BAR_HEIGHT_PCT.opp)).toBeGreaterThan(
      toNum(LEVEL_BAR_HEIGHT_PCT.warm),
    );
    expect(toNum(LEVEL_BAR_HEIGHT_PCT.warm)).toBeGreaterThan(
      toNum(LEVEL_BAR_HEIGHT_PCT.cool),
    );
  });
});

// ---------------------------------------------------------------------------
// Helpers — player sub-line + verdict split
// ---------------------------------------------------------------------------

describe('positionEs / exploiterSub', () => {
  test('FPL position codes map to Spanish', () => {
    expect(positionEs('MID')).toBe('MED');
    expect(positionEs('FWD')).toBe('DEL');
    expect(positionEs('GKP')).toBe('POR');
    expect(positionEs('DEF')).toBe('DEF');
  });

  test('sub-line joins with · and drops empty segments (join-miss degrade)', () => {
    expect(exploiterSub('ARS', 'MID')).toBe('ARS · MED');
    expect(exploiterSub('BOU', '')).toBe('BOU');
    expect(exploiterSub('', '')).toBe('');
  });
});

describe('splitVerdict', () => {
  test('bolds the +NN% token and keeps surrounding text', () => {
    const segs = splitVerdict(palaceMeta.verdict);
    const highlighted = segs.filter((s) => s.highlight);
    expect(highlighted).toHaveLength(1);
    expect(highlighted[0].text).toBe('+70%');
    expect(segs.map((s) => s.text).join('')).toBe(palaceMeta.verdict);
  });

  test('verdicts without a pct stay a single plain segment', () => {
    const segs = splitVerdict('Sin debilidad clara en ninguna zona.');
    expect(segs).toEqual([
      { text: 'Sin debilidad clara en ninguna zona.', highlight: false },
    ]);
  });
});

// ---------------------------------------------------------------------------
// selectIntentView gating
// ---------------------------------------------------------------------------

describe('selectIntentView — zonal_opportunity', () => {
  test('ok + meta with zones → defensive_zones', () => {
    expect(selectIntentView(zonalOkResponse)).toBe('defensive_zones');
  });

  test('non-ok outcome → null', () => {
    expect(
      selectIntentView({ ...zonalOkResponse, outcome: 'not_found' }),
    ).toBeNull();
  });

  test('ok but null meta → null (field CAN be null on ok turns)', () => {
    expect(
      selectIntentView({ ...zonalOkResponse, zonal_opportunity: null }),
    ).toBeNull();
  });

  test('ok but empty zones → null (never a half-empty card)', () => {
    expect(
      selectIntentView({
        ...zonalOkResponse,
        zonal_opportunity: { ...palaceMeta, zones: [] },
      }),
    ).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// DefensiveZonesCard rendering
// ---------------------------------------------------------------------------

describe('DefensiveZonesCard', () => {
  test('renders header: kicker, opponent, weakness pill', () => {
    render(<DefensiveZonesCard data={palaceMeta} />);
    expect(screen.getByText('Zonas que concede')).toBeInTheDocument();
    expect(screen.getByText('Crystal Palace')).toBeInTheDocument();
    expect(screen.getByText('Débil dentro del área')).toBeInTheDocument();
  });

  test('renders 3 zone readings with correct values, labels and pills', () => {
    render(<DefensiveZonesCard data={palaceMeta} />);
    // +70% appears twice: bolded in the verdict AND as the left reading
    expect(screen.getAllByText('+70%').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('+2%')).toBeInTheDocument();
    expect(screen.getByText('≈ 0%')).toBeInTheDocument();
    expect(screen.getByText('Izquierda')).toBeInTheDocument();
    expect(screen.getByText('Centro')).toBeInTheDocument();
    expect(screen.getByText('Derecha')).toBeInTheDocument();
    expect(screen.getByText('tu mejor zona')).toBeInTheDocument();
    expect(screen.getByText('ventaja leve')).toBeInTheDocument();
    expect(screen.getByText('sin ventaja')).toBeInTheDocument();
  });

  test('pitch bars carry level-coded heights', () => {
    render(<DefensiveZonesCard data={palaceMeta} />);
    expect(screen.getByTestId('zone-bar-left')).toHaveStyle({
      height: LEVEL_BAR_HEIGHT_PCT.opp,
    });
    expect(screen.getByTestId('zone-bar-central')).toHaveStyle({
      height: LEVEL_BAR_HEIGHT_PCT.warm,
    });
    expect(screen.getByTestId('zone-bar-right')).toHaveStyle({
      height: LEVEL_BAR_HEIGHT_PCT.cool,
    });
  });

  test('renders exploiter table with rank, name, team·pos, zone pill, fit', () => {
    render(<DefensiveZonesCard data={palaceMeta} />);
    expect(screen.getByText('Quién lo explota')).toBeInTheDocument();
    expect(screen.getByText('Saka')).toBeInTheDocument();
    expect(screen.getByText('ARS · MED')).toBeInTheDocument();
    expect(screen.getByText('10.0')).toBeInTheDocument();
    expect(screen.getAllByText('Izq')).toHaveLength(3);
    // join-miss degrade: player still listed, no dangling separator
    expect(screen.getByText('Alejandro Jiménez')).toBeInTheDocument();
    expect(screen.getByText('BOU')).toBeInTheDocument();
    expect(screen.queryByText('BOU ·')).not.toBeInTheDocument();
  });

  test('renders penalty footer and IA badge when ai_active', () => {
    render(<DefensiveZonesCard data={palaceMeta} />);
    expect(screen.getByText('0.140 xGA/partido')).toBeInTheDocument();
    expect(screen.getByText('IA activa')).toBeInTheDocument();
  });

  test('hides IA badge when ai_active=false', () => {
    render(
      <DefensiveZonesCard data={{ ...palaceMeta, ai_active: false }} />,
    );
    expect(screen.queryByText('IA activa')).not.toBeInTheDocument();
  });

  test('empty exploiters shows the fallback line, not the table', () => {
    render(<DefensiveZonesCard data={{ ...palaceMeta, exploiters: [] }} />);
    expect(screen.queryByText('Quién lo explota')).not.toBeInTheDocument();
    expect(
      screen.getByText('Sin perfiles de jugador que encajen en estas zonas todavía.'),
    ).toBeInTheDocument();
  });
});
