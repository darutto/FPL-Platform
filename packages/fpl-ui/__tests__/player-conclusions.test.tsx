/**
 * @jest-environment jsdom
 *
 * The player card's verdict: 0-3 structured conclusions above the card, on the
 * deterministic path (empty final_text) and the LLM path (model prose below the
 * list, untouched). No conclusions → no verdict block. Synthetic data only.
 */
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import MessageList, { type Message } from '../components/chat/MessageList';
import PlayerConclusions from '../components/intents/PlayerConclusions';
import { LocaleProvider } from '../lib/i18n/LocaleProvider';
import type { AskResponse, PlayerConclusion } from '../lib/types';
import { playerSnapshotOkResponse } from './fixtures/sample-responses';

const CONCLUSIONS: PlayerConclusion[] = [
  { key: 'points_attack', params: { position: 'MID' }, evidence: { metric: 'xgi_per_90', top_pct: 10, position: 'MID' } },
  { key: 'set_pieces', params: { pieces: ['penalties', 'free_kicks', 'corners'] }, evidence: null },
  { key: 'zonal', params: { opponents: ['AAA', 'BBB'] }, evidence: null },
];

function turn(overrides: Partial<AskResponse>, conclusions: PlayerConclusion[] | undefined): Message {
  const response: AskResponse = {
    ...playerSnapshotOkResponse,
    ...overrides,
    player_snapshot: { ...playerSnapshotOkResponse.player_snapshot!, conclusions },
  };
  return {
    id: 'a-1',
    role: 'assistant',
    text: response.final_text,
    outcome: response.outcome,
    llmUsed: response.llm_used,
    degraded: response.degraded,
    response,
  };
}

beforeAll(() => {
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: jest.fn() });
});

describe('player conclusions in the chat surface', () => {
  test('deterministic path: list renders with an empty final_text', () => {
    render(
      <MessageList
        messages={[turn({ final_text: '', llm_used: false, synthesis_turn: undefined }, CONCLUSIONS)]}
        loading={false}
      />,
    );
    const verdict = screen.getByRole('region', { name: 'Veredicto' });
    const list = within(verdict).getByRole('list', { name: 'Conclusiones' });
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent('De los MID que más ocasiones generan');
    expect(items[0]).toHaveTextContent('xGI/90 · top 10 % de MID');
    expect(items[1]).toHaveTextContent('Lanza penaltis, faltas y córners');
    expect(items[2]).toHaveTextContent('Cruce zonal favorable: AAA, BBB');
  });

  test('LLM path: list first, then the model prose untouched', () => {
    const prose = 'Texto sintético del modelo sobre el jugador.';
    render(
      <MessageList messages={[turn({ final_text: prose, llm_used: true, synthesis_turn: true }, CONCLUSIONS)]} loading={false} />,
    );
    const verdict = screen.getByRole('region', { name: 'Veredicto' });
    const list = within(verdict).getByRole('list', { name: 'Conclusiones' });
    const text = within(verdict).getByText(prose);
    expect(list.compareDocumentPosition(text) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  test('no conclusions and no prose: no verdict block, the card still renders', () => {
    render(<MessageList messages={[turn({ final_text: '', llm_used: false }, [])]} loading={false} />);
    expect(screen.queryByRole('region', { name: 'Veredicto' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('player-conclusions')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Datos de la recomendación' })).toBeInTheDocument();
  });

  test('older payload without the field: prose-only verdict as before', () => {
    render(<MessageList messages={[turn({ synthesis_turn: true }, undefined)]} loading={false} />);
    const verdict = screen.getByRole('region', { name: 'Veredicto' });
    expect(within(verdict).queryByTestId('player-conclusions')).not.toBeInTheDocument();
    expect(within(verdict).getByText(playerSnapshotOkResponse.final_text)).toBeInTheDocument();
  });
});

describe('PlayerConclusions wording', () => {
  test('set pieces name only the pieces that apply', () => {
    render(<PlayerConclusions conclusions={[{ key: 'set_pieces', params: { pieces: ['penalties', 'corners'] }, evidence: null }]} />);
    expect(screen.getByRole('listitem')).toHaveTextContent(/^Lanza penaltis y córners$/);
  });

  test('defence, clean sheets and starts lines; clean-sheets evidence has no metric prefix', () => {
    render(
      <PlayerConclusions
        conclusions={[
          { key: 'points_defence', params: { position: 'MID' }, evidence: { metric: 'dc_per_90', top_pct: 5, position: 'MID' } },
          { key: 'points_clean_sheets', params: { position: 'DEF' }, evidence: { metric: 'cs_per_90', top_pct: 10, position: 'DEF' } },
          { key: 'starts', params: { starts: 9, games: 10 }, evidence: null },
        ]}
      />,
    );
    const items = screen.getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('De los MID que más defienden');
    expect(items[0]).toHaveTextContent('contribución defensiva/90 · top 5 % de MID');
    expect(items[1]).toHaveTextContent(/^Muchas porterías a cerotop 10 % de DEF$/);
    expect(items[2]).toHaveTextContent('Titular en 9 de 10');
  });

  test('empty or unknown → renders nothing', () => {
    const { container } = render(
      <PlayerConclusions conclusions={[{ key: 'nope', params: {}, evidence: null } as unknown as PlayerConclusion]} />,
    );
    expect(container).toBeEmptyDOMElement();
    const { container: c2 } = render(<PlayerConclusions conclusions={[]} />);
    expect(c2).toBeEmptyDOMElement();
  });

  test('English wording', () => {
    render(
      <LocaleProvider initialLocale="en" canSwitch>
        <PlayerConclusions
          conclusions={[
            { key: 'points_attack', params: { position: 'DEF' }, evidence: { metric: 'xgi_per_90', top_pct: 10, position: 'DEF' } },
            { key: 'set_pieces', params: { pieces: ['penalties', 'free_kicks', 'corners'] }, evidence: null },
          ]}
        />
      </LocaleProvider>,
    );
    const items = screen.getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('Very attacking for a defender');
    expect(items[0]).toHaveTextContent('xGI/90 · top 10% of DEF');
    expect(items[1]).toHaveTextContent('Takes penalties, free kicks and corners');
  });
});
