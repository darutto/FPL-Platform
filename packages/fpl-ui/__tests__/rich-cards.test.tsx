/**
 * @jest-environment jsdom
 *
 * Rich "Hi-Fi" card tests (Track C):
 *   - lib/copy.ts: no-imperative rule (verdict/CTA templates carry no banned
 *     buy/sell command verbs), and verdict wording per recommendation.
 *   - ComparisonCard (rewritten): verdict headline, PICK winner, big scores,
 *     lead strip, reasons cap, null-context fallback.
 *   - TransferCard (rewritten): 3-block shape — OUT pill, verdict, deltas,
 *     honest CTA link; all TransferMeta data preserved.
 *   - TransferSuggestionCard (new): hero pick + ranked alternatives.
 */
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import {
  comparisonVerdict,
  comparisonLead,
  transferVerdict,
  suggestionVerdict,
  TRANSFER_CTA_URL,
  TRANSFER_CTA_LABEL,
} from '../lib/copy';
import ComparisonCard, { playerContext } from '../components/intents/ComparisonCard';
import TransferCard, { formatScoreDelta, formatPriceDelta } from '../components/intents/TransferCard';
import TransferSuggestionCard, { buildScope, formatPrice } from '../components/intents/TransferSuggestionCard';
import {
  comparisonOkResponse,
  comparisonTiedResponse,
  comparisonNoContextResponse,
  transferOkResponse,
  transferHoldResponse,
  transferSuggestionOkResponse,
} from './fixtures/sample-responses';
import type { TransferRecommendation } from '../lib/types';

// ---------------------------------------------------------------------------
// lib/copy — no-imperative rule (opportunity framing)
// ---------------------------------------------------------------------------

describe('lib/copy — no banned imperative verbs', () => {
  // Banned buy/sell command verbs (Spanish imperative forms).
  // See packages/fpl-tactical/CONTRACT.md:73 — opportunity framing.
  const BANNED = /\b(mete|meté|compra|vende|ficha|fiche|fichá)\b/i;

  const recs: TransferRecommendation[] = ['transfer_in', 'marginal_transfer_in', 'hold'];

  const allStrings: string[] = [
    comparisonVerdict('Haaland'),
    comparisonVerdict(null),
    comparisonLead('Haaland', 6.8),
    suggestionVerdict('Palmer'),
    TRANSFER_CTA_LABEL,
    TRANSFER_CTA_URL,
    ...recs.map((r) => transferVerdict(r, 'Salah')),
  ];

  test.each(allStrings)('template "%s" has no imperative verb', (s) => {
    expect(s).not.toMatch(BANNED);
  });

  test('winner comparison verdict uses the "mejor selección" pattern', () => {
    expect(comparisonVerdict('Haaland')).toBe('La mejor selección es Haaland.');
  });

  test('tied comparison verdict is neutral', () => {
    expect(comparisonVerdict(null)).toBe('Empate técnico.');
  });

  test('transfer_in verdict is a selection, not a command', () => {
    expect(transferVerdict('transfer_in', 'Salah')).toBe('La mejor selección es Salah.');
  });

  test('hold verdict frames holding as the read', () => {
    expect(transferVerdict('hold', 'Salah')).toBe('Mantener es la lectura correcta.');
  });

  test('CTA points at the official FPL transfers page', () => {
    expect(TRANSFER_CTA_URL).toBe('https://fantasy.premierleague.com/transfers');
  });
});

// ---------------------------------------------------------------------------
// ComparisonCard
// ---------------------------------------------------------------------------

describe('ComparisonCard', () => {
  test('renders verdict headline with winner and both big scores', () => {
    render(<ComparisonCard data={comparisonOkResponse.comparison!} />);
    expect(screen.getByText(/La mejor selección es/)).toBeInTheDocument();
    // winner appears in headline, option col, and lead strip
    expect(screen.getAllByText('Haaland').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('83.5')).toBeInTheDocument();
    expect(screen.getByText('76.7')).toBeInTheDocument();
    expect(screen.getByText('Pick')).toBeInTheDocument();
    expect(screen.getByText(/lidera por/)).toBeInTheDocument();
  });

  test('tied comparison shows neutral verdict and no PICK tab', () => {
    render(<ComparisonCard data={comparisonTiedResponse.comparison!} />);
    expect(screen.getByText('Empate técnico.')).toBeInTheDocument();
    expect(screen.queryByText('Pick')).not.toBeInTheDocument();
  });

  test('null player context still renders verdict (summary-only fallback)', () => {
    render(<ComparisonCard data={comparisonNoContextResponse.comparison!} />);
    expect(screen.getByText(/La mejor selección es/)).toBeInTheDocument();
    // no option columns → captain score numbers absent
    expect(screen.queryByText('83.5')).not.toBeInTheDocument();
  });

  test('caps reasons at 3', () => {
    const data = {
      ...comparisonOkResponse.comparison!,
      reasons: ['r1', 'r2', 'r3', 'r4', 'r5'],
    };
    render(<ComparisonCard data={data} />);
    expect(screen.getByText('r1')).toBeInTheDocument();
    expect(screen.getByText('r3')).toBeInTheDocument();
    expect(screen.queryByText('r4')).not.toBeInTheDocument();
  });

  test('playerContext helper: home/away/unknown', () => {
    expect(playerContext({ ...comparisonOkResponse.comparison!.player_a!, is_home: true })).toBe('FWD · Local');
    expect(playerContext({ ...comparisonOkResponse.comparison!.player_a!, is_home: false })).toBe('FWD · Visitante');
    expect(playerContext({ ...comparisonOkResponse.comparison!.player_a!, is_home: null })).toBe('FWD');
  });

  test('renders the stat comparison table below the verdict when present', () => {
    render(<ComparisonCard data={comparisonOkResponse.comparison!} />);
    expect(screen.getByText('Forma')).toBeInTheDocument();
    expect(screen.getByText('Goles')).toBeInTheDocument();
  });

  test('renders nothing extra when stat_comparison is null', () => {
    render(<ComparisonCard data={comparisonTiedResponse.comparison!} />);
    expect(screen.queryByText('Forma')).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// TransferCard
// ---------------------------------------------------------------------------

describe('TransferCard', () => {
  test('renders 3-block shape: OUT pill, verdict, deltas, CTA', () => {
    render(<TransferCard data={transferOkResponse.transfer!} />);
    expect(screen.getByText('← Saca')).toBeInTheDocument();
    expect(screen.getByText('Saka')).toBeInTheDocument(); // player_out
    expect(screen.getByText(/La mejor selección es/)).toBeInTheDocument();
    expect(screen.getByText('+7.5')).toBeInTheDocument(); // score_delta hero
    expect(screen.getByText('+£1.0m')).toBeInTheDocument(); // price_delta
    const cta = screen.getByRole('link', { name: /Hacer la transferencia en FPL/ });
    expect(cta).toHaveAttribute('href', TRANSFER_CTA_URL);
    expect(cta).toHaveAttribute('target', '_blank');
  });

  test('preserves warning banners and hold verdict semantics', () => {
    render(<TransferCard data={transferHoldResponse.transfer!} />);
    expect(screen.getByText('Mantener es la lectura correcta.')).toBeInTheDocument();
    expect(screen.getByText(/Supera tu presupuesto/)).toBeInTheDocument();
    expect(screen.getByText('-1.2')).toBeInTheDocument(); // negative delta shown
  });

  test('formatScoreDelta / formatPriceDelta helpers', () => {
    expect(formatScoreDelta(7.5)).toBe('+7.5');
    expect(formatScoreDelta(-1.2)).toBe('-1.2');
    expect(formatPriceDelta(10)).toBe('+£1.0m');
    expect(formatPriceDelta(-5)).toBe('-£0.5m');
    expect(formatPriceDelta(0)).toBe('£0.0m');
  });
});

// ---------------------------------------------------------------------------
// TransferSuggestionCard
// ---------------------------------------------------------------------------

describe('TransferSuggestionCard', () => {
  test('renders hero pick + verdict + ranked alternatives', () => {
    render(<TransferSuggestionCard data={transferSuggestionOkResponse.transfer_suggestion!} />);
    expect(screen.getByText(/La mejor selección es/)).toBeInTheDocument();
    expect(screen.getByText('Pick')).toBeInTheDocument();
    // hero composite score
    expect(screen.getByText('82.1')).toBeInTheDocument();
    // alternatives
    expect(screen.getByText('Saka')).toBeInTheDocument();
    expect(screen.getByText('Gordon')).toBeInTheDocument();
    expect(screen.getByText('Otras opciones')).toBeInTheDocument();
  });

  test('renders null (nothing) when picks empty', () => {
    const { container } = render(
      <TransferSuggestionCard
        data={{ ...transferSuggestionOkResponse.transfer_suggestion!, picks: [] }}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  test('buildScope + formatPrice helpers', () => {
    expect(formatPrice(8.5)).toBe('£8.5m');
    expect(buildScope({ position_label: 'Mediocampistas', team_short: null, team_name: null, max_price: 9.5 })).toBe(
      'Mediocampistas · ≤ £9.5m',
    );
    expect(buildScope({ position_label: 'Delanteros', team_short: 'ARS', team_name: 'Arsenal', max_price: null })).toBe(
      'Arsenal · Delanteros',
    );
  });
});
