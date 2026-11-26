/**
 * @jest-environment jsdom
 *
 * The reading row against the backend's own serialized examples (query_reading_examples.json is written by the
 * renderer and pinned by its tests), every example in both languages.
 */
import fs from 'node:fs';
import path from 'node:path';

import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import QueryReadingRow from '../components/intents/QueryReadingRow';
import type { QueryReading } from '../lib/types';

interface Example {
  name: string;
  state: string;
  reading: Record<'es' | 'en', QueryReading>;
}

const EXAMPLES: Example[] = JSON.parse(
  fs.readFileSync(
    path.resolve(__dirname, '../../fpl-grounded-assistant/tests/fixtures/query_reading_examples.json'),
    'utf8',
  ),
);
const CASES = EXAMPLES.flatMap((e) => (['es', 'en'] as const).map((lang) => [e.name, lang, e.reading[lang]] as const));

const items = () => within(screen.getByTestId('query-reading')).getAllByRole('listitem');

test('the fixture covers the four states', () => {
  expect(new Set(EXAMPLES.map((e) => e.state))).toEqual(
    new Set(['complete', 'needs_clarification', 'unsupported_constraint', 'data_unavailable']),
  );
});

describe.each(CASES)('%s (%s)', (_name, lang, reading) => {
  test('draws every part, in order, with the backend labels and no others', () => {
    render(<QueryReadingRow reading={reading} onPick={() => {}} />);
    expect(items().map((li) => li.textContent?.replace(/[⚠▾]/g, ''))).toEqual(reading.parts.map((p) => p.label));
    expect(screen.getByTestId('query-reading')).toHaveAttribute('lang', lang);
  });

  test('marks exactly the braked parts', () => {
    render(<QueryReadingRow reading={reading} onPick={() => {}} />);
    expect(items().map((li) => li.hasAttribute('data-braked'))).toEqual(reading.parts.map((p) => p.braked));
  });

  test('only editable parts with choices are buttons, and each pick sends that exact spec', () => {
    const onPick = jest.fn();
    render(<QueryReadingRow reading={reading} onPick={onPick} />);
    expect(items().map((li) => within(li).queryByRole('button') != null)).toEqual(
      reading.parts.map((p) => p.editable && p.alternatives.length > 0),
    );
    reading.parts.forEach((part, i) => {
      if (!part.editable) return;
      part.alternatives.forEach((alternative, j) => {
        fireEvent.click(within(items()[i]).getByRole('button'));
        fireEvent.click(within(screen.getByRole('group')).getAllByRole('button')[j]);
        expect(onPick).toHaveBeenLastCalledWith(alternative.spec, part, alternative);
        expect(screen.queryByRole('group')).toBeNull();
      });
    });
    const picks = reading.parts.reduce((n, p) => n + (p.editable ? p.alternatives.length : 0), 0);
    expect(onPick).toHaveBeenCalledTimes(picks);
  });

  test('with nothing to send a pick to, nothing is a button', () => {
    render(<QueryReadingRow reading={reading} />);
    expect(screen.queryByRole('button')).toBeNull();
  });
});

const editableExample = () => EXAMPLES[0].reading.en;

test('one set of choices is open at a time, and a second tap closes it', () => {
  const reading = editableExample();
  render(<QueryReadingRow reading={reading} onPick={() => {}} />);
  const pills = screen.getAllByRole('button');
  fireEvent.click(pills[0]);
  fireEvent.click(pills[1]);
  expect(screen.getAllByRole('group')).toHaveLength(1);
  expect(pills[0]).toHaveAttribute('aria-expanded', 'false');
  expect(pills[1]).toHaveAttribute('aria-expanded', 'true');
  fireEvent.click(pills[1]);
  expect(screen.queryByRole('group')).toBeNull();
});

test('a part kind the UI has never heard of is drawn from its label', () => {
  const reading: QueryReading = {
    lang: 'en',
    text: '',
    parts: [{ kind: 'something_new', label: 'Server words', value: null, editable: false, alternatives: [], braked: true }],
  };
  render(<QueryReadingRow reading={reading} onPick={() => {}} />);
  expect(screen.getByText('Server words')).toBeInTheDocument();
  expect(items()[0]).toHaveAttribute('data-braked');
});
