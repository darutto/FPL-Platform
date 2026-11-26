/**
 * @jest-environment jsdom
 *
 * The card of a focused player zonal question, rendered from the backend's own serialized /ask bodies
 * (fixtures written and checked by fpl-grounded-assistant/tests/test_player_zonal_card.py; synthetic data).
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import IntentRenderer from '../components/chat/IntentRenderer';
import { ChatAskProvider } from '../lib/chat-ask';
import { selectIntentView } from '../lib/intent-renderer';
import type { AskResponse } from '../lib/types';
import favourable from './fixtures/player-zonal/favourable.json';
import neutral from './fixtures/player-zonal/no-favourable.json';
import profileOnly from './fixtures/player-zonal/profile-only.json';

const body = (b: unknown) => b as AskResponse;

describe('PlayerZonalCard from the serialized backend body', () => {
  test('favourable: header, pitch, chips, one row per match, verdict, stamp', () => {
    const res = body(favourable);
    expect(selectIntentView(res)).toBe('player_zonal');
    render(<IntentRenderer response={res} />);
    const card = screen.getByTestId('player-zonal-card');
    expect(within(card).getByText('Palmer')).toBeInTheDocument();
    expect(within(card).getByText('CHE · MID')).toBeInTheDocument();
    expect(within(card).getByTestId('player-zonas-pitch-wrap')).toBeInTheDocument();
    expect(within(card).getByTestId('player-zonas-chips').children).toHaveLength(
      res.player_zonal!.zonal.zones.length,
    );
    const rows = within(card).getAllByTestId('player-zonas-row');
    expect(rows.map((r) => r.getAttribute('data-status'))).toEqual(['neutral', 'neutral', 'favorable']);
    expect(within(card).getByTestId('player-zonas-verdict')).toHaveTextContent(res.player_zonal!.zonal.verdict);
    expect(within(card).getByTestId('zonal-provenance')).toBeInTheDocument();
    expect(within(card).getByText(/próximas 3 jornadas · J6–J8/)).toBeInTheDocument();
  });

  test('the zone link sends the backend question, only with a chat to send it to', () => {
    const res = body(favourable);
    const ask = jest.fn();
    const { unmount } = render(
      <ChatAskProvider ask={ask}>
        <IntentRenderer response={res} />
      </ChatAskProvider>,
    );
    fireEvent.click(within(screen.getByTestId('player-zonas-link')).getByRole('button'));
    expect(ask).toHaveBeenCalledWith(res.player_zonal!.signals![0].send_text);
    unmount();
    render(<IntentRenderer response={res} />);
    expect(screen.queryByTestId('player-zonas-link')).not.toBeInTheDocument();
  });

  test('no favourable match: the card stays, with neutral and no-data rows and no link', () => {
    render(
      <ChatAskProvider ask={jest.fn()}>
        <IntentRenderer response={body(neutral)} />
      </ChatAskProvider>,
    );
    expect(screen.getByTestId('player-zonas')).toHaveAttribute('data-verdict-kind', 'neutral');
    expect(screen.getAllByTestId('player-zonas-row').map((r) => r.getAttribute('data-status'))).toContain('no_data');
    expect(screen.queryByTestId('player-zonas-link')).not.toBeInTheDocument();
  });

  test('old data: profile and stamp only', () => {
    render(<IntentRenderer response={body(profileOnly)} />);
    expect(screen.getByTestId('player-zonas-chips')).toBeInTheDocument();
    expect(screen.getByTestId('zonal-provenance')).toHaveTextContent('Datos hasta la GW5');
    expect(screen.queryByTestId('player-zonas-rows')).not.toBeInTheDocument();
    expect(screen.queryByTestId('player-zonas-verdict')).not.toBeInTheDocument();
  });

  test('one gameweek asked: the window label is singular', () => {
    const res = body(JSON.parse(JSON.stringify(favourable)));
    res.player_zonal!.zonal.gw_to = res.player_zonal!.zonal.gw_from;
    render(<IntentRenderer response={res} />);
    expect(screen.getByText(/de la próxima jornada · J6$/)).toBeInTheDocument();
  });

  test('no card in the body, or one without zones, is a text turn', () => {
    expect(selectIntentView({ ...body(favourable), player_zonal: null })).toBeNull();
    const empty = body(JSON.parse(JSON.stringify(favourable)));
    empty.player_zonal!.zonal.zones = [];
    expect(selectIntentView(empty)).toBeNull();
  });
});
