/**
 * @jest-environment jsdom
 *
 * MessageList — orchestrator atomic-tool ranking card.
 *
 * Locks in the visual-style fix: when an open-ended orchestrator turn carries a
 * generic_card (rank_players_by_metric), MessageList renders the styled card and
 * NOT the raw ASCII table that was the whole complaint. Card replaces the bubble.
 */
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import MessageList, { type Message } from '../components/chat/MessageList';
import { orchestratorRankCardResponse } from './fixtures/sample-responses';

function assistantMessage(): Message {
  return {
    id: 'a1',
    role: 'assistant',
    text: orchestratorRankCardResponse.final_text, // the raw ASCII table
    outcome: 'ok',
    llmUsed: true,
    response: orchestratorRankCardResponse,
  };
}

beforeAll(() => {
  // jsdom has no scrollIntoView; MessageList calls it in a mount effect.
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    configurable: true,
    value: jest.fn(),
  });
});

describe('MessageList — atomic-tool ranking card', () => {
  test('renders the card and suppresses the ASCII final_text bubble', () => {
    render(<MessageList messages={[assistantMessage()]} loading={false} />);

    // The styled card is present (its title + a player row).
    expect(screen.getByText('TOP 3 · Puntos')).toBeInTheDocument();
    expect(screen.getByText('Haaland')).toBeInTheDocument();

    // The raw ASCII table text must NOT be rendered (card replaces the bubble).
    expect(screen.queryByText(/Valor métrica/)).not.toBeInTheDocument();
    expect(screen.queryByText(/#\s*\|\s*Jugador/)).not.toBeInTheDocument();
  });
});
