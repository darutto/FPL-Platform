/**
 * @jest-environment jsdom
 *
 * The player card's «Explorar» pills and the verdict's position line. Synthetic labels and counts.
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import PlayerCard from '../components/intents/PlayerCard';
import PlayerConclusions from '../components/intents/PlayerConclusions';
import { ChatAskProvider } from '../lib/chat-ask';
import { LocaleProvider } from '@/lib/i18n/LocaleProvider';
import type { Locale } from '@/lib/i18n/locale';
import { playerSnapshotOkResponse } from './fixtures/sample-responses';
import type { PlayerConclusion, PlayerSignal, PlayerSnapshotMeta } from '../lib/types';

const base = playerSnapshotOkResponse.player_snapshot!;

const POSITION: PlayerSignal = { kind: 'position', label: 'Posición', send_text: '¿En qué posición juega Quillby?' };
const ZONE: PlayerSignal = {
  kind: 'zone',
  label: 'Zonas',
  send_text: '¿Qué jugadores del Northbury pueden explotar las zonas débiles del Eastport?',
};

function wrap(node: React.ReactNode, locale: Locale = 'es') {
  return <LocaleProvider initialLocale={locale} canSwitch={false}>{node}</LocaleProvider>;
}

function renderCard(signals: PlayerSignal[] | undefined, ask: ((q: string) => void) | null = jest.fn(), locale: Locale = 'es') {
  const data: PlayerSnapshotMeta = { ...base, signals };
  const card = <PlayerCard data={data} />;
  return render(wrap(ask ? <ChatAskProvider ask={ask}>{card}</ChatAskProvider> : card, locale));
}

describe('Explorar pills', () => {
  test('two pills under the EXPLORAR heading, in order, named by destination, with icon and chevron', () => {
    renderCard([POSITION, ZONE]);
    const section = screen.getByRole('region', { name: 'Explorar' });
    expect(within(section).getByText('Explorar')).toBeInTheDocument();
    const pills = within(section).getAllByRole('button');
    expect(pills.map((b) => b.textContent)).toEqual(['Posición›', 'Zonas›']);
    expect(pills.map((b) => b.getAttribute('data-signal'))).toEqual(['position', 'zone']);
    pills.forEach((b) => expect(b.querySelector('svg')).not.toBeNull());
  });

  test('one pill', () => {
    renderCard([ZONE]);
    expect(within(screen.getByRole('region', { name: 'Explorar' })).getAllByRole('button')).toHaveLength(1);
  });

  test.each([[undefined], [[]]])('no pills: no heading, no row, no separator (%p)', (signals) => {
    const { container } = renderCard(signals);
    expect(screen.queryByText('Explorar')).not.toBeInTheDocument();
    expect(container.querySelector('[data-testid="player-explore"]')).toBeNull();
  });

  test('a tap sends the pill question verbatim', () => {
    const ask = jest.fn();
    renderCard([POSITION, ZONE], ask);
    fireEvent.click(screen.getByRole('button', { name: /Zonas/ }));
    expect(ask).toHaveBeenCalledWith(ZONE.send_text);
    fireEvent.click(screen.getByRole('button', { name: /Posición/ }));
    expect(ask).toHaveBeenLastCalledWith(POSITION.send_text);
  });

  test('outside the chat (no ask provider) nothing renders', () => {
    renderCard([POSITION, ZONE], null);
    expect(screen.queryByText('Explorar')).not.toBeInTheDocument();
  });

  test('unknown kinds are dropped', () => {
    const extra = { kind: 'fixtures', label: 'x', send_text: 'y' } as unknown as PlayerSignal;
    renderCard([POSITION, extra]);
    expect(within(screen.getByRole('region', { name: 'Explorar' })).getAllByRole('button')).toHaveLength(1);
  });

  test('English heading', () => {
    renderCard([{ kind: 'zone', label: 'Zones', send_text: "Which Northbury players can exploit Eastport's weak zones?" }], jest.fn(), 'en');
    expect(screen.getByRole('region', { name: 'Explore' })).toHaveTextContent('Zones');
  });
});

describe('verdict position line', () => {
  const winger: PlayerConclusion = { key: 'position', params: { role: 'winger', starts: 7, games: 10 }, evidence: null };
  const midLine: PlayerConclusion = { key: 'position', params: { line: 'MID', starts: 2, games: 3 }, evidence: null };

  test('role word with the count as evidence (ES/EN)', () => {
    const { unmount } = render(wrap(<PlayerConclusions conclusions={[winger]} />));
    expect(screen.getByText('Juega de extremo')).toBeInTheDocument();
    expect(screen.getByText('7 de 10')).toBeInTheDocument();
    unmount();
    render(wrap(<PlayerConclusions conclusions={[winger]} />, 'en'));
    expect(screen.getByText('Plays as a winger')).toBeInTheDocument();
    expect(screen.getByText('7 of 10')).toBeInTheDocument();
  });

  test('line word when the roles do not agree', () => {
    render(wrap(<PlayerConclusions conclusions={[midLine]} />));
    expect(screen.getByText('Juega de medio')).toBeInTheDocument();
  });

  test('an unknown role is dropped, never shown raw', () => {
    const bad = { key: 'position', params: { role: 'sweeper', starts: 3, games: 4 }, evidence: null } as unknown as PlayerConclusion;
    render(wrap(<PlayerConclusions conclusions={[bad]} />));
    expect(screen.queryByTestId('player-conclusions')).not.toBeInTheDocument();
  });
});
