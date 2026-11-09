/**
 * @jest-environment jsdom
 *
 * Player-card signals: pills at the foot of PlayerCard. Synthetic labels.
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import PlayerCard from '../components/intents/PlayerCard';
import { ChatAskProvider } from '../lib/chat-ask';
import { LocaleProvider } from '@/lib/i18n/LocaleProvider';
import type { Locale } from '@/lib/i18n/locale';
import { playerSnapshotOkResponse } from './fixtures/sample-responses';
import type { PlayerSignal, PlayerSnapshotMeta } from '../lib/types';

const base = playerSnapshotOkResponse.player_snapshot!;

const POSITION: PlayerSignal = { kind: 'position', label: 'Extremo 2 de 4', send_text: '¿En qué posición juega Quillby?' };
const ZONE: PlayerSignal = {
  kind: 'zone',
  label: 'Banda débil EAS',
  send_text: '¿Qué jugadores del Northbury pueden explotar las zonas débiles del Eastport?',
};

function renderCard(signals: PlayerSignal[] | undefined, ask: ((q: string) => void) | null = jest.fn(), locale: Locale = 'es') {
  const data: PlayerSnapshotMeta = { ...base, signals };
  const card = <PlayerCard data={data} />;
  return render(
    <LocaleProvider initialLocale={locale} canSwitch={false}>
      {ask ? <ChatAskProvider ask={ask}>{card}</ChatAskProvider> : card}
    </LocaleProvider>,
  );
}

describe('PlayerSignals', () => {
  test('two signals render in order, position then zone, with icons', () => {
    renderCard([POSITION, ZONE]);
    const row = screen.getByRole('group', { name: 'Señales' });
    const pills = within(row).getAllByRole('button');
    expect(pills.map((b) => b.textContent)).toEqual(['Extremo 2 de 4', 'Banda débil EAS']);
    expect(pills.map((b) => b.getAttribute('data-signal'))).toEqual(['position', 'zone']);
    pills.forEach((b) => expect(b.querySelector('svg')).not.toBeNull());
  });

  test('one signal renders one pill', () => {
    renderCard([ZONE]);
    expect(within(screen.getByRole('group', { name: 'Señales' })).getAllByRole('button')).toHaveLength(1);
  });

  test.each([[undefined], [[]]])('no signals: no row, no separator (%p)', (signals) => {
    const { container } = renderCard(signals);
    expect(screen.queryByRole('group', { name: 'Señales' })).not.toBeInTheDocument();
    expect(container.querySelector('[data-signal]')).toBeNull();
  });

  test('a tap sends the pill question verbatim', () => {
    const ask = jest.fn();
    renderCard([POSITION, ZONE], ask);
    fireEvent.click(screen.getByRole('button', { name: 'Banda débil EAS' }));
    expect(ask).toHaveBeenCalledWith(ZONE.send_text);
    fireEvent.click(screen.getByRole('button', { name: 'Extremo 2 de 4' }));
    expect(ask).toHaveBeenLastCalledWith(POSITION.send_text);
  });

  test('outside the chat (no ask provider) nothing tappable renders', () => {
    renderCard([POSITION, ZONE], null);
    expect(screen.queryByRole('group', { name: 'Señales' })).not.toBeInTheDocument();
  });

  test('at most three pills, unknown kinds dropped', () => {
    const extra = { kind: 'fixtures', label: 'x', send_text: 'y' } as unknown as PlayerSignal;
    renderCard([POSITION, extra, ZONE, POSITION, ZONE]);
    const labels = within(screen.getByRole('group', { name: 'Señales' })).getAllByRole('button').map((b) => b.textContent);
    expect(labels).toEqual(['Extremo 2 de 4', 'Banda débil EAS', 'Extremo 2 de 4']);
  });

  test('English: group label in English, backend label shown as sent', () => {
    renderCard([{ kind: 'position', label: 'Winger 2 of 4', send_text: 'What position does Quillby really play?' }], jest.fn(), 'en');
    expect(screen.getByRole('group', { name: 'Signals' })).toHaveTextContent('Winger 2 of 4');
  });
});
