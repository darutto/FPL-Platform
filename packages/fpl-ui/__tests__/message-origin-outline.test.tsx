/**
 * @jest-environment jsdom
 *
 * MessageList — answer origin is an outline colour, not an «IA activa» pill.
 *
 * Model-written answers get a turquoise outline, deterministic ones BF gold.
 * No "IA"/"AI" label is shown on plain FPL turns; web-search turns keep their
 * «Búsqueda web» pill (no "IA" in it either).
 */
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import MessageList, { type Message } from '../components/chat/MessageList';
import type { AskResponse } from '../lib/types';
import { orchestratorRankCardResponse } from './fixtures/sample-responses';

function cardMessage(llmUsed: boolean): Message {
  return { id: 'a1', role: 'assistant', text: 'Texto del asistente.', outcome: 'ok', llmUsed, response: orchestratorRankCardResponse };
}

function textMessage(llmUsed: boolean, response: Partial<AskResponse> = {}): Message {
  return {
    id: 'a2',
    role: 'assistant',
    text: 'Respuesta en texto.',
    outcome: 'ok',
    llmUsed,
    response: { ...orchestratorRankCardResponse, generic_card: null, intent: 'unknown', ...response } as AskResponse,
  };
}

beforeAll(() => {
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: jest.fn() });
});

describe('MessageList — origin outline', () => {
  test.each([
    [true, 'border-bf-turquoise/25'],
    [false, 'border-bf-gold/25'],
  ])('card surface, llmUsed=%s → %s, no origin pill', (llmUsed, outline) => {
    const { container } = render(<MessageList messages={[cardMessage(llmUsed)]} loading={false} />);
    expect(screen.getByRole('region', { name: 'Respuesta estructurada' })).toHaveClass(outline);
    expect(container.textContent).not.toMatch(/\bIA\b|\bAI\b|Determinístico/);
  });

  test('text bubble carries the outline too', () => {
    render(<MessageList messages={[textMessage(true)]} loading={false} />);
    const bubble = screen.getByText('Respuesta en texto.').closest('.rounded-\\[14px\\]');
    expect(bubble).toHaveClass('border-bf-turquoise/25');
  });

  test('web-search turn keeps its pill without "IA" and a neutral outline', () => {
    const response = { web_search: { topic: 'Tema', summary: 'Resumen.', results: [], timestamp: '2026-07-19T00:00:00Z' } } as unknown as Partial<AskResponse>;
    const { container } = render(<MessageList messages={[textMessage(true, response)]} loading={false} />);
    expect(screen.getAllByText('Búsqueda web').length).toBeGreaterThan(0);
    expect(container.textContent).not.toMatch(/\bIA\b/);
    expect(container.querySelector('.border-bf-turquoise\\/25')).toBeNull();
  });
});
