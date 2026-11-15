/**
 * @jest-environment jsdom
 *
 * The team zonal question «Quién del X explota al Y ›» where the matchup is on screen: at the end of the player
 * card's «Zonas» section, and under the fixture-cell answer's «Calendario» card. Synthetic clubs and values.
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import FixtureOutlookCard from '../components/intents/FixtureOutlookCard';
import PlayerCard from '../components/intents/PlayerCard';
import { ChatAskProvider } from '../lib/chat-ask';
import { LocaleProvider } from '@/lib/i18n/LocaleProvider';
import { playerSnapshotOkResponse } from './fixtures/sample-responses';
import type { FixtureOutlookMeta, PlayerSignal, PlayerSnapshotMeta, PlayerZonalOutlookMeta, ZonalLink } from '../lib/types';

const LINK: PlayerSignal = {
  kind: 'zone',
  label: 'Quién del NOR explota al EAS',
  send_text: '¿Qué jugadores del Northbury pueden explotar las zonas débiles del Eastport?',
};

function zonal(status: 'favorable' | 'neutral' | 'no_data'): PlayerZonalOutlookMeta {
  return {
    zones: [{ zone: 'in-box / central', share: 0.5 }],
    gw_from: 11,
    gw_to: 13,
    fixtures: [
      { gameweek: 11, fixture_id: 1, opponent: 'Eastport', opponent_short: 'EAS', is_home: false, status, matches: [] },
    ],
    verdict_kind: status,
    verdict: 'Lectura sintética.',
    data_provenance: null,
  } as PlayerZonalOutlookMeta;
}

function wrap(node: React.ReactNode, ask: ((q: string) => void) | null) {
  const inner = ask ? <ChatAskProvider ask={ask}>{node}</ChatAskProvider> : node;
  return <LocaleProvider initialLocale="es" canSwitch={false}>{inner}</LocaleProvider>;
}

function renderCard(z: PlayerZonalOutlookMeta | null, signals: PlayerSignal[], ask: ((q: string) => void) | null = jest.fn()) {
  const data: PlayerSnapshotMeta = { ...playerSnapshotOkResponse.player_snapshot!, zonal: z, signals };
  return render(wrap(<PlayerCard data={data} />, ask));
}

describe('«Zonas» section link', () => {
  test('closes the section when a row is a favourable matchup; a tap sends the team question', () => {
    const ask = jest.fn();
    renderCard(zonal('favorable'), [LINK], ask);
    const zonas = screen.getByTestId('player-zonas');
    const link = within(zonas).getByTestId('player-zonas-link');
    expect(link.textContent).toBe('Quién del NOR explota al EAS›');
    fireEvent.click(within(link).getByRole('button'));
    expect(ask).toHaveBeenCalledWith(LINK.send_text);
    // It is not an «Explorar» pill.
    expect(screen.queryByTestId('player-explore')).toBeNull();
  });

  test.each(['neutral', 'no_data'] as const)('no favourable row (%s): no link', (status) => {
    renderCard(zonal(status), [LINK]);
    expect(screen.queryByTestId('player-zonas-link')).toBeNull();
  });

  test('no zone signal, or no chat (shared answer): no link', () => {
    const { unmount } = renderCard(zonal('favorable'), []);
    expect(screen.queryByTestId('player-zonas-link')).toBeNull();
    unmount();
    renderCard(zonal('favorable'), [LINK], null);
    expect(screen.getByTestId('player-zonas')).toBeInTheDocument();
    expect(screen.queryByTestId('player-zonas-link')).toBeNull();
  });
});

describe('fixture-cell answer link', () => {
  const cell: FixtureOutlookMeta = {
    axis: 'defence',
    horizon: 1,
    current_gameweek: 10,
    teams: [{
      team_short: 'NOR', team_name: 'Northbury', axis: 'defence', avg_band: 2, verdict: 'J11: sintético.',
      series: [{ gameweek: 11, band: 2, klass: 'good', is_dgw: false, is_bgw: false,
        fixtures: [{ opponent_short: 'EAS', is_home: false, band: 2 }] }],
      runs: [],
    }],
  };
  const links: ZonalLink[] = [
    { label: 'Quién del NOR explota al EAS', send_text: 'q1' },
    { label: 'Quién del NOR explota al WES', send_text: 'q2' },
    { label: 'third', send_text: 'q3' },
  ];

  test('pills under the card (outside it), at most two; a tap sends the question', () => {
    const ask = jest.fn();
    const { container } = render(wrap(<FixtureOutlookCard data={{ ...cell, zonal_links: links }} />, ask));
    const row = screen.getByTestId('fixture-zonal-links');
    expect(within(row).getAllByRole('button').map((b) => b.textContent)).toEqual([
      'Quién del NOR explota al EAS›', 'Quién del NOR explota al WES›']);
    // A sibling of the card, never inside it.
    expect(container.firstElementChild?.contains(row)).toBe(false);
    fireEvent.click(within(row).getAllByRole('button')[0]);
    expect(ask).toHaveBeenCalledWith('q1');
  });

  test('no links, or no chat (shared answer): nothing under the card', () => {
    const { unmount } = render(wrap(<FixtureOutlookCard data={cell} />, jest.fn()));
    expect(screen.queryByTestId('fixture-zonal-links')).toBeNull();
    unmount();
    render(wrap(<FixtureOutlookCard data={{ ...cell, zonal_links: links }} />, null));
    expect(screen.queryByTestId('fixture-zonal-links')).toBeNull();
  });
});
