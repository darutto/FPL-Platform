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

  // --- i81: headings + numbered lists ---------------------------------------

  test('`### Título` renders as <h3> and the literal ### never appears', () => {
    const { container } = render(<MarkdownLite text={'### Resumen del partido\nTexto.'} />);
    const h3 = container.querySelector('h3');
    expect(h3).not.toBeNull();
    expect(h3).toHaveTextContent('Resumen del partido');
    // the exact assertion for the bug as seen in prod: no raw hashes anywhere
    expect(container.textContent).not.toContain('#');
    expect(container.querySelectorAll('p')).toHaveLength(1);
  });

  test('`1.` / `2.` lines render as one <ol> with two <li> and no literal numbers', () => {
    const { container } = render(<MarkdownLite text={'1. Saka\n2. Palmer'} />);
    const ols = container.querySelectorAll('ol');
    expect(ols).toHaveLength(1);
    expect(within(ols[0] as HTMLElement).getAllByRole('listitem')).toHaveLength(2);
    expect(container.querySelector('ul')).toBeNull();
    expect(container.textContent).not.toMatch(/\d\./);
    expect(ols[0]).not.toHaveAttribute('start');
  });

  test('`1)` numbering is accepted too', () => {
    const { container } = render(<MarkdownLite text={'1) uno\n2) dos'} />);
    expect(container.querySelectorAll('ol li')).toHaveLength(2);
  });

  test('`- a` followed by `1. b` yields a distinct <ul> and <ol>, never merged', () => {
    const { container } = render(<MarkdownLite text={'- a\n1. b\n- c'} />);
    expect(container.querySelectorAll('ul')).toHaveLength(2);
    expect(container.querySelectorAll('ol')).toHaveLength(1);
    expect(container.querySelectorAll('ul li')).toHaveLength(2);
    expect(container.querySelectorAll('ol li')).toHaveLength(1);
    const kinds = Array.from(container.querySelectorAll('ul, ol')).map((e) => e.tagName);
    expect(kinds).toEqual(['UL', 'OL', 'UL']);
  });

  test('a heading after a list closes the list', () => {
    const { container } = render(<MarkdownLite text={'1. a\n## Siguiente\n1. b'} />);
    expect(container.querySelectorAll('ol')).toHaveLength(2);
    expect(container.querySelector('h2')).toHaveTextContent('Siguiente');
    const tags = Array.from(container.querySelectorAll('ol, h2')).map((e) => e.tagName);
    expect(tags).toEqual(['OL', 'H2', 'OL']);
  });

  test('a paragraph after a list closes the list', () => {
    const { container } = render(<MarkdownLite text={'- a\nTexto suelto\n- b'} />);
    expect(container.querySelectorAll('ul')).toHaveLength(2);
    expect(container.querySelectorAll('p')).toHaveLength(1);
  });

  test('a numbered list starting at 3 carries start=3', () => {
    const { container } = render(<MarkdownLite text={'3. tres\n4. cuatro'} />);
    expect(container.querySelector('ol')).toHaveAttribute('start', '3');
  });

  test('bold renders inside headings and numbered items', () => {
    const { container } = render(
      <MarkdownLite text={'### Capitán: **Haaland**\n1. **Salah** (LIV)'} />,
    );
    expect(container.querySelectorAll('strong')).toHaveLength(2);
    expect(container.querySelector('h3 strong')).toHaveTextContent('Haaland');
    expect(container.querySelector('ol li strong')).toHaveTextContent('Salah');
    expect(container.textContent).not.toContain('**');
  });

  test('`#` and `##` share the largest size; `####` collapses to the smallest', () => {
    const { container } = render(<MarkdownLite text={'# A\n## B\n#### D'} />);
    const h1 = container.querySelector('h1')!;
    const h2 = container.querySelector('h2')!;
    const h4 = container.querySelector('h4')!;
    expect(h1.className).toBe(h2.className);
    expect(h4.className).not.toBe(h1.className);
  });

  test('a lone `#` with no text is a paragraph, not an empty heading', () => {
    const { container } = render(<MarkdownLite text={'#'} />);
    expect(container.querySelector('h1')).toBeNull();
    expect(container.querySelectorAll('p')).toHaveLength(1);
  });

  test('empty string renders no blocks', () => {
    const { container } = render(<MarkdownLite text="" />);
    expect(container.querySelectorAll('p, ul, ol, h1, h2, h3, strong')).toHaveLength(0);
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
