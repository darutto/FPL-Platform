/** @jest-environment jsdom */
// The owner-only "Presentar" switch reads the Clerk session; these tests render the board without one.
jest.mock('@/lib/presentation-access', () => ({
  usePresentationAccess: () => (globalThis as { __owner?: boolean }).__owner !== false,
}));

import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import SwipePager, { PagerScreen } from '../components/chat/SwipePager';
import CardTable from '../components/intents/CardTable';
import MarkdownLite from '../components/MarkdownLite';
import PlayerCard from '../components/intents/PlayerCard';
import { FixturesBoard } from '../components/intents/FixturesBoard';
import { playerSnapshotOkResponse } from './fixtures/sample-responses';
import type { ReactNode } from 'react';

// jsdom has no PointerEvent constructor. Preserve the properties used by the
// browser's pointer identity/primary-button contract instead of plain Events.
function pointer(target: Element, type: string, x: number, y = 100, id = 1, extra = {}) {
  const event = new MouseEvent(type, { bubbles: true, clientX: x, clientY: y, button: 0 });
  Object.defineProperties(event, {
    pointerId: { value: id },
    pointerType: { value: 'touch' },
    isPrimary: { value: id === 1 },
    ...Object.fromEntries(Object.entries(extra).map(([key, value]) => [key, { value }])),
  });
  fireEvent(target, event);
}

function setup(child: ReactNode = <div data-testid="content">Content</div>) {
  const change = jest.fn();
  const view = render(
    <SwipePager screen={1} onScreenChange={change} labels={['Squad', 'Chat', 'Commands']}>
      <PagerScreen>{child}</PagerScreen>
    </SwipePager>,
  );
  const track = view.container.querySelector('[style*="translateX"]') as HTMLElement;
  return { ...view, change, track, surface: track.parentElement! };
}

function drag(target: Element, endX = 100, id = 1) {
  pointer(target, 'pointerdown', 220, 100, id);
  pointer(target, 'pointermove', endX, 100, id);
}

function makeScrollable(element: HTMLElement, scrollLeft = 0) {
  // Layout is not provided by jsdom. Declare browser-measured overflow, while
  // using actual card markup for the ancestor traversal.
  element.style.overflowX = 'auto';
  Object.defineProperties(element, { scrollWidth: { value: 700 }, clientWidth: { value: 350 } });
  element.scrollLeft = scrollLeft;
}

test.each([['left', 100, 2], ['right', 340, 0]])('completed %s swipe navigates once', (_, x, expected) => {
  const { surface, change } = setup();
  drag(surface, x as number);
  pointer(surface, 'pointerup', x as number);
  expect(change).toHaveBeenCalledTimes(1);
  expect(change).toHaveBeenCalledWith(expected);
});

test.each(['pointercancel', 'pointerout', 'lostpointercapture', 'touchcancel'])('%s abandons a threshold-crossing drag', (type) => {
  const { surface, track, change } = setup();
  drag(surface);
  expect(track.style.transform).toContain('-120px');
  pointer(surface, type, 100);
  pointer(surface, 'pointerup', 100);
  expect(track.style.transform).toContain('+ 0px');
  expect(change).not.toHaveBeenCalled();
});

test('a release outside the surface or window blur cannot commit a drag', () => {
  const { surface, change, track } = setup();
  drag(surface);
  pointer(document.body, 'pointerup', 100);
  pointer(surface, 'pointerup', 100);
  expect(change).not.toHaveBeenCalled();
  drag(surface);
  fireEvent(window, new Event('blur'));
  pointer(surface, 'pointerup', 100);
  expect(change).not.toHaveBeenCalled();
  expect(track.style.transform).toContain('+ 0px');
});

test('an unrelated pointer cannot move or finish a drag', () => {
  const { surface, change, track } = setup();
  pointer(surface, 'pointerdown', 220);
  pointer(surface, 'pointermove', 10, 100, 2);
  pointer(surface, 'pointerup', 10, 100, 2);
  expect(track.style.transform).toContain('+ 0px');
  expect(change).not.toHaveBeenCalled();
  pointer(surface, 'pointermove', 100);
  pointer(surface, 'pointerup', 100);
  expect(change).toHaveBeenCalledWith(2);
});

test('second finger aborts; lifting either finger cannot resume the abandoned swipe', () => {
  const { surface, change, track } = setup();
  drag(surface);
  pointer(document.body, 'pointerdown', 250, 100, 2);
  pointer(document.body, 'pointerup', 250, 100, 2);
  pointer(surface, 'pointermove', 0);
  pointer(surface, 'pointerup', 0);
  expect(change).not.toHaveBeenCalled();
  expect(track.style.transform).toContain('+ 0px');
  drag(surface);
  pointer(surface, 'pointerup', 100);
  expect(change).toHaveBeenCalledWith(2);
});

test('vertical-first and short gestures never navigate', () => {
  const { surface, change } = setup();
  pointer(surface, 'pointerdown', 220);
  pointer(surface, 'pointermove', 218, 140);
  pointer(surface, 'pointermove', 10, 145);
  pointer(surface, 'pointerup', 10, 145);
  drag(surface, 200);
  pointer(surface, 'pointerup', 200);
  expect(change).not.toHaveBeenCalled();
});

test('native panning is prevented only for an eligible single-finger horizontal drag', () => {
  const { surface, change } = setup();
  pointer(surface, 'pointerdown', 220);
  expect(fireEvent.touchMove(surface, { touches: [{ clientX: 100, clientY: 100 }] })).toBe(false);
  fireEvent.touchStart(surface, { touches: [{}, {}] });
  expect(fireEvent.touchMove(surface, { touches: [{ clientX: 90, clientY: 100 }, {}] })).toBe(true);
  pointer(surface, 'pointerup', 100);
  expect(change).not.toHaveBeenCalled();
  pointer(surface, 'pointerdown', 220);
  expect(fireEvent.touchMove(surface, { touches: [{ clientX: 218, clientY: 160 }] })).toBe(true);
});

test('a zoomed page keeps single-finger panning and never switches screens', () => {
  const descriptor = Object.getOwnPropertyDescriptor(window, 'visualViewport');
  Object.defineProperty(window, 'visualViewport', { configurable: true, value: { scale: 2 } });
  try {
    const { surface, change } = setup();
    drag(surface);
    expect(fireEvent.touchMove(surface, { touches: [{ clientX: 100, clientY: 100 }] })).toBe(true);
    pointer(surface, 'pointerup', 100);
    expect(change).not.toHaveBeenCalled();
  } finally {
    if (descriptor) Object.defineProperty(window, 'visualViewport', descriptor);
    else Reflect.deleteProperty(window, 'visualViewport');
  }
});

test.each([0, 175, 350])('CardTable owns horizontal gestures at scrollLeft=%i', (scrollLeft) => {
  const { change } = setup(<CardTable columns={[{ header: 'Player', align: 'left', kind: 'text' }]} rows={[['Haaland']]} />);
  const cell = screen.getByText('Haaland');
  const scroller = screen.getByRole('table').parentElement!;
  makeScrollable(scroller, scrollLeft);
  drag(cell);
  expect(fireEvent.touchMove(cell, { touches: [{ clientX: 100, clientY: 100 }] })).toBe(true);
  pointer(cell, 'pointerup', 100);
  expect(change).not.toHaveBeenCalled();
});

test('Markdown tables retain native touch scrolling and arrow key navigation', () => {
  const { change } = setup(<MarkdownLite text={'| Player | Points |\n| --- | --- |\n| Haaland | 10 |'} />);
  const scroller = screen.getByRole('region', { name: 'Tabla' });
  makeScrollable(scroller);
  const cell = screen.getByText('Haaland');
  drag(cell);
  pointer(cell, 'pointerup', 100);
  fireEvent.keyDown(scroller, { key: 'ArrowRight' });
  expect(change).not.toHaveBeenCalled();
});

test('nested controls and overlay opt-outs never start navigation', () => {
  const { change } = setup(<><button><svg data-testid="icon"><path /></svg></button><div data-no-swipe><p>Overlay</p></div></>);
  for (const target of [screen.getByTestId('icon'), screen.getByText('Overlay')]) {
    drag(target);
    pointer(target, 'pointerup', 100);
  }
  expect(change).not.toHaveBeenCalled();
});

test('tabs and keyboard still navigate', () => {
  const { change } = setup();
  fireEvent.click(screen.getAllByRole('button', { name: 'Commands' })[0]);
  expect(change).toHaveBeenLastCalledWith(2);
  fireEvent.keyDown(window, { key: 'ArrowLeft' });
  expect(change).toHaveBeenLastCalledWith(0);
});

test('arrow navigation works while a pager tab or edge hint has focus', () => {
  const { change } = setup();
  const tab = screen.getAllByRole('button', { name: 'Commands' })[0];
  tab.focus();
  fireEvent.keyDown(document.activeElement!, { key: 'ArrowLeft' });
  expect(change).toHaveBeenLastCalledWith(0);
  const hint = screen.getByTitle('Ir a Commands');
  hint.focus();
  fireEvent.keyDown(document.activeElement!, { key: 'ArrowRight' });
  expect(change).toHaveBeenLastCalledWith(2);
});

test('#402 player pitch allows pinch abandonment without navigating', () => {
  const { change } = setup(<PlayerCard data={{
    ...playerSnapshotOkResponse.player_snapshot!,
    zonal: { zones: [{ zone: 'in-box / central', share: 0.6 }], fixtures: [{ gameweek: 6, fixture_id: 6, opponent: 'Rival', opponent_short: 'RIV', is_home: true, status: 'neutral', matches: [] }], gw_from: 6, gw_to: 8, verdict_kind: 'neutral', verdict: 'Neutral', data_provenance: null },
  }} />);
  const pitch = screen.getByTestId('player-zones-pitch');
  drag(pitch);
  pointer(pitch, 'pointerdown', 250, 100, 2);
  expect(fireEvent.touchMove(pitch, { touches: [{ clientX: 80, clientY: 100 }, {}] })).toBe(true);
  pointer(pitch, 'pointerup', 80);
  pointer(pitch, 'pointerup', 270, 100, 2);
  expect(change).not.toHaveBeenCalled();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

test('presentation fallback owns gestures even without the fullscreen API', () => {
  // Keep live fixture lookup pending: this regression exercises only the
  // real presentation wrapper and its input boundary, with the local dataset.
  const fetchBefore = global.fetch;
  global.fetch = jest.fn(() => new Promise<Response>(() => {}));
  try {
    const { change } = setup(<FixturesBoard onAsk={jest.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Presentar' }));
    const presentation = screen.getByLabelText(/Calendario en modo/);
    expect(presentation).toHaveAttribute('aria-hidden', 'false');
    drag(presentation);
    pointer(presentation, 'pointerup', 100);
    fireEvent.keyDown(presentation, { key: 'ArrowRight' });
    expect(change).not.toHaveBeenCalled();
  } finally {
    global.fetch = fetchBefore;
  }
});
