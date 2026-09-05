/**
 * @jest-environment jsdom
 *
 * RankingTable — an open pool and the lists it actually shows.
 *
 * Nobody is excluded for playing in defence any more, so the card has to say
 * which position each row is, show the short lists the backend named, and be
 * honest when no lightly-owned player is worth suggesting.
 */
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import RankingTable from '../components/intents/RankingTable';
import type { RankedCaptainEntry, RankingPresentation } from '../lib/types';

function entry(
  overrides: Partial<RankedCaptainEntry> & { rank: number; player_id: number },
): RankedCaptainEntry {
  return {
    web_name: `P${overrides.player_id}`,
    team_short: 'BHA',
    captain_score: 90 - overrides.rank,
    tier: 'safe',
    role_bonus: 0,
    set_piece_notes: [],
    ...overrides,
  };
}

// Eight scored players, so both lists have more behind them than they show.
const data: RankedCaptainEntry[] = [
  entry({ rank: 1, player_id: 1, web_name: 'DeCuyper', position: 'DEF', owned: true }),
  entry({ rank: 2, player_id: 2, web_name: 'Raya', position: 'GKP', owned: true }),
  entry({ rank: 3, player_id: 3, web_name: 'Haaland', position: 'FWD', owned: true }),
  entry({ rank: 4, player_id: 4, web_name: 'Palmer', position: 'MID', owned: true }),
  entry({ rank: 5, player_id: 5, web_name: 'Saka', position: 'MID' }),
  entry({ rank: 6, player_id: 6, web_name: 'Gakpo', position: 'MID' }),
  entry({ rank: 7, player_id: 7, web_name: 'Mbeumo', position: 'FWD' }),
  entry({ rank: 8, player_id: 8, web_name: 'Rogers', position: 'MID', selected_by_percent: 1.2 }),
];

const presentation: RankingPresentation = {
  owned_top: [1, 2, 3],
  owned_hipster: { player_id: 4, selected_by_percent: 3.4, reason: null },
  global_top: [1, 2, 3, 4, 5],
  global_hipster: { player_id: 8, selected_by_percent: 1.2, reason: null },
};

describe('RankingTable — open pool', () => {
  test('a keeper and a defender are shown with their position', () => {
    render(<RankingTable data={data} squadSource="connected" presentation={presentation} />);

    // Without the position a keeper is indistinguishable from a forward.
    expect(screen.getAllByText('BHA · GKP').length).toBeGreaterThan(0);
    expect(screen.getAllByText('BHA · DEF').length).toBeGreaterThan(0);
  });

  test('shows 3 + 1 owned and 5 + 1 global without dropping anyone from the data', () => {
    render(<RankingTable data={data} squadSource="connected" presentation={presentation} />);

    // The hipster is an extra name, not one of the three.
    expect(screen.getAllByText('Palmer')).toHaveLength(2); // owned hipster + global top
    expect(screen.getAllByText('Rogers')).toHaveLength(1); // global hipster only
    // Someone scored but not named by either list simply is not shown.
    expect(screen.queryByText('Mbeumo')).not.toBeInTheDocument();
    expect(screen.getAllByText(/lo lleva el/)).toHaveLength(2);
  });

  test('says there is no hipster rather than offering a weak one', () => {
    render(
      <RankingTable
        data={data}
        squadSource="connected"
        presentation={{
          ...presentation,
          global_hipster: { player_id: null, reason: 'no_candidate_clears_floor' },
        }}
      />,
    );

    expect(
      screen.getByText('Sin hipster esta jornada: nadie de poca propiedad llega al mínimo.'),
    ).toBeInTheDocument();
  });

  test('falls back to the old shape when no presentation is sent', () => {
    render(<RankingTable data={data} squadSource="connected" />);

    expect(screen.getByText('Mbeumo')).toBeInTheDocument();
    expect(screen.queryByText(/Sin hipster/)).not.toBeInTheDocument();
  });
});
