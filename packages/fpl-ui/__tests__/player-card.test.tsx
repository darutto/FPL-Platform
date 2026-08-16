/**
 * @jest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import PlayerCard from '../components/intents/PlayerCard';
import {
  playerSnapshotOkResponse,
  playerSnapshotDoubtfulResponse,
  playerSnapshotNoFixturesResponse,
} from './fixtures/sample-responses';

describe('PlayerCard — available player', () => {
  const data = playerSnapshotOkResponse.player_snapshot!;

  test('renders name, price, ownership, and total points', () => {
    render(<PlayerCard data={data} />);
    expect(screen.getByText('Haaland')).toBeInTheDocument();
    expect(screen.getByText('£15.5m')).toBeInTheDocument();
    expect(screen.getByText('74.2%')).toBeInTheDocument();
    expect(screen.getByText('239')).toBeInTheDocument();
  });

  test('renders the available-status badge with the good tone class', () => {
    render(<PlayerCard data={data} />);
    const badge = screen.getByText('Available');
    expect(badge.className).toEqual(expect.stringContaining('turquoise'));
  });

  test('does not render a news line when available', () => {
    render(<PlayerCard data={data} />);
    expect(screen.queryByText(/tobillo/)).not.toBeInTheDocument();
  });

  test('renders the next-fixture strip', () => {
    render(<PlayerCard data={data} />);
    expect(screen.getByText('GW29')).toBeInTheDocument();
    expect(screen.getByText(/LIV/)).toBeInTheDocument();
    expect(screen.getByText('GW30')).toBeInTheDocument();
  });

  test('renders season totals and aligned per-90 metrics including DC', () => {
    render(<PlayerCard data={data} />);
    for (const label of ['xG', 'xA', 'xGI', 'ICT', 'DC']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    for (const label of ['xG/90', 'xA/90', 'xGI/90', 'ICT/90', 'DC/90']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText('25.50')).toBeInTheDocument();
    expect(screen.getByText('0.78')).toBeInTheDocument();
    expect(screen.getByText('116')).toBeInTheDocument();
    expect(screen.getByText('3.54')).toBeInTheDocument();
  });

  test('derives rates without crashing against an older API response', () => {
    const legacyData = {
      ...data,
      expected_goals_per_90: undefined,
      expected_assists_per_90: undefined,
      expected_goal_involvements_per_90: undefined,
      ict_index_per_90: undefined,
      defensive_contribution: undefined,
      defensive_contribution_per_90: undefined,
    };
    render(<PlayerCard data={legacyData} />);
    expect(screen.getByText('0.78')).toBeInTheDocument();
    expect(screen.getByText('9.21')).toBeInTheDocument();
    expect(screen.getByText('0')).toBeInTheDocument();
    expect(screen.getByText('0.00')).toBeInTheDocument();
  });
});

describe('PlayerCard — no fixture coverage', () => {
  test('omits the fixture strip when fixtures is empty', () => {
    render(<PlayerCard data={playerSnapshotNoFixturesResponse.player_snapshot!} />);
    expect(screen.queryByText(/^GW/)).not.toBeInTheDocument();
  });
});

describe('PlayerCard — doubtful player', () => {
  const data = playerSnapshotDoubtfulResponse.player_snapshot!;

  test('renders the doubtful-status badge with the warn tone class', () => {
    render(<PlayerCard data={data} />);
    const badge = screen.getByText('Doubtful');
    expect(badge.className).toEqual(expect.stringContaining('gold'));
  });

  test('renders the news line', () => {
    render(<PlayerCard data={data} />);
    expect(screen.getByText(/tobillo/)).toBeInTheDocument();
  });
});
