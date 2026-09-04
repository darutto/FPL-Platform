/**
 * @jest-environment jsdom
 *
 * MessageList — orchestrator atomic-tool ranking card.
 *
 * Locks in the integrated-verdict treatment: when an orchestrator turn carries
 * a generic_card, MessageList keeps final_text and the structured rows in one
 * answer surface. There is no assistant bubble wrapped around a second card.
 */
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import MessageList, { type Message } from '../components/chat/MessageList';
import { orchestratorRankCardResponse } from './fixtures/sample-responses';

function assistantMessage(text = 'Haaland lidera por su producción sostenida. Palmer ofrece una alternativa con más riesgo.'): Message {
  return {
    id: 'a1',
    role: 'assistant',
    text,
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
  test('keeps final_text above the rows inside one structured answer surface', () => {
    const { container } = render(<MessageList messages={[assistantMessage()]} loading={false} />);

    const surface = screen.getByRole('region', { name: 'Respuesta estructurada' });
    const verdict = within(surface).getByRole('region', { name: 'Veredicto' });
    const data = within(surface).getByRole('region', { name: 'Datos de la recomendación' });

    expect(within(verdict).getByText(/Haaland lidera/)).toBeInTheDocument();
    expect(within(data).getByText('TOP 3 · Puntos')).toBeInTheDocument();
    expect(within(data).getByText('Haaland')).toBeInTheDocument();
    expect(verdict.parentElement).toBe(surface);
    expect(data.parentElement).toBe(surface);

    // Only the integrated surface carries top-level card chrome. In
    // particular, there is no assistant text bubble around the intent card.
    expect(surface).toHaveClass('rounded-card');
    expect(surface).toHaveClass('border');
    expect(container.querySelectorAll('[aria-label="Respuesta estructurada"]')).toHaveLength(1);
    expect(surface.parentElement).toHaveClass('max-w-prose');
    expect(surface.parentElement).not.toHaveClass('bg-white/5');
    expect(surface.parentElement?.parentElement).toHaveClass('flex');
  });
  test('drops a final_text that is itself the table, keeping only the card', () => {
    // The backend still emits the ranking as an ASCII table in final_text on
    // some orchestrator turns. Printing it above the styled card is the
    // duplication the card replaced; the verdict band must not accept it.
    render(
      <MessageList
        messages={[assistantMessage(orchestratorRankCardResponse.final_text)]}
        loading={false}
      />,
    );

    const surface = screen.getByRole('region', { name: 'Respuesta estructurada' });
    expect(screen.queryByRole('region', { name: 'Veredicto' })).not.toBeInTheDocument();
    expect(within(surface).getByText('TOP 3 · Puntos')).toBeInTheDocument();
    expect(screen.queryByText(/Valor métrica/)).not.toBeInTheDocument();
    expect(screen.queryByText(/#\s*\|\s*Jugador/)).not.toBeInTheDocument();
  });
});
