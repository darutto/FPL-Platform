/**
 * @jest-environment jsdom
 *
 * "One number, one place": a zone's % is written once, inside its box. The card used to print
 * it a second time, with one decimal, right under the big one ("+70%" over "+69.8%").
 */
import { render } from '@testing-library/react';
import '@testing-library/jest-dom';

import DefensiveZonesCard from '../components/intents/DefensiveZonesCard';
import { LocaleProvider } from '../lib/i18n/LocaleProvider';
import type { DefensiveZonesMeta } from '../lib/types';
import type { Locale } from '../lib/i18n/locale';

const data: DefensiveZonesMeta = {
  opponent: 'Crystal Palace',
  weakness_label: 'Ataca dentro del área',
  verdict: 'Ataca a Crystal Palace por la derecha dentro del área — concede un +70% sobre un equipo medio ahí.',
  zones: [
    { lateral: 'left', pct_over_avg: -31.7, opportunity_level: 'cool' },
    { lateral: 'central', pct_over_avg: 18.4, opportunity_level: 'warm' },
    { lateral: 'right', pct_over_avg: 69.8, opportunity_level: 'opp' },
  ],
  frontal_zones: [
    { lateral: 'left', pct_over_avg: 12.2, opportunity_level: 'warm' },
    { lateral: 'central', pct_over_avg: 41.0, opportunity_level: 'opp' },
    { lateral: 'right', pct_over_avg: -8.0, opportunity_level: 'cool' },
  ],
  exploiters: [],
  penalty_xga_per_game: 0.1402,
  ai_active: false,
} as DefensiveZonesMeta;

const readings = (locale: Locale) => {
  const { container } = render(
    <LocaleProvider initialLocale={locale} canSwitch={false}>
      <DefensiveZonesCard data={data} />
    </LocaleProvider>,
  );
  return Array.from(container.querySelectorAll('svg text')).map((node) => (node.textContent ?? '').trim());
};

describe.each(['es', 'en'] as const)('zone readings (%s)', (locale) => {
  test('each cell shows its rounded % once and no one-decimal twin', () => {
    const texts = readings(locale);
    // The three in-box and the three frontal cells: two are average ('≈ media'), four carry a %.
    expect(texts.filter((t) => /^\+\d+%$/.test(t)).sort()).toEqual(['+12%', '+18%', '+41%', '+70%']);
    expect(texts.filter((t) => /\d\.\d%/.test(t))).toEqual([]);
    expect(texts).toHaveLength(6);
  });
});
