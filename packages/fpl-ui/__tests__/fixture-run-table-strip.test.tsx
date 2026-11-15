/**
 * @jest-environment jsdom
 *
 * `/calendarios <jugador>` (player_fixture_run) draws the player card's fixture strip, the
 * /fixtures tiles, not its own FDR chips. The payload has no `strip_axis`: the strip goes by
 * FPL position. Synthetic data.
 */
import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';

import FixtureRunTable from '../components/intents/FixtureRunTable';
import { fixtureRunOkResponse } from './fixtures/sample-responses';

const received: Array<Record<string, unknown>> = [];
jest.mock('../components/intents/PlayerFixtureStrip', () => ({
  PlayerFixtureStrip: (props: Record<string, unknown>) => {
    received.push(props);
    return <div data-testid="player-fixture-strip" />;
  },
}));

beforeEach(() => {
  received.length = 0;
});

const data = fixtureRunOkResponse.fixture_run!;

test('the run hands its fixtures, team and position to the card strip, no observed axis', () => {
  render(<FixtureRunTable data={data} />);
  expect(screen.getByTestId('player-fixture-strip')).toBeInTheDocument();
  expect(received).toHaveLength(1);
  expect(received[0]).toMatchObject({ fixtures: data.fixtures, teamShort: data.team_short, position: data.position });
  expect(received[0].observedAxis ?? null).toBeNull();
});

test('the old chip legend is gone; the header stays', () => {
  render(<FixtureRunTable data={data} />);
  expect(screen.queryByText('FDR:')).not.toBeInTheDocument();
  expect(screen.getByText(data.web_name)).toBeInTheDocument();
  expect(screen.getByText(data.team_short)).toBeInTheDocument();
});

test('no fixtures: nothing rendered, no strip', () => {
  const { container } = render(<FixtureRunTable data={{ ...data, fixtures: [] }} />);
  expect(container).toBeEmptyDOMElement();
  expect(received).toHaveLength(0);
});
