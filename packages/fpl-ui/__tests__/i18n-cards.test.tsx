/**
 * @jest-environment jsdom
 *
 * The result cards in both languages. Every card is rendered from the same fixture under an
 * English and a Spanish LocaleProvider:
 *   - the Spanish text is snapshotted and must equal what the card said before the dictionary
 *     (the existing Spanish assertions elsewhere are untouched);
 *   - the English text is snapshotted, and for the strings the UI itself owns the English words
 *     are asserted present and their Spanish originals absent.
 * Text that comes from the payload (names, reasons, backend prose) is the backend's to localise.
 */
import React from 'react';
import { render } from '@testing-library/react';
import '@testing-library/jest-dom';

import IntentRenderer from '../components/chat/IntentRenderer';
import { LocaleProvider } from '@/lib/i18n/LocaleProvider';
import type { Locale } from '@/lib/i18n/locale';
import type { AskResponse } from '../lib/types';
import {
  captainOkResponse,
  comparisonOkResponse,
  comparisonTiedResponse,
  rankingOkResponse,
  transferOkResponse,
  transferHoldResponse,
  transferSuggestionOkResponse,
  chipOkResponse,
  chipUnavailableResponse,
  differentialOkResponse,
  playerSnapshotOkResponse,
  injuryListGenericResponse,
} from './fixtures/sample-responses';

// "3 months ago" must not drift with the calendar: the cards ask the clock how long ago a date was.
beforeAll(() => {
  jest.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-10-20T12:00:00Z'));
});
afterAll(() => {
  jest.restoreAllMocks();
});

function text(response: AskResponse, locale: Locale): string {
  const { container, unmount } = render(
    <LocaleProvider initialLocale={locale} canSwitch={false}>
      <IntentRenderer response={response} />
    </LocaleProvider>,
  );
  const out = (container.textContent ?? '').replace(/\s+/g, ' ').trim();
  unmount();
  return out;
}

const CARDS: Array<{ name: string; response: AskResponse; en: string[]; esOnly: string[] }> = [
  { name: 'captain', response: captainOkResponse, en: ['Favourite', 'Captain score', '1st penalty taker'], esOnly: ['Favorito', 'Puntuación de capitán', 'lanzador de penaltis'] },
  { name: 'comparison', response: comparisonOkResponse, en: ['Comparison', 'The best pick is Haaland.', 'Pick', 'leads by'], esOnly: ['Comparación', 'La mejor selección es', 'lidera por'] },
  { name: 'comparison tie', response: comparisonTiedResponse, en: ['Too close to call.'], esOnly: ['Empate técnico.'] },
  { name: 'ranking', response: rankingOkResponse, en: ['Captain candidates'], esOnly: ['Candidatos a capitán'] },
  { name: 'transfer', response: transferOkResponse, en: ['Transfer', '← Out', 'Make the transfer on FPL', 'captain pts'], esOnly: ['Transferencia', '← Saca', 'Hacer la transferencia en FPL', 'pts capitán'] },
  { name: 'transfer hold', response: transferHoldResponse, en: ['Holding is the right read.', 'Keep'], esOnly: ['Mantener es la lectura correcta.', 'Conservar'] },
  { name: 'transfer suggestions', response: transferSuggestionOkResponse, en: ['Transfer targets', 'Other options', 'ownership', 'index'], esOnly: ['Objetivos de transferencia', 'Otras opciones', 'propiedad', 'índice'] },
  { name: 'chip', response: chipOkResponse, en: ['Triple Captain', 'Favourable conditions'], esOnly: ['Condiciones favorables'] },
  { name: 'chip unavailable', response: chipUnavailableResponse, en: ['Chip not available in your squad'], esOnly: ['Chip no disponible en tu equipo'] },
  { name: 'differentials', response: differentialOkResponse, en: ['Differentials', 'owned', 'Player', 'Price', 'not directly comparable'], esOnly: ['Diferenciales', 'de propietarios', 'Jugador', 'Precio', 'no es directamente comparable'] },
  { name: 'player', response: playerSnapshotOkResponse, en: ['price', 'ownership', 'form', 'minutes'], esOnly: ['precio', 'propiedad', 'forma', 'minutos'] },
  { name: 'injury list', response: injuryListGenericResponse, en: [], esOnly: [] },
];

describe.each(CARDS)('$name card', ({ response, en, esOnly }) => {
  test('Spanish is unchanged (snapshot) and carries the Spanish words', () => {
    const es = text(response, 'es');
    expect(es).toMatchSnapshot();
    for (const word of esOnly) expect(es).toContain(word);
  });

  test('English reads in English, with the Spanish UI words gone', () => {
    const english = text(response, 'en');
    expect(english).toMatchSnapshot();
    for (const word of en) expect(english).toContain(word);
    for (const word of esOnly) expect(english).not.toContain(word);
  });
});
