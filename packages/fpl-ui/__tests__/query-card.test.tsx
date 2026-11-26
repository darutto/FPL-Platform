/**
 * @jest-environment jsdom
 *
 * The query card and its routing in the four states.
 *
 * `reading` is the backend's own serialized block (query_reading_examples.json). The rest of each query block
 * is written here to the wire shape agreed for the door (query layer PR 6) and is to be replaced by that PR's
 * serialized bodies.
 */
import fs from 'node:fs';
import path from 'node:path';

import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import IntentRenderer from '../components/chat/IntentRenderer';
import ShareCard from '../components/share/ShareCard';
import { selectIntentView } from '../lib/intent-renderer';
import { QueryActionsProvider, type QueryActions } from '../lib/chat-ask';
import { queryContextForNextTurn } from '../lib/query-context';
import { comparisonOkResponse } from './fixtures/sample-responses';
import type { AskResponse, QueryBlock, QueryReading } from '../lib/types';

interface Example {
  name: string;
  state: string;
  spec: Record<string, unknown>;
  reading: Record<'es' | 'en', QueryReading>;
}

const EXAMPLES: Example[] = JSON.parse(
  fs.readFileSync(
    path.resolve(__dirname, '../../fpl-grounded-assistant/tests/fixtures/query_reading_examples.json'),
    'utf8',
  ),
);
const example = (name: string) => EXAMPLES.find((e) => e.name === name)!;

const TABLE: NonNullable<QueryBlock['table']> = {
  columns: [
    { header: 'Player', align: 'left', kind: 'text' },
    { header: 'Value', align: 'right', kind: 'mono' },
  ],
  rows: [['Alfa (AAA)', '1.4–1.7'], ['Beta (BBB)', '12']],
};

const side = (label: string, value: string) => ({
  label, gameweeks: [1, 3], n: 2, home: 1, away: 1, mean_fdr_text: '2.5', value_text: value,
  total_text: `total ${value}`, per_match_text: `each ${value}`, per_match_values_text: [`first ${value}`],
});

const COMPARISON: NonNullable<QueryBlock['comparison']> = {
  club: 'AAA', metric_header: 'Server header', sides: [side('Side one', '1.9'), side('Side two', '0.7–0.9')],
  mixed: [], before_join: [1, 2], small_sample: true, ranges_overlap: true,
};

function block(name: string, over: Partial<QueryBlock> = {}, lang: 'es' | 'en' = 'en'): QueryBlock {
  const e = example(name);
  return {
    v: 1, state: e.state, reason: null, spec: e.spec, reading: e.reading[lang], table: null, comparison: null,
    chips: [], notes: [], message: null, sum_check: null, changed_parts: [], ...over,
  };
}

function answer(query: QueryBlock): AskResponse {
  return {
    ...comparisonOkResponse,
    comparison: null,
    intent: 'query',
    outcome: (query.state === 'complete' ? 'ok' : query.state) as AskResponse['outcome'],
    final_text: 'Showing: the text-only answer',
    query,
  };
}

function show(query: QueryBlock, actions: QueryActions | null = { pick: jest.fn(), correct: jest.fn() }) {
  const card = <IntentRenderer response={answer(query)} />;
  render(actions ? <QueryActionsProvider value={actions}>{card}</QueryActionsProvider> : card);
  return actions;
}

describe('routing', () => {
  test.each(EXAMPLES.map((e) => [e.name]))('%s opens the query card whatever its outcome', (name) => {
    expect(selectIntentView(answer(block(name)))).toBe('query');
  });

  test('a state the UI does not know is text only, even with a table in the body', () => {
    const response = answer(block('low_ownership_last_5', { state: 'something_new', table: TABLE }));
    response.outcome = 'ok';
    response.generic_card = comparisonOkResponse.generic_card;
    expect(selectIntentView(response)).toBeNull();
  });

  test('without a query block nothing changes', () => {
    expect(selectIntentView(comparisonOkResponse)).toBe('comparison');
  });
});

describe('complete', () => {
  test('the reading row comes first, then the server cells as sent', () => {
    show(block('low_ownership_last_5', { table: TABLE }));
    const card = screen.getByTestId('query-card');
    const reading = within(card).getByTestId('query-reading');
    const table = within(card).getByRole('table');
    expect(reading.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(table).getByText('1.4–1.7')).toBeInTheDocument();
    expect(card).not.toHaveTextContent('Showing: the text-only answer');
  });

  test('a comparison shows both sides in the order sent, and the note about excluded gameweeks', () => {
    show(block('team_with_without', { comparison: COMPARISON, notes: ['Server note: GW1–2 left out'] }));
    const sides = screen.getAllByTestId('query-side');
    expect(sides.map((s) => s.getAttribute('aria-label'))).toEqual(['Side one', 'Side two']);
    expect(sides[1]).toHaveTextContent('0.7–0.9');
    expect(screen.getByText('Server header')).toBeInTheDocument();
    expect(screen.getByTestId('query-notes')).toHaveTextContent('Server note: GW1–2 left out');
    expect(screen.queryByRole('table')).toBeNull();
  });

  test('the part a tap changed is marked', () => {
    show(block('low_ownership_last_5', { table: TABLE, changed_parts: ['window'] }));
    const marked = Array.from(document.querySelectorAll('[data-changed]'), (el) => el.getAttribute('data-kind'));
    expect(marked).toEqual(['window']);
  });
});

describe.each([
  ['clarify_club', 'needs_clarification'],
  ['unsupported_outside_spec', 'unsupported_constraint'],
  ['missing_gameweek', 'data_unavailable'],
])('%s (%s)', (name, state) => {
  test('shows the reading and the message, never a table or a comparison', () => {
    // A table in a refusal would be a server fault; the card still must not draw it.
    show(block(name, { message: 'Server sentence', table: TABLE, comparison: COMPARISON }));
    expect(screen.getByTestId('query-card')).toHaveAttribute('data-state', state);
    expect(screen.getByTestId('query-reading')).toBeInTheDocument();
    expect(screen.getByText('Server sentence')).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByTestId('query-side')).toBeNull();
  });

  test('a chip sends its typed spec with its label', () => {
    const chip = { label: 'Server chip', spec: { v: 1, metric: 'bonus' } };
    const actions = show(block(name, { chips: [chip] }))!;
    fireEvent.click(screen.getByRole('button', { name: 'Server chip' }));
    expect(actions.pick).toHaveBeenCalledWith(chip.spec, 'Server chip');
  });
});

test('an unreadable call has no reading: the message alone, and no "Not this"', () => {
  show(block('clarify_club', { reading: null, spec: null, message: 'Server question' }));
  expect(screen.getByText('Server question')).toBeInTheDocument();
  expect(screen.queryByTestId('query-reading')).toBeNull();
  expect(screen.queryByRole('button')).toBeNull();
});

test('a reading pill sends the alternative spec', () => {
  const data = block('low_ownership_last_5', { table: TABLE });
  const actions = show(data)!;
  const windowPart = data.reading!.parts.find((p) => p.kind === 'window')!;
  fireEvent.click(screen.getByRole('button', { name: new RegExp(windowPart.label.slice(0, 6)) }));
  fireEvent.click(screen.getByRole('button', { name: windowPart.alternatives[0].label }));
  expect(actions.pick).toHaveBeenCalledWith(windowPart.alternatives[0].spec, windowPart.alternatives[0].label);
});

test('"Not this" hands over to the composer', () => {
  const actions = show(block('low_ownership_last_5', { table: TABLE }))!;
  fireEvent.click(screen.getByRole('button', { name: 'No es esto' }));
  expect(actions.correct).toHaveBeenCalledTimes(1);
});

test('outside the chat (a shared answer) nothing is tappable', () => {
  show(block('low_ownership_last_5', { table: TABLE, chips: [{ label: 'Server chip', spec: {} }] }), null);
  expect(screen.queryByRole('button')).toBeNull();
  expect(screen.getByRole('table')).toBeInTheDocument();
});

test('the share image drawn inside the chat has no taps either', () => {
  const data = block('low_ownership_last_5', { table: TABLE, chips: [{ label: 'Server chip', spec: {} }] });
  render(
    <QueryActionsProvider value={{ pick: jest.fn(), correct: jest.fn() }}>
      <ShareCard question="q" response={answer(data)} appUrl="https://example.test" cta="cta" />
    </QueryActionsProvider>,
  );
  expect(screen.getByTestId('query-card')).toBeInTheDocument();
  expect(screen.queryByRole('button')).toBeNull();
});

describe('what the next typed message carries', () => {
  const user = { role: 'user' as const };
  const queried = { role: 'assistant' as const, response: answer(block('low_ownership_last_5')) };

  test('the last answer spec, and whether "Not this" was tapped', () => {
    const spec = example('low_ownership_last_5').spec;
    expect(queryContextForNextTurn([user, queried], false)).toEqual({ spec, not_this: false });
    expect(queryContextForNextTurn([user, queried], true)).toEqual({ spec, not_this: true });
  });

  test('nothing after any other answer, an error, or a call with no spec', () => {
    const other = { role: 'assistant' as const, response: comparisonOkResponse };
    const error = { role: 'assistant' as const };
    const unreadable = { role: 'assistant' as const, response: answer(block('clarify_club', { spec: null })) };
    for (const last of [other, error, unreadable]) {
      expect(queryContextForNextTurn([queried, user, last], true)).toBeUndefined();
    }
    expect(queryContextForNextTurn([], false)).toBeUndefined();
  });
});
