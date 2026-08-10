/**
 * @jest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import PlayerCard from '../components/intents/PlayerCard';
import {
  playerSnapshotOkResponse,
  playerSnapshotDoubtfulResponse,
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
