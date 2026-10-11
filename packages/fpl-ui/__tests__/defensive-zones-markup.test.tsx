/**
 * @jest-environment jsdom
 *
 * i152 guard: DefensiveZonesCard's markup must not change when its pitch
 * geometry is extracted into a shared component. The snapshot was recorded
 * on the card as it was BEFORE the extraction; the same file must pass after.
 */
import { render } from '@testing-library/react';

import DefensiveZonesCard from '../components/intents/DefensiveZonesCard';
import type { DefensiveZonesMeta } from '../lib/types';

const base: DefensiveZonesMeta = {
  opponent: 'Crystal Palace',
  weakness_label: 'Débil dentro del área',
  verdict: 'Ataca a Crystal Palace por la derecha dentro del área — concede un +70% sobre un equipo medio ahí.',
  zones: [
    { lateral: 'left', pct_over_avg: -31.7, opportunity_level: 'cool' },
    { lateral: 'central', pct_over_avg: 1.5, opportunity_level: 'warm' },
    { lateral: 'right', pct_over_avg: 69.8, opportunity_level: 'opp' },
  ],
  exploiters: [
    { rank: 1, web_name: 'Saka', team_short: 'ARS', position: 'MID', zone: 'in-box / right', fit_score: 10.0 },
  ],
  penalty_xga_per_game: 0.1402,
  ai_active: true,
};

describe('DefensiveZonesCard markup is stable (i152 extraction guard)', () => {
  test('mixed zones', () => {
    const { container } = render(<DefensiveZonesCard data={base} />);
    expect(container.innerHTML).toMatchSnapshot();
  });

  test('all-average zones (≈ media readings)', () => {
    const data: DefensiveZonesMeta = {
      ...base,
      zones: base.zones.map((z) => ({ ...z, pct_over_avg: 0.1, opportunity_level: 'cool' as const })),
    };
    const { container } = render(<DefensiveZonesCard data={data} />);
    expect(container.innerHTML).toMatchSnapshot();
  });

  test('every zone an opportunity, with provenance', () => {
    const data: DefensiveZonesMeta = {
      ...base,
      zones: base.zones.map((z) => ({ ...z, pct_over_avg: 40, opportunity_level: 'opp' as const })),
      data_provenance: {
        season: '2026-2027', season_label: '2026-27', live_season: '2026-2027', is_current: true,
        status: 'current', label: 'Datos: temporada 2026-27', ingested_at: '2026-09-01T10:00:00Z',
        n_matches: 380, n_shots: 9524,
      },
    };
    const { container } = render(<DefensiveZonesCard data={data} />);
    expect(container.innerHTML).toMatchSnapshot();
  });
});
