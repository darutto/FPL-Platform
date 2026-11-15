/**
 * @jest-environment jsdom
 *
 * The choice chips (compare wizard + single-tap player pick) render their copy in the
 * request locale and show the backend labels verbatim.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { LocaleProvider } from '@/lib/i18n/LocaleProvider';
import SuggestionChips, { PlayerPickChips } from '@/components/chat/SuggestionChips';

const options = [
  { label: 'João Pedro (CHE)', send_text: 'compare João Pedro (CHE)', player_id: 1 },
  { label: 'João Pedro (BHA)', send_text: 'compare João Pedro (BHA)', player_id: 2 },
] as never[];

function wrap(locale: 'en' | 'es', node: React.ReactNode) {
  return render(
    <LocaleProvider initialLocale={locale} canSwitch={false}>{node}</LocaleProvider>,
  );
}

test('compare wizard chips are English in EN', () => {
  wrap('en', <SuggestionChips wizard={{ playerA: null, options }} onPick={() => {}} />);
  expect(screen.getByText('Who is the first player?')).toBeInTheDocument();
  expect(screen.getByText('João Pedro (CHE)')).toBeInTheDocument();
  expect(screen.getByText('Cannot see your player? Type the name below.')).toBeInTheDocument();
});

test('player pick chips are English in EN and Spanish in ES', () => {
  const { unmount } = wrap('en', <PlayerPickChips wizard={{ options, sessionId: null }} onPick={() => {}} />);
  expect(screen.getByText('Which of these players did you mean?')).toBeInTheDocument();
  unmount();
  wrap('es', <PlayerPickChips wizard={{ options, sessionId: null }} onPick={() => {}} />);
  expect(screen.getByText('¿Cuál de estos jugadores buscabas?')).toBeInTheDocument();
});
