/**
 * @jest-environment jsdom
 *
 * The player card's «Explorar» pill and the verdict's position line. Synthetic labels and counts.
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
  label: 'Quién del NOR explota al EAS',
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
  test('only the position pill, under the EXPLORAR heading, named by destination, with icon and chevron', () => {
    renderCard([POSITION, ZONE]);
    const section = screen.getByRole('region', { name: 'Explorar' });
    expect(within(section).getByText('Explorar')).toBeInTheDocument();
    const pills = within(section).getAllByRole('button');
    expect(pills.map((b) => b.textContent)).toEqual(['Posición›']);
    expect(pills[0].getAttribute('data-signal')).toBe('position');
    expect(pills[0].querySelector('svg')).not.toBeNull();
  });

  test('a zone signal alone opens no EXPLORAR section (it belongs to «Zonas»)', () => {
    const { container } = renderCard([ZONE]);
    expect(container.querySelector('[data-testid="player-explore"]')).toBeNull();
  });

  test.each([[undefined], [[]]])('no pills: no heading, no row, no separator (%p)', (signals) => {
    const { container } = renderCard(signals);
    expect(screen.queryByText('Explorar')).not.toBeInTheDocument();
    expect(container.querySelector('[data-testid="player-explore"]')).toBeNull();
  });

  test('a tap sends the pill question verbatim', () => {
    const ask = jest.fn();
    renderCard([POSITION], ask);
    fireEvent.click(screen.getByRole('button', { name: /Posición/ }));
    expect(ask).toHaveBeenCalledWith(POSITION.send_text);
  });

  test('outside the chat (no ask provider) nothing renders', () => {
    renderCard([POSITION], null);
    expect(screen.queryByText('Explorar')).not.toBeInTheDocument();
  });

  test('unknown kinds are dropped', () => {
    const extra = { kind: 'fixtures', label: 'x', send_text: 'y' } as unknown as PlayerSignal;
    renderCard([POSITION, extra]);
    expect(within(screen.getByRole('region', { name: 'Explorar' })).getAllByRole('button')).toHaveLength(1);
  });

  test('English heading', () => {
    renderCard([{ kind: 'position', label: 'Position', send_text: 'What position does Quillby really play?' }], jest.fn(), 'en');
    expect(screen.getByRole('region', { name: 'Explore' })).toHaveTextContent('Position');
  });
});

describe('verdict position line', () => {
  const winger: PlayerConclusion = {
    key: 'position', params: { role: 'winger', starts: 6, games: 6 }, evidence: { gw_from: 5, gw_to: 10 },
  };
  const midLine: PlayerConclusion = { key: 'position', params: { line: 'MID', starts: 3, games: 5 }, evidence: null };

  test('role word and the position card count in the label, its gameweeks as evidence (ES/EN)', () => {
    const { unmount } = render(wrap(<PlayerConclusions conclusions={[winger]} />));
    expect(screen.getByText('Juega de extremo · 6 de 6')).toBeInTheDocument();
    expect(screen.getByText('J5–J10')).toBeInTheDocument();
    unmount();
    render(wrap(<PlayerConclusions conclusions={[winger]} />, 'en'));
    expect(screen.getByText('Plays as a winger · 6 of 6')).toBeInTheDocument();
    expect(screen.getByText('GW5–GW10')).toBeInTheDocument();
  });

  test('line word when the roles do not agree; no evidence when the span is missing', () => {
    render(wrap(<PlayerConclusions conclusions={[midLine]} />));
    const row = screen.getByText('Juega de medio · 3 de 5').closest('li')!;
    expect(row.textContent).toBe('Juega de medio · 3 de 5');
  });

  test('one gameweek reads as a single J', () => {
    render(wrap(<PlayerConclusions conclusions={[{ ...winger, evidence: { gw_from: 9, gw_to: 9 } }]} />));
    expect(screen.getByText('J9')).toBeInTheDocument();
  });

  test('an unknown role is dropped, never shown raw', () => {
    const bad = { key: 'position', params: { role: 'sweeper', starts: 3, games: 4 }, evidence: null } as unknown as PlayerConclusion;
    render(wrap(<PlayerConclusions conclusions={[bad]} />));
    expect(screen.queryByTestId('player-conclusions')).not.toBeInTheDocument();
  });
});
