/**
 * @jest-environment jsdom
 *
 * Rotating loading words: a new word every ~2.5 s, never the same twice in a row, one static word under
 * prefers-reduced-motion, the words live in both dictionaries, and the EO pending line is untouched.
 */
import React from 'react';
import { act, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import LoadingWord, { LOADING_WORD_COUNT, LOADING_WORD_INTERVAL_MS, nextWordIndex } from '../components/chat/LoadingWord';
import MessageList from '../components/chat/MessageList';
import { LocaleProvider } from '../lib/i18n/LocaleProvider';
import { en } from '../lib/i18n/en';
import { es } from '../lib/i18n/es';

if (typeof Element.prototype.scrollIntoView !== 'function') {
  Element.prototype.scrollIntoView = () => {};
}

function mockReducedMotion(reduced: boolean) {
  window.matchMedia = jest.fn((query: string) => ({
    matches: reduced && query.includes('prefers-reduced-motion'),
    media: query,
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
  })) as unknown as typeof window.matchMedia;
}

function renderWord(locale: 'es' | 'en' = 'en') {
  return render(
    <LocaleProvider initialLocale={locale} canSwitch={false}>
      <LoadingWord />
    </LocaleProvider>,
  );
}

const dictionaries = en as unknown as Record<string, string>;
const word = () => screen.getByTestId('loading-word').textContent ?? '';

beforeEach(() => {
  jest.useFakeTimers();
  mockReducedMotion(false);
});
afterEach(() => {
  jest.useRealTimers();
});

describe('LoadingWord', () => {
  test('starts on the first word and changes every 2.5 s', () => {
    renderWord('en');
    const first = word();
    expect(first).toBe(`${dictionaries['loading.word.1']}…`);
    act(() => {
      jest.advanceTimersByTime(LOADING_WORD_INTERVAL_MS - 1);
    });
    expect(word()).toBe(first);
    act(() => {
      jest.advanceTimersByTime(1);
    });
    expect(word()).not.toBe(first);
  });

  test('never shows the same word twice in a row', () => {
    renderWord('es');
    let previous = word();
    for (let i = 0; i < 60; i += 1) {
      act(() => {
        jest.advanceTimersByTime(LOADING_WORD_INTERVAL_MS);
      });
      expect(word()).not.toBe(previous);
      previous = word();
    }
  });

  test('nextWordIndex never returns the current index, whatever the random draw', () => {
    for (let current = 0; current < LOADING_WORD_COUNT; current += 1) {
      for (const draw of [0, 0.1, 0.5, 0.999999]) {
        const next = nextWordIndex(current, () => draw);
        expect(next).not.toBe(current);
        expect(next).toBeGreaterThanOrEqual(0);
        expect(next).toBeLessThan(LOADING_WORD_COUNT);
      }
    }
  });

  test('prefers-reduced-motion: one static word, no pulse', () => {
    mockReducedMotion(true);
    renderWord('en');
    const first = word();
    act(() => {
      jest.advanceTimersByTime(60_000);
    });
    expect(word()).toBe(first);
    expect(jest.getTimerCount()).toBe(0);
  });

  test('stops rotating when it goes away', () => {
    const { unmount } = renderWord('en');
    unmount();
    expect(jest.getTimerCount()).toBe(0);
  });
});

describe('the words in the dictionaries', () => {
  test('every slot has an EN and an ES word, and they differ', () => {
    const spanish = es as unknown as Record<string, string>;
    for (let n = 1; n <= LOADING_WORD_COUNT; n += 1) {
      const key = `loading.word.${n}`;
      expect(dictionaries[key]).toBeTruthy();
      expect(spanish[key]).toBeTruthy();
      expect(spanish[key]).not.toBe(dictionaries[key]);
    }
    const unique = new Set(Array.from({ length: LOADING_WORD_COUNT }, (_, i) => dictionaries[`loading.word.${i + 1}`]));
    expect(unique.size).toBe(LOADING_WORD_COUNT);
  });
});

describe('MessageList', () => {
  const pendingEo = { messageId: 'a1', tool: 'get_league_eo', etaS: 20, timedOut: false };
  const messages = [
    { id: 'a1', role: 'assistant', text: 'Calculando', response: null },
  ] as unknown as React.ComponentProps<typeof MessageList>['messages'];

  function renderList(loading: boolean, locale: 'es' | 'en' = 'es') {
    return render(
      <LocaleProvider initialLocale={locale} canSwitch={false}>
        <MessageList
          messages={messages}
          loading={loading}
          onFollowUp={jest.fn()}
          followUpArmedFor={null}
          compareWizard={null as never}
          onSuggestionPick={jest.fn()}
          playerPickWizard={null as never}
          onPlayerPick={jest.fn()}
          pendingEo={pendingEo}
        />
      </LocaleProvider>,
    );
  }

  test('the generic indicator is a rotating word, not the old static line', () => {
    renderList(true);
    expect(screen.getByTestId('loading-word')).toBeInTheDocument();
    expect(screen.queryByText('Pensando…')).toBeNull();
  });

  test('the EO pending line keeps its own text, with or without the generic indicator', () => {
    const { unmount } = renderList(false, 'es');
    expect(screen.getByTestId('eo-pending')).toHaveTextContent('Calculando el EO de tu liga… (~20 s)');
    expect(screen.queryByTestId('loading-word')).toBeNull();
    unmount();
    renderList(true, 'en');
    expect(screen.getByTestId('eo-pending')).toHaveTextContent('Calculating your league’s EO… (~20 s)');
  });
});
