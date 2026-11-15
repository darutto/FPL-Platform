/**
 * @jest-environment jsdom
 *
 * The card hands the snapshot's `strip_axis` (the backend's axis from the observed role) to the
 * fixture strip; an older payload without it leaves the strip on the FPL fallback. Synthetic data.
 */
import { render } from '@testing-library/react';

import PlayerCard from '../components/intents/PlayerCard';
import { playerSnapshotOkResponse } from './fixtures/sample-responses';

const received: Array<Record<string, unknown>> = [];
jest.mock('../components/intents/PlayerFixtureStrip', () => ({
  PlayerFixtureStrip: (props: Record<string, unknown>) => {
    received.push(props);
    return null;
  },
}));

beforeEach(() => {
  received.length = 0;
});

const base = playerSnapshotOkResponse.player_snapshot!;

test('payload axis goes to the strip', () => {
  render(<PlayerCard data={{ ...base, position: 'MID', strip_axis: 'defence' }} />);
  expect(received.at(-1)).toMatchObject({ position: 'MID', observedAxis: 'defence' });
});

test('no strip_axis in the payload: the strip gets null and goes by FPL position', () => {
  const { strip_axis: _drop, ...older } = { ...base, strip_axis: undefined };
  render(<PlayerCard data={{ ...older, position: 'DEF' }} />);
  expect(received.at(-1)).toMatchObject({ position: 'DEF', observedAxis: null });
});
