/**
 * @jest-environment jsdom
 *
 * MarkdownLite — the shared minimal-markdown renderer, plus its use in the
 * assistant chat bubble. Locks in the "structured, never a raw text wall"
 * baseline for open-ended orchestrator answers.
 */
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import MarkdownLite from '../components/MarkdownLite';
import MessageList, { type Message } from '../components/chat/MessageList';
import type { AskResponse } from '../lib/types';

beforeAll(() => {
  // jsdom has no scrollIntoView; MessageList calls it in a mount effect.
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    configurable: true,
    value: jest.fn(),
  });
});

describe('MarkdownLite', () => {
  test('renders **bold** as <strong>, not literal asterisks', () => {
    const { container } = render(<MarkdownLite text="El mejor es **Haaland** hoy" />);
    const strong = container.querySelector('strong');
    expect(strong).not.toBeNull();
    expect(strong).toHaveTextContent('Haaland');
    // the asterisks themselves must be gone
    expect(container).not.toHaveTextContent('**Haaland**');
  });

  test('renders `- ` and `* ` lines as a single bullet list', () => {
    const { container } = render(
      <MarkdownLite text={'Opciones:\n- Saka\n* Palmer\n- Salah'} />,
    );
    const lists = container.querySelectorAll('ul');
    expect(lists).toHaveLength(1);
    expect(within(lists[0] as HTMLElement).getAllByRole('listitem')).toHaveLength(3);
    expect(screen.getByText('Saka')).toBeInTheDocument();
    expect(screen.getByText('Palmer')).toBeInTheDocument();
  });

  test('separates non-bullet lines into paragraphs and keeps plain text plain', () => {
    const { container } = render(<MarkdownLite text={'Primera línea.\nSegunda línea.'} />);
    expect(container.querySelectorAll('p')).toHaveLength(2);
    expect(container.querySelector('ul')).toBeNull();
    expect(container.querySelector('strong')).toBeNull();
  });

  test('empty string renders no blocks', () => {
    const { container } = render(<MarkdownLite text="" />);
    expect(container.querySelectorAll('p, ul, strong')).toHaveLength(0);
  });
});

// --- Assistant bubble integration --------------------------------------------

function textResponse(finalText: string): AskResponse {
  // A minimal orchestrator-style text turn: no card payload, so MessageList
  // takes the text-bubble path rather than a structured card.
  return {
    selected_tool: null,
    intent: 'unsupported',
    outcome: 'ok',
    supported: true,
    final_text: finalText,
  } as unknown as AskResponse;
}

function assistantMessage(text: string): Message {
  return { id: 'a1', role: 'assistant', text, outcome: 'ok', response: textResponse(text) };
}

function userMessage(text: string): Message {
  return { id: 'u1', role: 'user', text };
}

describe('MessageList assistant bubble uses MarkdownLite', () => {
  test('assistant prose renders markdown (bold + bullets), not raw markup', () => {
    render(
      <MessageList
        messages={[assistantMessage('Recomiendo **Haaland**.\n- barato\n- en forma')]}
        loading={false}
      />,
    );
    expect(document.querySelector('strong')).toHaveTextContent('Haaland');
    expect(document.querySelectorAll('ul li')).toHaveLength(2);
    expect(screen.queryByText(/\*\*Haaland\*\*/)).not.toBeInTheDocument();
  });

  test('user prompts stay verbatim (no markdown interpretation)', () => {
    render(<MessageList messages={[userMessage('gané con **mi** equipo')]} loading={false} />);
    // the user's literal asterisks survive; no <strong> is produced for them
    expect(screen.getByText('gané con **mi** equipo')).toBeInTheDocument();
    expect(document.querySelector('strong')).toBeNull();
  });
});
