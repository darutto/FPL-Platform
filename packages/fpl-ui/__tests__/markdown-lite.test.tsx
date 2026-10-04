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

  // i126: *cursiva* reached the chat as literal asterisks.
  test('renders *italic* as <em>, not literal asterisks', () => {
    const { container } = render(<MarkdownLite text="Ojo: *riesgo de rotación* esta jornada" />);
    const em = container.querySelector('em');
    expect(em).not.toBeNull();
    expect(em).toHaveTextContent('riesgo de rotación');
    expect(container).toHaveTextContent('Ojo: riesgo de rotación esta jornada');
    expect(container.textContent).not.toContain('*');
  });

  test('**bold** stays bold, never two italics', () => {
    const { container } = render(<MarkdownLite text="El mejor es **Haaland** y *Salah* después" />);
    expect(container.querySelectorAll('strong')).toHaveLength(1);
    expect(container.querySelector('strong')).toHaveTextContent('Haaland');
    const ems = container.querySelectorAll('em');
    expect(ems).toHaveLength(1);
    expect(ems[0]).toHaveTextContent('Salah');
    expect(container.textContent).not.toContain('*');
  });

  test('a lone `*` stays literal ("5 * 2", "a * b * c")', () => {
    const { container } = render(<MarkdownLite text={'Son 5 * 2 puntos\na * b * c'} />);
    expect(container.querySelector('em')).toBeNull();
    expect(container).toHaveTextContent('Son 5 * 2 puntos');
    expect(container).toHaveTextContent('a * b * c');
  });

  test('a `* item` bullet is a list item, and italics inside it still render', () => {
    const { container } = render(<MarkdownLite text={'* Palmer\n* *Saka* en duda'} />);
    const items = container.querySelectorAll('ul > li');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent(/^Palmer$/);
    expect(items[0].querySelector('em')).toBeNull();
    expect(items[1].querySelector('em')).toHaveTextContent('Saka');
    expect(container.textContent).not.toContain('*');
  });

  test('underscores are never italics (internal names keep their shape)', () => {
    const { container } = render(<MarkdownLite text="campo dgw_teams y _algo_" />);
    expect(container.querySelector('em')).toBeNull();
    expect(container).toHaveTextContent('campo dgw_teams y _algo_');
  });

  test('an asterisk that opens or closes on a space is not italics', () => {
    const { container } = render(<MarkdownLite text={'* a* y *b *'} />);
    // "* a* y *b *" is a bullet ("a* y *b *"); neither pair qualifies
    expect(container.querySelector('em')).toBeNull();
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

// ---------------------------------------------------------------------------
// i138 — tables (prod 2026-10-04: «Compara a Haaland con Cole Palmer» showed
// «| Dato | Haaland | Palmer |» as raw lines)
// ---------------------------------------------------------------------------

describe('MarkdownLite — tables (i138)', () => {
  const PROD = [
    'Comparación directa:',
    '',
    '| Dato | Haaland | Palmer |',
    '|---|---:|---:|',
    '| Forma | **8.5** | 6.0 |',
    '| xGI/90 | 0.95 | *0.61* |',
    '',
    'Haaland sale mejor.',
  ].join('\n');

  test('the prod comparison renders as a table, with no raw pipes or dashes', () => {
    const { container } = render(<MarkdownLite text={PROD} />);
    const table = container.querySelector('table');
    expect(table).not.toBeNull();
    const ths = Array.from(table!.querySelectorAll('th')).map((t) => t.textContent);
    expect(ths).toEqual(['Dato', 'Haaland', 'Palmer']);
    const rows = Array.from(table!.querySelectorAll('tbody tr')).map((tr) =>
      Array.from(tr.querySelectorAll('td')).map((td) => td.textContent),
    );
    expect(rows).toEqual([['Forma', '8.5', '6.0'], ['xGI/90', '0.95', '0.61']]);
    expect(container.textContent).not.toContain('|');
    expect(container.textContent).not.toContain('---');
    // the paragraphs around it are untouched
    expect(container.querySelectorAll('p')).toHaveLength(2);
    expect(container).toHaveTextContent('Haaland sale mejor.');
  });

  test('bold and italic still render inside cells', () => {
    const { container } = render(<MarkdownLite text={PROD} />);
    expect(container.querySelector('td strong')).toHaveTextContent('8.5');
    expect(container.querySelector('td em')).toHaveTextContent('0.61');
    expect(container.textContent).not.toContain('*');
  });

  test('alignment comes from the separator row', () => {
    const text = '| a | b | c | d |\n|:--|:-:|--:|---|\n| 1 | 2 | 3 | 4 |';
    const { container } = render(<MarkdownLite text={text} />);
    const tds = Array.from(container.querySelectorAll('td')) as HTMLElement[];
    expect(tds.map((td) => td.style.textAlign)).toEqual(['left', 'center', 'right', 'left']);
    const ths = Array.from(container.querySelectorAll('th')) as HTMLElement[];
    expect(ths[2].style.textAlign).toBe('right');
  });

  test('outer pipes are optional', () => {
    const { container } = render(<MarkdownLite text={'Dato | Haaland\n--- | ---\nForma | 8.5'} />);
    expect(Array.from(container.querySelectorAll('th')).map((t) => t.textContent)).toEqual(['Dato', 'Haaland']);
    expect(container.querySelector('td')).toHaveTextContent('Forma');
  });

  test('a line with a stray | and no separator stays a paragraph', () => {
    const { container } = render(<MarkdownLite text={'Haaland | Palmer: duelo de la jornada\nOtra línea'} />);
    expect(container.querySelector('table')).toBeNull();
    expect(container.querySelector('p')).toHaveTextContent('Haaland | Palmer: duelo de la jornada');
  });

  test('a separator of another width does not make a table', () => {
    const { container } = render(<MarkdownLite text={'| a | b | c |\n|---|---|\n| 1 | 2 | 3 |'} />);
    expect(container.querySelector('table')).toBeNull();
    expect(container.textContent).toContain('| a | b | c |');
  });

  test('a plain line followed by --- is not a table', () => {
    const { container } = render(<MarkdownLite text={'Resumen\n---'} />);
    expect(container.querySelector('table')).toBeNull();
  });

  test('an escaped \| is a literal pipe inside a cell', () => {
    const { container } = render(<MarkdownLite text={'| Jugada | Nota |\n|---|---|\n| a \\| b | ok |'} />);
    const tds = Array.from(container.querySelectorAll('td')).map((td) => td.textContent);
    expect(tds).toEqual(['a | b', 'ok']);
  });

  test('short rows are padded and long rows are cut to the header width', () => {
    const { container } = render(<MarkdownLite text={'| a | b |\n|---|---|\n| 1 |\n| 1 | 2 | 3 |'} />);
    const rows = Array.from(container.querySelectorAll('tbody tr')).map((tr) =>
      Array.from(tr.querySelectorAll('td')).map((td) => td.textContent),
    );
    expect(rows).toEqual([['1', ''], ['1', '2']]);
  });

  test('the table ends at a line without | and a list after it is still a list', () => {
    const text = '| a | b |\n|---|---|\n| 1 | 2 |\n- uno\n- dos';
    const { container } = render(<MarkdownLite text={text} />);
    expect(container.querySelectorAll('tbody tr')).toHaveLength(1);
    expect(container.querySelectorAll('ul li')).toHaveLength(2);
  });

  test('a list before the table is closed, not merged', () => {
    const text = '- uno\n| a | b |\n|---|---|\n| 1 | 2 |';
    const { container } = render(<MarkdownLite text={text} />);
    expect(container.querySelectorAll('ul li')).toHaveLength(1);
    expect(container.querySelector('table')).not.toBeNull();
  });

  test('the table scrolls horizontally inside its own wrapper', () => {
    const { container } = render(<MarkdownLite text={PROD} />);
    const wrapper = container.querySelector('table')!.parentElement!;
    expect(wrapper.className).toContain('overflow-x-auto');
    expect(wrapper.getAttribute('role')).toBe('region');
  });
});
