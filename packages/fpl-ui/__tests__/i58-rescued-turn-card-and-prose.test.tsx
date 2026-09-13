/**
 * @jest-environment jsdom
 *
 * i58 — a turn rescued by the i46 extra round shows the card AND the prose.
 *
 * Backend side (PR for i58): the harness card gate now reads "one distinct
 * tool with cardable output" instead of `tool_call_count == 1`, so a turn
 * where the model called `rank_players_by_metric` twice and then wrote prose
 * arrives with BOTH `synthesis_turn: true` and a non-null `generic_card`.
 *
 * Client side: nothing new was needed. `MessageList` already renders the
 * model's prose as the "Veredicto" band above the structured rows whenever
 * the backend says the model wrote it (`synthesis_turn !== false`), and
 * drops it when the backend says the text is a deterministic render
 * (`synthesis_turn === false`) — commits 98d8ae3 / f56a4f8, 2026-09-04.
 *
 * This file pins that contract for the exact payload shape the rescued turn
 * produces, asserting from the DOM: with `synthesis_turn: true` both nodes
 * are present (card and prose, prose above); with `synthesis_turn: false`
 * only the card is. The Message is built the way ChatShell builds it
 * (`text: response.final_text`, `response`).
 */
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import MessageList, { type Message } from '../components/chat/MessageList';
import type { AskResponse } from '../lib/types';
import { orchestratorRankCardResponse } from './fixtures/sample-responses';

/** The /ask payload of a rescued turn: model prose + the card composed from
 *  the retained tool output. `synthesis_turn` is the field the harness
 *  projects from OrchestratorResult; the count is not on the wire. */
const RESCUED_PROSE =
  'Haaland lidera por xG con diferencia. Palmer es la alternativa con más riesgo; B.Fernandes suma por volumen.';

function rescuedTurn(overrides: Partial<AskResponse> = {}): AskResponse {
  return {
    ...orchestratorRankCardResponse,
    final_text: RESCUED_PROSE,
    synthesis_turn: true,
    ...overrides,
  };
}

function asChatShellWould(response: AskResponse): Message {
  return {
    id: 'a-rescued',
    role: 'assistant',
    text: response.final_text,
    outcome: response.outcome,
    llmUsed: response.llm_used,
    degraded: response.degraded,
    response,
  };
}

beforeAll(() => {
  // jsdom has no scrollIntoView; MessageList calls it in a mount effect.
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    configurable: true,
    value: jest.fn(),
  });
});

describe('i58 — rescued turn (synthesis_turn: true + generic_card)', () => {
  test('renders BOTH the card and the prose, prose above the rows', () => {
    render(
      <MessageList messages={[asChatShellWould(rescuedTurn())]} loading={false} />,
    );

    const surface = screen.getByRole('region', { name: 'Respuesta estructurada' });
    const verdict = within(surface).getByRole('region', { name: 'Veredicto' });
    const data = within(surface).getByRole('region', { name: 'Datos de la recomendación' });

    // The prose node carries the model's text …
    expect(within(verdict).getByText(/Haaland lidera por xG/)).toBeInTheDocument();
    // … and the card node carries the composed rows.
    expect(within(data).getByText('TOP 3 · Puntos')).toBeInTheDocument();
    expect(within(data).getByText('Haaland')).toBeInTheDocument();
    expect(within(data).getByText('Palmer')).toBeInTheDocument();

    // Prose first, rows second — the surface's existing order.
    const sections = Array.from(surface.querySelectorAll(':scope > section'));
    expect(sections.map((s) => s.getAttribute('aria-label'))).toEqual([
      'Veredicto',
      'Datos de la recomendación',
    ]);

    // Exactly one answer surface: the prose did not get its own bubble.
    expect(screen.getAllByRole('region', { name: 'Respuesta estructurada' })).toHaveLength(1);
  });

  test('the prose is not duplicated by the card and the card is not duplicated by the prose', () => {
    render(
      <MessageList messages={[asChatShellWould(rescuedTurn())]} loading={false} />,
    );
    expect(screen.getAllByText(/Haaland lidera por xG/)).toHaveLength(1);
    expect(screen.getAllByText('TOP 3 · Puntos')).toHaveLength(1);
  });
});

describe('i58 — same payload, synthesis_turn: false (pinned: card only)', () => {
  test('drops the prose the backend says it did not write, keeps the card', () => {
    const rendered = rescuedTurn({
      // What the backend ships when the extra round did NOT rescue the turn:
      // the deterministic render behind the i46 (c) notice.
      final_text: 'Esto es lo que devolvió la herramienta:\n\n' + orchestratorRankCardResponse.final_text,
      synthesis_turn: false,
    });
    render(<MessageList messages={[asChatShellWould(rendered)]} loading={false} />);

    expect(screen.queryByRole('region', { name: 'Veredicto' })).not.toBeInTheDocument();
    expect(screen.queryByText(/devolvió la herramienta/)).not.toBeInTheDocument();
    const data = screen.getByRole('region', { name: 'Datos de la recomendación' });
    expect(within(data).getByText('TOP 3 · Puntos')).toBeInTheDocument();
  });
});
