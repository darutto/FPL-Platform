/**
 * @jest-environment jsdom
 *
 * The factors a captain score is made of, shown instead of implied.
 *
 * The complaint this answers: someone asking about a player read "your pick
 * 71.1, best available 82.2" and could not see that his pick plays every
 * minute and takes the penalties.
 */
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import RankingTable from '../components/intents/RankingTable';
import { contradictionNote, factorPhrases } from '../lib/captain-factors';
import type { RankedCaptainEntry } from '../lib/types';

function entry(over: Partial<RankedCaptainEntry> & { rank: number }): RankedCaptainEntry {
  return {
    web_name: 'Jugador',
    team_short: 'MCI',
    captain_score: 70,
    tier: 'safe',
    role_bonus: 0,
    set_piece_notes: [],
    player_id: over.rank,
    position: 'FWD',
    ...over,
  };
}

const partial = entry({
  rank: 1,
  web_name: 'Cherki',
  captain_score: 85.7,
  minutes_context: {
    minutes_played: 108,
    minutes_available: 180,
    starts: 1,
    participation_percent: 60,
    degraded: false,
    degradation_reason: null,
  },
  penalties_order: null,
});

const full = entry({
  rank: 2,
  web_name: 'Haaland',
  captain_score: 71.1,
  minutes_context: {
    minutes_played: 180,
    minutes_available: 180,
    starts: 2,
    participation_percent: 100,
    degraded: false,
    degradation_reason: null,
  },
  penalties_order: 1,
});

describe('visible captaincy factors', () => {
  test('names minutes and penalties in plain language', () => {
    expect(factorPhrases(partial)).toEqual([
      'jugó 108 de 180 minutos posibles, 1 titularidad',
    ]);
    expect(factorPhrases(full)).toEqual([
      'jugó 180 de 180 minutos posibles, 2 titularidades',
      'lanza los penaltis',
    ]);
  });

  test('never states a weight or a threshold', () => {
    const everything = [
      ...factorPhrases(full),
      contradictionNote(full, [partial, full]) ?? '',
    ].join(' ');

    // Naming the factor informs; naming its coefficient publishes the model.
    expect(everything).not.toMatch(/\d+\s*%\s*(del|de la|of the)?\s*(cálculo|calculation|puntuación)/i);
    expect(everything).not.toMatch(/\b(40|30|20|10)\s*%/);
    expect(everything).toMatch(/forma reciente/);
  });

  test('says so when the order and the factors disagree', () => {
    // Haaland plays every minute and takes the penalties, yet ranks below a
    // player at 60% of the available minutes.
    expect(contradictionNote(full, [partial, full])).toMatch(/aun así puntúa por debajo/);
  });

  test('stays quiet when the order and the factors agree', () => {
    // Reverse the ranks: now the full participant is on top, no surprise.
    const onTop = { ...full, rank: 1 };
    const below = { ...partial, rank: 2 };
    expect(contradictionNote(onTop, [onTop, below])).toBeNull();
  });

  test('shows both on the card, and the note only on the row it is about', () => {
    render(<RankingTable data={[partial, full]} />);

    expect(
      screen.getByText('jugó 108 de 180 minutos posibles, 1 titularidad'),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/jugó 180 de 180 minutos posibles, 2 titularidades · lanza los penaltis/),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/aun así puntúa por debajo/)).toHaveLength(1);
  });

  test('shows nothing rather than a blank when participation was not derived', () => {
    const degraded = entry({
      rank: 1,
      web_name: 'Sin datos',
      minutes_context: {
        minutes_played: 90,
        minutes_available: null,
        starts: 1,
        participation_percent: null,
        degraded: true,
        degradation_reason: 'missing_official_fixtures',
      },
    });

    expect(factorPhrases(degraded)).toEqual([]);
    render(<RankingTable data={[degraded]} />);
    expect(screen.queryByText(/minutos posibles/)).not.toBeInTheDocument();
  });
});

describe('a short list must not cut the row its note was written for', () => {
  // The merged product review found this: with 3+1 / 5+1 lists, Haaland fell
  // outside the shown five, so the note built to stop exactly that misreading
  // rendered nowhere.
  const filler = (rank: number) =>
    entry({
      rank,
      web_name: `Relleno${rank}`,
      player_id: 100 + rank,
      captain_score: 90 - rank,
      minutes_context: {
        minutes_played: 60,
        minutes_available: 180,
        starts: 0,
        participation_percent: 33,
        degraded: false,
        degradation_reason: null,
      },
    });

  const sunk = { ...full, rank: 8, player_id: 999 };
  const data = [1, 2, 3, 4, 5, 6, 7].map(filler).concat(sunk);
  const presentation = {
    owned_top: [],
    owned_hipster: { player_id: null, reason: 'no_candidate_clears_floor' as const },
    global_top: [101, 102, 103, 104, 105],
    global_hipster: { player_id: null, reason: 'no_candidate_clears_floor' as const },
  };

  test('names the cut player and shows his note', () => {
    render(<RankingTable data={data} squadSource="connected" presentation={presentation} />);

    expect(screen.getByText('Conviene saber')).toBeInTheDocument();
    expect(screen.getByText('Haaland')).toBeInTheDocument();
    expect(screen.getByText(/aun así puntúa por debajo/)).toBeInTheDocument();
  });

  test('adds nothing when every note-carrying row is already shown', () => {
    render(
      <RankingTable
        data={data}
        squadSource="connected"
        presentation={{ ...presentation, global_top: [101, 102, 103, 104, 999] }}
      />,
    );

    expect(screen.queryByText('Conviene saber')).not.toBeInTheDocument();
  });
});
