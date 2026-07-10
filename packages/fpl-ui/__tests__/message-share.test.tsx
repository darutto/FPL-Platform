/**
 * @jest-environment jsdom
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import MessageList from '../components/chat/MessageList';
import { captainOkResponse, unsupportedResponse } from './fixtures/sample-responses';

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    value: jest.fn(),
    writable: true,
  });
});

describe('MessageList share actions', () => {
  test('shows single share button for structured assistant FPL cards', () => {
    render(
      <MessageList
        loading={false}
        messages={[
          { id: 'u1', role: 'user', text: '¿A quién capitanear esta semana?' },
          {
            id: 'a1',
            role: 'assistant',
            text: captainOkResponse.final_text,
            response: captainOkResponse,
            outcome: captainOkResponse.outcome,
            llmUsed: captainOkResponse.llm_used,
            degraded: false,
          },
        ]}
      />,
    );

    expect(screen.getByRole('button', { name: 'Compartir tarjeta' })).toBeInTheDocument();
  });

  test('does not show share buttons for text-only assistant responses', () => {
    render(
      <MessageList
        loading={false}
        messages={[
          { id: 'u1', role: 'user', text: 'Pregunta fuera de alcance' },
          {
            id: 'a1',
            role: 'assistant',
            text: unsupportedResponse.final_text,
            response: unsupportedResponse,
            outcome: unsupportedResponse.outcome,
            llmUsed: unsupportedResponse.llm_used,
            degraded: false,
          },
        ]}
      />,
    );

    expect(screen.queryByRole('button', { name: 'Compartir tarjeta' })).not.toBeInTheDocument();
  });

  test('does not show share buttons for assistant error turns', () => {
    render(
      <MessageList
        loading={false}
        messages={[
          { id: 'u1', role: 'user', text: '¿Qué pasó?' },
          { id: 'a1', role: 'assistant', text: 'Error inesperado', isError: true },
        ]}
      />,
    );

    expect(screen.queryByRole('button', { name: 'Compartir tarjeta' })).not.toBeInTheDocument();
  });
});
