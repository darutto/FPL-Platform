/**
 * @jest-environment jsdom
 *
 * The steady position pitch, rendered from the backend's own serialized /ask cards
 * (fixtures written and checked by fpl-grounded-assistant/tests/test_position_pitch_steady.py; synthetic data).
 */
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import IntentRenderer from '../components/chat/IntentRenderer';
import { dotRect, labelRect, outsideField, placeLabel, placeRole, spreadSpots } from '../components/intents/PositionPitch';
import { LocaleProvider } from '../lib/i18n/LocaleProvider';
import type { AskResponse } from '../lib/types';
import oneRole from './fixtures/position-pitch/one-role-es.json';
import majority from './fixtures/position-pitch/majority-es.json';
import splitEs from './fixtures/position-pitch/split-es.json';
import splitEn from './fixtures/position-pitch/split-en.json';

const show = (b: unknown, locale: 'es' | 'en' = 'es') =>
  render(
    <LocaleProvider initialLocale={locale} canSwitch={false}>
      <IntentRenderer response={b as AskResponse} />
    </LocaleProvider>,
  );
const dots = (pitch: HTMLElement, role: string) => pitch.querySelectorAll(`[data-role="${role}"]`);

describe('steady position pitch', () => {
  test('one role: one highlighted spot with its count, no arrow, no link, no table', () => {
    const { container } = show(oneRole);
    const pitch = screen.getByTestId('position-pitch');
    expect(pitch).toHaveAttribute('data-kind', 'steady');
    expect(dots(pitch, 'new')).toHaveLength(1);
    expect(dots(pitch, 'other')).toHaveLength(0);
    expect(dots(pitch, 'old')).toHaveLength(0);
    expect(pitch.querySelector('[data-connector]')).toBeNull();
    expect(pitch).toHaveTextContent('Mediapunta 6 de 6 titularidades');
    expect(screen.queryByTestId('position-pitch-table')).not.toBeInTheDocument();
    expect(container.querySelector('table')).toBeNull();
    expect(screen.getByText('como mediapunta')).toBeInTheDocument();
  });

  test('a majority role keeps one spot and the table says the other start', () => {
    const { container } = show(majority);
    const pitch = screen.getByTestId('position-pitch');
    expect(dots(pitch, 'new')).toHaveLength(1);
    expect(dots(pitch, 'other')).toHaveLength(0);
    expect(container.querySelector('table')).not.toBeNull();
    expect(screen.getByText('Pivote')).toBeInTheDocument();
  });

  test.each([
    ['es', splitEs, ['Mediapunta 3 de 6 titularidades', 'Pivote 2', 'Banda derecha 1']],
    ['en', splitEn, ['Attacking Midfield 3 of 6 starts', 'Defensive Midfield (left) 2', 'Right Midfield 1']],
  ] as const)('split starts (%s): main plus lighter spots with counts, no arrow', (locale, body, texts) => {
    show(body, locale);
    const pitch = screen.getByTestId('position-pitch');
    expect(dots(pitch, 'new')).toHaveLength(1);
    expect(dots(pitch, 'other')).toHaveLength(2);
    expect(pitch.querySelector('[data-connector]')).toBeNull();
    const box = within(pitch).getByTestId('position-pitch-box');
    for (const text of texts) {
      expect(Array.from(box.querySelectorAll('[data-label-anchor]')).map((l) => l.textContent)).toContain(text);
    }
  });

  test('labels stay on the field and off each other and the dots', () => {
    const card = (splitEs as unknown as AskResponse).generic_card!.position_pitch!;
    const field = spreadSpots([card.to, ...card.others!].map((r) => placeRole(r)));
    const texts = [card.labels.to, ...card.others!.map((o) => o.label)];
    const at = field.map((p) => ({ x: (100 * (8 + (p.x / 100) * 224)) / 240, y: (100 * (8 + (p.y / 100) * 344)) / 360 }));
    const taken = at.map(dotRect);
    at.forEach((p, i) => {
      const rect = labelRect(p, texts[i], placeLabel(p, texts[i], p.y < 50, null, taken));
      expect(outsideField(rect)).toBe(false);
      for (const other of taken) {
        expect(rect.x0 < other.x1 && other.x0 < rect.x1 && rect.y0 < other.y1 && other.y0 < rect.y1).toBe(false);
      }
      taken.push(rect);
    });
  });

  test('two roles that share a spot are drawn apart', () => {
    const same = placeRole({ detailed_position: 'Attacker', side: null, line: 'FWD' });
    const [a, b] = spreadSpots([same, placeRole({ detailed_position: 'Centre Forward', side: null, line: 'FWD' })]);
    expect(a).toEqual(same);
    expect(Math.abs(a.x - b.x)).toBeGreaterThanOrEqual(12);
  });
});
