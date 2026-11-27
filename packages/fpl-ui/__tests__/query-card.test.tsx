/**
 * @jest-environment jsdom
 *
 * The query card and its routing, from the backend's serialized /ask bodies (query_response_bodies.json,
 * written by the door's tests). A test that needs something no body carries changes a copy of a real one.
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
import type { AskResponse, QueryBlock } from '../lib/types';

const fixture = (name: string) =>
  JSON.parse(
    fs.readFileSync(path.resolve(__dirname, '../../fpl-grounded-assistant/tests/fixtures', name), 'utf8'),
  );

const BODIES: Record<string, AskResponse> = fixture('query_response_bodies.json');
const NAMES = Object.keys(BODIES);

/** A real body, its query block optionally changed. */
function answer(name: string, over: Partial<QueryBlock> = {}): AskResponse {
  const body: AskResponse = JSON.parse(JSON.stringify(BODIES[name]));
  Object.assign(body.query!, over);
  return body;
}

const COMPARE = 'complete_comparison_before_join';
const REFUSALS = ['needs_clarification', 'unsupported_constraint', 'data_unavailable', 'unreadable_call'];

function show(response: AskResponse, actions: QueryActions | null = { pick: jest.fn(), correct: jest.fn() }) {
  const card = <IntentRenderer response={response} />;
  render(actions ? <QueryActionsProvider value={actions}>{card}</QueryActionsProvider> : card);
  return actions;
}

test('the bodies cover the four states and a call that could not be read', () => {
  expect(new Set(NAMES.map((n) => BODIES[n].query!.state))).toEqual(
    new Set(['complete', 'needs_clarification', 'unsupported_constraint', 'data_unavailable']),
  );
  expect(BODIES.unreadable_call.query!.reading).toBeNull();
});

describe('routing', () => {
  test.each(NAMES)('%s opens the query card whatever its outcome', (name) => {
    expect(selectIntentView(answer(name))).toBe('query');
  });

  test('a state the UI does not know is text only, even with a table in the body', () => {
    const response = answer('complete_list_en', { state: 'something_new' });
    response.generic_card = comparisonOkResponse.generic_card;
    expect(selectIntentView(response)).toBeNull();
  });

  test('without a query block nothing changes', () => {
    expect(selectIntentView(comparisonOkResponse)).toBe('comparison');
  });
});

describe.each(NAMES)('%s', (name) => {
  const query = BODIES[name].query!;

  test('draws what the block carries, in the server words, and never the text copy', () => {
    show(answer(name));
    const card = screen.getByTestId('query-card');
    expect(card).toHaveAttribute('data-state', query.state);
    expect(screen.queryByTestId('query-reading') != null).toBe(query.reading != null);
    for (const part of query.reading?.parts ?? []) expect(card).toHaveTextContent(part.label);
    if (query.message != null) expect(within(card).getByText(query.message)).toBeInTheDocument();
    const notes = screen.queryByTestId('query-notes');
    expect(notes ? within(notes).getAllByRole('listitem').map((li) => li.textContent) : []).toEqual(query.notes);
    expect(screen.queryByRole('table') != null).toBe(query.table != null);
    expect(screen.queryAllByTestId('query-side')).toHaveLength(query.comparison ? 2 : 0);
    expect(card).not.toHaveTextContent(/Showing:|Muestro:/);
  });

  test('every chip sends its typed spec with its label', () => {
    const actions = show(answer(name))!;
    for (const chip of query.chips) {
      fireEvent.click(screen.getByRole('button', { name: chip.label }));
      expect(actions.pick).toHaveBeenLastCalledWith(chip.spec, chip.label);
    }
    expect(actions.pick).toHaveBeenCalledTimes(query.chips.length);
  });

  test('"Not this" is offered exactly when there is a spec and a reading to correct', () => {
    show(answer(name));
    expect(screen.queryByRole('button', { name: 'No es esto' }) != null).toBe(
      query.spec != null && query.reading != null,
    );
  });
});

test('a list is the server table: reading row first, then the cells as sent', () => {
  show(answer('complete_list_es'));
  const reading = screen.getByTestId('query-reading');
  const table = screen.getByRole('table');
  expect(reading.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  const expected = BODIES.complete_list_es.query!.table!;
  const rows = within(table).getAllByRole('row').slice(1);
  expect(rows.map((row) => within(row).getAllByRole('cell').map((cell) => cell.textContent))).toEqual(expected.rows);
});

test('a comparison says which gameweeks were left out because the player had not joined', () => {
  const query = BODIES[COMPARE].query!;
  expect(query.comparison!.before_join).not.toHaveLength(0);
  const line = query.notes.find((note) => note.includes('GW1'))!;
  show(answer(COMPARE));
  expect(screen.getByTestId('query-notes')).toHaveTextContent(line);
});

test('comparison sides keep the order sent, and no figure is drawn twice in a column', () => {
  const { sides, metric_header } = BODIES[COMPARE].query!.comparison!;
  show(answer(COMPARE));
  const columns = screen.getAllByTestId('query-side');
  expect(columns.map((c) => c.getAttribute('aria-label'))).toEqual(sides.map((side) => side.label));
  columns.forEach((column, i) => {
    // This comparison is per match, so the headline is the per-match figure: only total and matches follow.
    expect(sides[i].per_match_text).toBe(sides[i].value_text);
    expect(Array.from(column.querySelectorAll('dd'), (dd) => dd.textContent)).toEqual(
      [sides[i].total_text, String(sides[i].n)],
    );
  });
  // The metric is in the reading row only; the group carries it for screen readers.
  expect(screen.getByRole('group', { name: metric_header })).not.toHaveTextContent(metric_header);
});

test.each(REFUSALS)('%s never draws a table or a comparison, even if the body wrongly had one', (name) => {
  show(answer(name, { table: BODIES.complete_list_en.query!.table, comparison: BODIES[COMPARE].query!.comparison }));
  expect(screen.queryByRole('table')).toBeNull();
  expect(screen.queryByTestId('query-side')).toBeNull();
});

test('the part a tap changed is marked', () => {
  show(answer('complete_list_en', { changed_parts: ['window'] }));
  const marked = Array.from(document.querySelectorAll('[data-changed]'), (el) => el.getAttribute('data-kind'));
  expect(marked).toEqual(['window']);
});

test('a reading pill sends the alternative spec', () => {
  const part = BODIES.complete_list_en.query!.reading!.parts.find((p) => p.kind === 'window')!;
  const actions = show(answer('complete_list_en'))!;
  fireEvent.click(screen.getByRole('button', { name: new RegExp(part.label.slice(0, 6)) }));
  fireEvent.click(screen.getByRole('button', { name: part.alternatives[0].label }));
  expect(actions.pick).toHaveBeenCalledWith(part.alternatives[0].spec, part.alternatives[0].label);
});

test('"Not this" hands over to the composer', () => {
  const actions = show(answer('complete_list_es'))!;
  fireEvent.click(screen.getByRole('button', { name: 'No es esto' }));
  expect(actions.correct).toHaveBeenCalledTimes(1);
});

test.each(NAMES)('%s: outside the chat nothing is tappable', (name) => {
  show(answer(name), null);
  expect(screen.queryByRole('button')).toBeNull();
});

test('the share image drawn inside the chat has no taps either', () => {
  render(
    <QueryActionsProvider value={{ pick: jest.fn(), correct: jest.fn() }}>
      <ShareCard question="q" response={answer('needs_clarification')} appUrl="https://example.test" cta="cta" />
    </QueryActionsProvider>,
  );
  expect(screen.getByTestId('query-card')).toBeInTheDocument();
  expect(screen.queryByRole('button')).toBeNull();
});

describe('what the next typed message carries', () => {
  const user = { role: 'user' as const };
  const queried = { role: 'assistant' as const, response: BODIES.complete_list_es };
  const spec = BODIES.complete_list_es.query!.spec;

  test('the last answer spec, and whether "Not this" was tapped', () => {
    expect(queryContextForNextTurn([user, queried], false)).toEqual({ spec, not_this: false });
    expect(queryContextForNextTurn([user, queried], true)).toEqual({ spec, not_this: true });
  });

  test('nothing after any other answer, an error, or a call with no spec', () => {
    const other = { role: 'assistant' as const, response: comparisonOkResponse };
    const error = { role: 'assistant' as const };
    const unreadable = { role: 'assistant' as const, response: BODIES.unreadable_call };
    for (const last of [other, error, unreadable]) {
      expect(queryContextForNextTurn([queried, user, last], true)).toBeUndefined();
    }
    expect(queryContextForNextTurn([], false)).toBeUndefined();
  });
});
