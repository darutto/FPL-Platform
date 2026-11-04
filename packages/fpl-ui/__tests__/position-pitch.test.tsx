/**
 * @jest-environment jsdom
 */
/**
 * Position-changes mini-pitch ("canchita") inside GenericCard. Synthetic payloads only (never licensed values).
 */
import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import GenericCard from '@/components/intents/GenericCard';
import PositionPitch, {
  MAX_DOT_DISTANCE, dotDistance, hitsConnector, labelRect, outsideField, placeLabel, placeRole,
} from '@/components/intents/PositionPitch';
import { LocaleProvider } from '@/lib/i18n/LocaleProvider';
import type { GenericCardMeta, PositionPitchMeta } from '@/lib/types';

const SWITCH: PositionPitchMeta = {
  kind: 'switch',
  from: { detailed_position: 'Right Midfield', side: 'right', line: 'MID' },
  to: { detailed_position: 'Attacker', side: null, line: 'FWD' },
  labels: { from: 'J1–J4 · Banda derecha', to: 'J5–J8 · Delantero', table: 'Desde el cambio, por 90', before: 'Antes', after: 'Después' },
  rows: [
    { metric: 'touches', label: 'Toques', before: 48, after: 41 },
    { metric: 'key_passes', label: 'Pases clave', before: 1.75, after: null },
  ],
  note: '4 y 4 partidos con 30+ min',
  claim_status: 'observed',
};

const LISTING: PositionPitchMeta = {
  kind: 'fpl_listing',
  from: { fpl_position: 'DEF', line: 'DEF' },
  to: { detailed_position: 'Left Midfield', side: 'left', line: 'MID' },
  labels: { from: 'FPL: DEF', to: 'J1–J6 · Banda izquierda', table: 'Como banda izquierda, por 90', before: 'Antes', after: 'Después' },
  rows: [{ metric: 'touches', label: 'Toques', value: 44.25 }],
  note: '5 partidos con 30+ min',
  claim_status: 'observed',
};

const pct = (el: HTMLElement, prop: 'left' | 'top') => parseFloat(el.style[prop]);

describe('placement: attack up, attacker left = viewer left, from role + side only', () => {
  test('a forward sits nearer the top than a winger, centred', () => {
    const fwd = placeRole({ detailed_position: 'Attacker', side: null });
    const rm = placeRole({ detailed_position: 'Right Midfield', side: 'right' });
    expect(fwd.y).toBeLessThan(rm.y);
    expect(fwd.x).toBe(50);
    expect(rm.x).toBeGreaterThan(70);
    expect(placeRole({ detailed_position: 'Left Back', side: 'left' }).x).toBeLessThan(30);
  });

  test('an FPL listing with no role sits on its line, on the side of the role actually played', () => {
    const p = placeRole({ fpl_position: 'DEF', line: 'DEF' }, 'left');
    expect(p.y).toBeGreaterThan(placeRole({ detailed_position: 'Left Midfield', side: 'left' }).y);
    expect(p.x).toBeLessThan(30);
  });
});

describe('the pitch is vertical, in real proportions', () => {
  test('the container and the drawing are taller than wide, and nothing stretches the circle', () => {
    const { container } = render(<PositionPitch data={SWITCH} />);
    const frame = screen.getByTestId('position-pitch-box');
    const [w, h] = (frame.className.match(/aspect-\[(\d+)\/(\d+)\]/) ?? []).slice(1).map(Number);
    expect(h).toBeGreaterThan(w);
    const svg = frame.querySelector('svg') as SVGSVGElement;
    const [, , vw, vh] = svg.getAttribute('viewBox')!.split(' ').map(Number);
    expect(vh).toBeGreaterThan(vw);
    expect(vw / vh).toBeCloseTo(w / h, 5); // box and drawing share one aspect
    expect(svg.getAttribute('preserveAspectRatio')).not.toBe('none');
    const field = svg.querySelector('rect') as SVGRectElement;
    const ratio = Number(field.getAttribute('width')) / Number(field.getAttribute('height'));
    expect(ratio).toBeGreaterThan(0.62); // ≈ 68/105
    expect(ratio).toBeLessThan(0.67);
    expect(container.innerHTML).not.toMatch(/aspect-\[5\/3\]/);
  });
});

describe('a role switch', () => {
  test('old role is a dashed ring, new role a solid dot above it, joined by an arrow', () => {
    const { container } = render(<PositionPitch data={SWITCH} />);
    const old = container.querySelector('[data-role="old"]') as HTMLElement;
    const now = container.querySelector('[data-role="new"]') as HTMLElement;
    expect(pct(now, 'top')).toBeLessThan(pct(old, 'top'));
    expect(pct(old, 'left')).toBeGreaterThan(70); // right midfield on the viewer's right
    expect(container.querySelector('[data-connector="arrow"] polygon')).not.toBeNull();
    expect(container.querySelector('[data-role="listing"]')).toBeNull();
    expect(screen.getByText('J1–J4')).toBeInTheDocument();
    expect(screen.getByText('Delantero')).toBeInTheDocument();
  });

  test('the table is neutral: one decimal with a dot in Spanish too, the value since the change in bold, no colours', () => {
    const { container } = render(<PositionPitch data={SWITCH} />);
    const row = container.querySelector('[data-metric="touches"]') as HTMLElement;
    expect(row.querySelector('[data-cell="before"]')!.textContent).toBe('48.0');
    const after = row.querySelector('[data-cell="after"]') as HTMLElement;
    expect(after.textContent).toBe('41.0');
    expect(after.className).toMatch(/font-extrabold/);
    expect(container.querySelector('[data-metric="key_passes"] [data-cell="after"]')!.textContent).toBe('–'); // unknown
    expect(container.innerHTML).not.toMatch(/text-bf-(turquoise|coral|gold)/);
    expect(container.textContent).not.toMatch(/[+−]\d/);
    expect(screen.getByText('4 y 4 partidos con 30+ min')).toBeInTheDocument();
  });

  test('English formats the same way', () => {
    const { container } = render(
      <LocaleProvider initialLocale="en" canSwitch={false}><PositionPitch data={SWITCH} /></LocaleProvider>);
    expect(container.querySelector('[data-metric="key_passes"] [data-cell="before"]')!.textContent).toBe('1.8');
  });
});

describe('an FPL listing (no change date, nobody moved)', () => {
  test('a dashed FPL tag on its line, a quiet link with no arrowhead, single values', () => {
    const { container } = render(<PositionPitch data={LISTING} />);
    const tag = container.querySelector('[data-role="listing"]') as HTMLElement;
    expect(tag.textContent).toBe('FPL: DEF');
    expect(pct(tag, 'left')).toBeLessThan(30); // same side as the played left midfield
    expect(container.querySelector('[data-connector="link"]')).not.toBeNull();
    expect(container.querySelector('[data-connector="arrow"]')).toBeNull();
    expect(container.querySelector('[data-role="old"]')).toBeNull();
    expect(container.querySelector('[data-cell="value"]')!.textContent).toBe('44.3');
    expect(container.querySelector('[data-cell="before"]')).toBeNull();
  });
});

describe('inside GenericCard', () => {
  const base: GenericCardMeta = {
    accent: 'turquoise', title: 'Mbeumo · Casilla inicial', subtitle: null,
    hero: { value: '4/4', label: 'de delantero desde J5', tone: null },
    pills: [{ label: 'Antes: Banda derecha 4/4', tone: 'neutral' }], columns: [], rows: [], footer: 'Fuente: x',
  } as unknown as GenericCardMeta;

  test('renders the pitch only when the payload is present', () => {
    const { rerender } = render(<GenericCard data={{ ...base, position_pitch: SWITCH }} />);
    expect(screen.getByTestId('position-pitch')).toHaveAttribute('data-kind', 'switch');
    rerender(<GenericCard data={{ ...base, position_pitch: null }} />);
    expect(screen.queryByTestId('position-pitch')).toBeNull();
  });
});

describe('labels never cross the halfway line, the centre circle or the connector (one general rule)', () => {
  const ROLES: Array<[string, string | null]> = [
    ['Attacker', null], ['Centre Forward', null], ['Attacking Midfield', null], ['Left Midfield', 'left'], ['Right Midfield', 'right'],
    ['Central Midfield', null], ['Defensive Midfield', null], ['Left Back', 'left'], ['Right Back', 'right'],
    ['Centre Back', 'left'], ['Centre Back', 'right'], ['Goalkeeper', null],
  ];
  // the same field-percent -> box-percent / SVG-unit mapping the component uses (240x360 box, 8-unit margin)
  const toBox = (p: { x: number; y: number }) => ({ x: (100 * (8 + (p.x / 100) * 224)) / 240, y: (100 * (8 + (p.y / 100) * 344)) / 360 });
  const toUnits = (p: { x: number; y: number }): [number, number] => [8 + (p.x / 100) * 224, 8 + (p.y / 100) * 344];

  // The product's role names (ES from position_changes_text._DETAILED_POSITION_ES, EN as the provider names them), with the
  // longest gameweek prefixes. jsdom does not lay text out, so the label width is the component's own ESTIMATE
  // (5.8 px per character, a bit wider than the real font); this checks the geometry rule, not rendered pixels.
  const ES: Record<string, string> = {
    Goalkeeper: 'Portero', 'Centre Back': 'Central', 'Right Back': 'Lateral derecho', 'Left Back': 'Lateral izquierdo',
    'Defensive Midfield': 'Pivote', 'Central Midfield': 'Mediocentro', 'Attacking Midfield': 'Mediapunta',
    'Right Midfield': 'Banda derecha', 'Left Midfield': 'Banda izquierda', Attacker: 'Delantero', 'Centre Forward': 'Delantero centro',
  };
  const EN_GW = (a: string) => `GW10–15 · ${a}`;
  const ES_GW = (a: string) => `J10–J15 · ${ES[a]}`;

  test('every old -> new role pair, in both locales: labels stay attached, inside the field lines, off the connector', () => {
    const bad: string[] = [];
    for (const [fp, fs] of ROLES) {
      for (const [tp, ts] of ROLES) {
        if (fp === tp && fs === ts) continue;
        const [a, b] = [placeRole({ detailed_position: fp, side: fs, line: null }), placeRole({ detailed_position: tp, side: ts, line: null })];
        const [f, t] = [toBox(a), toBox(b)];
        const seg: [number, number, number, number] = [...toUnits(a), ...toUnits(b)];
        for (const [lf, lt] of [[ES_GW(fp), ES_GW(tp)], [EN_GW(fp), EN_GW(tp)]]) {
          for (const [at, text, prefer] of [[f, lf, f.y >= t.y], [t, lt, t.y > f.y]] as const) {
            const r = labelRect(at, text, placeLabel(at, text, prefer, seg));
            if (outsideField(r) || hitsConnector(r, seg) || dotDistance(at, r) > MAX_DOT_DISTANCE) bad.push(`${text} (${fp}->${tp})`);
          }
        }
      }
    }
    expect(bad).toEqual([]);
  });

  test('the right-midfield label stays on the dot side of the pitch (never the far side), in two lines when one will not fit', () => {
    const from = toBox(placeRole({ detailed_position: 'Right Midfield', side: 'right', line: 'MID' }));
    const to = toBox(placeRole({ detailed_position: 'Attacker', side: null, line: 'FWD' }));
    const seg: [number, number, number, number] = [...toUnits(placeRole({ detailed_position: 'Right Midfield', side: 'right', line: 'MID' })),
      ...toUnits(placeRole({ detailed_position: 'Attacker', side: null, line: 'FWD' }))];
    for (const text of ['J1–J5 · Banda derecha', 'GW1–5 · Right Midfield', 'GW10–15 · Right Midfield']) {
      const r = labelRect(from, text, placeLabel(from, text, from.y >= to.y, seg));
      expect((r.x0 + r.x1) / 2).toBeGreaterThan(120); // right half of the 240-unit box
      expect(dotDistance(from, r)).toBeLessThanOrEqual(MAX_DOT_DISTANCE);
      expect(outsideField(r)).toBe(false);
      expect(hitsConnector(r, seg)).toBe(false);
    }
  });

  test('the DOM carries the chosen anchor and the pitch keeps its box', () => {
    const { container } = render(<PositionPitch data={SWITCH} />);
    expect(container.querySelectorAll('[data-label-anchor]')).toHaveLength(2);
    expect(container.querySelector('[data-label-lines]')).not.toBeNull();
    expect(screen.getByTestId('position-pitch-box').className).toMatch(/aspect-\[2\/3\]/);
  });
});

describe('the associations line', () => {
  test('is one observed line under the table, absent when the payload has none', () => {
    const { rerender } = render(<PositionPitch data={{ ...SWITCH, associations: 'En J6–J8 coincidió con ausencias de Aa, Bb y Cc' }} />);
    expect(screen.getByTestId('position-pitch-associations')).toHaveTextContent('En J6–J8 coincidió con ausencias de Aa, Bb y Cc');
    expect(screen.getByTestId('position-pitch-table').nextElementSibling).toBe(screen.getByTestId('position-pitch-associations'));
    rerender(<PositionPitch data={{ ...SWITCH, associations: null }} />);
    expect(screen.queryByTestId('position-pitch-associations')).toBeNull();
  });
});
