/**
 * @jest-environment jsdom
 *
 * @xa renders like @xg: its own accent and the shared ranking card. Synthetic rows.
 */
import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import ResourceRankingTable from '../components/intents/ResourceRankingTable';
import { RESOURCE_ACCENT } from '@/lib/theme';

test('the xA ranking has its own accent entry and renders its title and values', () => {
  expect(RESOURCE_ACCENT.top_xa).toBe('coral');
  render(
    <ResourceRankingTable
      data={{
        resource: 'top_xa',
        title: 'Top Expected Assists',
        columns: ['web_name', 'team_short', 'position', 'value'],
        rows: [{ web_name: 'Uno', team_short: 'AAA', position: 'MID', value: 3.5 }],
      }}
    />,
  );
  expect(screen.getByText('Top Expected Assists')).toBeInTheDocument();
  expect(screen.getByText('3.50')).toBeInTheDocument();
});
