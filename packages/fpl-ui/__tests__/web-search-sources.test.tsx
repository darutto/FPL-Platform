/**
 * @jest-environment jsdom
 *
 * search_web ran beside another tool: the player card stays the main view and the
 * cited sources show under it as titled links. Synthetic data only.
 */
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import MessageList, { type Message } from '../components/chat/MessageList';
import type { AskResponse } from '../lib/types';
import { playerSnapshotOkResponse } from './fixtures/sample-responses';

const WEB = {
  topic: 'Synthetic injury update',
  summary: 'Resumen sintético.',
  timestamp: '2026-11-20T10:00:00+00:00',
  results: [
    { title: 'Synthetic club update', snippet: 's', url: 'https://example.test/a', source: 'example.test', published: null },
    { title: 'Synthetic report', snippet: 's', url: 'https://example.test/b', source: '', published: null },
  ],
};

function turn(webSearch: unknown): Message {
  const response = { ...playerSnapshotOkResponse, web_search: webSearch } as unknown as AskResponse;
  return {
    id: 'a-1',
    role: 'assistant',
    text: 'Texto sintético sin enlaces.',
    outcome: response.outcome,
    llmUsed: true,
    response,
  };
}

beforeAll(() => {
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: jest.fn() });
});

describe('web sources beside a player card', () => {
  test('titled, clickable links under the card; the card is still the main view', () => {
    render(<MessageList messages={[turn(WEB)]} loading={false} />);
    const sources = screen.getByTestId('web-sources');
    const first = within(sources).getByRole('link', { name: 'Synthetic club update' });
    expect(first).toHaveAttribute('href', 'https://example.test/a');
    expect(first).toHaveAttribute('target', '_blank');
    expect(within(sources).getByRole('link', { name: 'Synthetic report' })).toHaveAttribute('href', 'https://example.test/b');
    expect(screen.getByRole('region', { name: 'Datos de la recomendación' })).toBeInTheDocument();
  });

  test('no web_search → no sources block', () => {
    render(<MessageList messages={[turn(null)]} loading={false} />);
    expect(screen.queryByTestId('web-sources')).not.toBeInTheDocument();
  });
});
