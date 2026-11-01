/**
 * @jest-environment jsdom
 */
/**
 * R6 two-player involvement card. The fixtures are generic_card bodies the backend composer produced for a SYNTHETIC
 * store (packages/fpl-grounded-assistant/tests/test_r6_involvement_compare.py: Palmer vs Saka, Saka has no GW5 match),
 * not production data.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import GenericCard from '../components/intents/GenericCard';
import InvolvementCompareCard, { FIGURE_CLASS, fitLine, runs } from '../components/intents/InvolvementCompareCard';
import type { GenericCardMeta, InvolvementCompareMeta } from '../lib/types';
import es from './fixtures/involvement-compare-es.json';
import en from './fixtures/involvement-compare-en.json';

const ES = es as unknown as GenericCardMeta;
const EN = en as unknown as GenericCardMeta;
const payload = (card: GenericCardMeta): InvolvementCompareMeta => card.involvement_compare as InvolvementCompareMeta;
const clone = (p: InvolvementCompareMeta): InvolvementCompareMeta => JSON.parse(JSON.stringify(p));

const COLOR_CLASS = /text-bf-(turquoise|cyan|coral|coral-soft|gold)/;

function figure(container: HTMLElement, metric: string, side: 'a' | 'b'): HTMLElement {
  const row = container.querySelector(`[data-metric="${metric}"]`) as HTMLElement;
  return row.querySelector(`[data-side="${side}"]`) as HTMLElement;
}

describe('routing', () => {
  test('GenericCard draws the comparison card when the payload is present', () => {
    render(<GenericCard data={ES} />);
    expect(screen.getByTestId('involvement-compare-card')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  test('without the payload GenericCard keeps its table', () => {
    render(<GenericCard data={{ ...ES, involvement_compare: null }} />);
    expect(screen.queryByTestId('involvement-compare-card')).not.toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
  });
});

describe('Per 90 view (default)', () => {
  test('five metrics with both players, Spanish labels', () => {
    render(<InvolvementCompareCard data={payload(ES)} />);
    for (const label of ['Toques/90', 'Clave/90', 'Pases/90', 'Acierto', 'Atrás']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText('Palmer')).toBeInTheDocument();
    expect(screen.getByText('Saka')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Por 90' })).toHaveAttribute('aria-pressed', 'true');
  });

  test('the winner keeps the full figure and the other is dimmed; no figure carries a colour', () => {
    const { container } = render(<InvolvementCompareCard data={payload(ES)} />);
    // touches: Saka (b) wins; key passes: Palmer (a) wins
    expect(figure(container, 'touches', 'b').className).toBe(FIGURE_CLASS.lead);
    expect(figure(container, 'touches', 'a').className).toBe(FIGURE_CLASS.dim);
    expect(figure(container, 'key_passes', 'a').className).toBe(FIGURE_CLASS.lead);
    expect(figure(container, 'key_passes', 'b').className).toBe(FIGURE_CLASS.dim);
    container.querySelectorAll('[data-side]').forEach((el) => expect(el.className).not.toMatch(COLOR_CLASS));
  });

  test('a tie dims neither side', () => {
    const { container } = render(<InvolvementCompareCard data={payload(ES)} />);
    // passes: 40 vs 40 in the fixture, winner null
    expect(figure(container, 'passes', 'a').className).toBe(FIGURE_CLASS.lead);
    expect(figure(container, 'passes', 'b').className).toBe(FIGURE_CLASS.lead);
  });

  test('the backward share has no winner: both neutral', () => {
    const p = clone(payload(ES));
    p.per90[4] = { ...p.per90[4], a: 23.2, b: 12 };
    const { container } = render(<InvolvementCompareCard data={p} />);
    expect(figure(container, 'backward_share', 'a').className).toBe(FIGURE_CLASS.neutral);
    expect(figure(container, 'backward_share', 'b').className).toBe(FIGURE_CLASS.neutral);
    expect(figure(container, 'backward_share', 'a')).toHaveTextContent('23.2%');
  });

  test('an unknown value reads as a dash, with no bar', () => {
    const p = clone(payload(ES));
    p.per90[1] = { ...p.per90[1], b: null, winner: null };
    const { container } = render(<InvolvementCompareCard data={p} />);
    expect(figure(container, 'key_passes', 'b')).toHaveTextContent('–');
    expect(figure(container, 'key_passes', 'b').nextElementSibling).toBeNull();
  });

  test('the footer says how many matches each player has', () => {
    render(<InvolvementCompareCard data={payload(ES)} />);
    expect(screen.getByText('Palmer: 6 partidos · Saka: 5 partidos · totales por partido, sin zonas del campo'))
      .toBeInTheDocument();
  });
});

describe('By match view', () => {
  function openSeries(card: GenericCardMeta, name: string) {
    const utils = render(<InvolvementCompareCard data={payload(card)} />);
    fireEvent.click(screen.getByRole('button', { name }));
    return utils;
  }

  test('the view icon switches to the series, with gameweek labels and averages', () => {
    const { container } = openSeries(ES, 'Por jornada');
    expect(container.querySelector('[data-view="series"]')).toBeInTheDocument();
    expect(container.querySelector('[data-view="per90"]')).not.toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Toques por partido' })).toBeInTheDocument();
    for (const gw of ['J1', 'J6']) expect(screen.getByText(gw)).toBeInTheDocument();
    expect(screen.getByText('media /90')).toBeInTheDocument();
  });

  test('a gameweek one player did not play breaks the line, it is not drawn as zero', () => {
    const { container } = openSeries(ES, 'Por jornada');
    expect(container.querySelectorAll('[data-run="b"]').length).toBe(2);   // GW1-4, then GW6
    expect(container.querySelectorAll('[data-run="a"]').length).toBe(1);
    expect(container.querySelectorAll('[data-series="b"] circle').length).toBe(5);
  });

  test('the trend marks come from the payload, labelled for screen readers', () => {
    openSeries(ES, 'Por jornada');
    expect(screen.getByRole('img', { name: 'Al alza en estos partidos' })).toHaveTextContent('↗');
    expect(screen.getByRole('img', { name: 'A la baja en estos partidos' })).toHaveTextContent('↘');
  });

  test('no trend mark under three matches (trend null)', () => {
    const p = clone(payload(ES));
    p.series.metrics[0].trend_b = null;
    render(<InvolvementCompareCard data={p} />);
    fireEvent.click(screen.getByRole('button', { name: 'Por jornada' }));
    expect(screen.queryByRole('img', { name: 'A la baja en estos partidos' })).not.toBeInTheDocument();
  });

  test('the metric icons switch the series; the averages keep the typographic hierarchy', () => {
    const { container } = openSeries(ES, 'Por jornada');
    fireEvent.click(screen.getByRole('button', { name: 'Pases clave por partido' }));
    expect(screen.getByRole('img', { name: 'Pases clave por partido' })).toBeInTheDocument();
    const series = container.querySelector('[data-view="series"]') as HTMLElement;
    const a = series.querySelector('[data-side="a"]') as HTMLElement;
    const b = series.querySelector('[data-side="b"]') as HTMLElement;
    expect(a).toHaveTextContent('2.5');
    expect(a.className).toBe(FIGURE_CLASS.lead);   // Palmer leads key passes
    expect(b).toHaveTextContent('1');
    expect(b.className).toBe(FIGURE_CLASS.dim);
  });

  test('a dashed trend line per player with at least three known values', () => {
    const { container } = openSeries(ES, 'Por jornada');
    expect(container.querySelector('[data-trendline="a"]')).toBeInTheDocument();
    expect(container.querySelector('[data-trendline="b"]')).toBeInTheDocument();
  });
});

describe('English', () => {
  test('both views read in English from the payload', () => {
    render(<InvolvementCompareCard data={payload(EN)} />);
    expect(screen.getByText('Comparison · involvement')).toBeInTheDocument();
    expect(screen.getByText('Touches/90')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'By match' }));
    expect(screen.getByText('GW1')).toBeInTheDocument();
    expect(screen.getByText('avg /90')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Trending up over these matches' })).toBeInTheDocument();
  });
});

describe('geometry helpers', () => {
  test('runs split at gaps', () => {
    expect(runs([1, 2, null, 4])).toEqual([[[0, 1], [1, 2]], [[3, 4]]]);
  });

  test('the drawn fit uses axis positions and needs three values', () => {
    expect(fitLine([1, null])).toBeNull();
    const fit = fitLine([30, 10, null, null, null, null, 31])!;
    expect(fit.at(6)).toBeGreaterThan(fit.at(0));   // same direction as the backend's "up" for this series
  });
});
