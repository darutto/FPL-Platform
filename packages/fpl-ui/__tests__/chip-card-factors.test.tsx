/**
 * @jest-environment jsdom
 *
 * ChipCard — the factors, not just the two numbers.
 *
 * The card used to say "captain score · Haaland 71.1 / Mejor disponible:
 * B.Fernandes" and nothing else, which is the exact complaint this work
 * exists to answer: a reader could not see that Haaland plays every minute
 * and takes the penalties.
 */
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import ChipCard from '../components/intents/ChipCard';
import type { ChipAdviceMeta } from '../lib/types';

const tc: ChipAdviceMeta = {
  chip: 'triple_captain',
  recommendation: 'conditions_marginal',
  gw: 3,
  signal_value: 71.1,
  signal_label: 'captain score',
  top_player: 'B.Fernandes',
  evaluated_player: 'Haaland',
  chip_unavailable: false,
  evaluated_factors: ['jugó 180 de 180 minutos posibles, 2 titularidades', 'lanza los penaltis'],
  top_factors: ['jugó 174 de 180 minutos posibles, 2 titularidades', 'lanza los penaltis'],
  risk_note: 'El triple capitán multiplica lo que pase, en los dos sentidos.',
};

describe('ChipCard — visible factors', () => {
  test('names the asked-about player’s minutes and penalties', () => {
    render(<ChipCard data={tc} />);

    expect(
      screen.getByText(/jugó 180 de 180 minutos posibles, 2 titularidades · lanza los penaltis/),
    ).toBeInTheDocument();
  });

  test('says the chip multiplies the downside too', () => {
    render(<ChipCard data={tc} />);
    expect(screen.getByText(/en los dos sentidos/)).toBeInTheDocument();
  });

  test('gives the recommended alternative its factors as well', () => {
    render(<ChipCard data={tc} />);
    // Otherwise "better available" is just another bare name.
    expect(screen.getByText(/Mejor disponible:/)).toHaveTextContent('lanza los penaltis');
  });

  test('a chip with no factors renders exactly as before', () => {
    const freeHit: ChipAdviceMeta = {
      chip: 'free_hit',
      recommendation: 'missing_context',
      gw: 3,
      signal_value: null,
      signal_label: null,
      top_player: null,
      evaluated_player: null,
      chip_unavailable: false,
    };

    render(<ChipCard data={freeHit} />);

    expect(screen.getByText('Ficha Libre')).toBeInTheDocument();
    expect(screen.queryByText(/minutos posibles/)).not.toBeInTheDocument();
    expect(screen.queryByText(/dos sentidos/)).not.toBeInTheDocument();
  });
});
