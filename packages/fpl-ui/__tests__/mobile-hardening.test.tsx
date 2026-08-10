/**
 * @jest-environment jsdom
 *
 * Mobile hardening pass (Track E / final wave):
 *   - Name cells that sit inside a flex/grid item's child (not the item
 *     itself) must be `block` in addition to `truncate` — an inline `<span>`
 *     does not establish the block box `text-overflow: ellipsis` needs, so
 *     without `block` the name never actually truncates, just overflows the
 *     row visually. RankingTable, DifferentialTable, ResourceRankingTable,
 *     and TransferSuggestionCard's AltRow all had this bug; this file pins
 *     the fix so it can't silently regress.
 *   - Header rows (CaptainCard, ChipCard, FixtureRunTable,
 *     DefensiveZonesCard) get min-w-0 on the text side and flex-shrink-0 on
 *     pills, so a long name can't push a badge out of the 360px card.
 *
 * Not chasing pixels here — jsdom doesn't lay out text, so these assertions
 * are class-presence checks, not visual truncation checks.
 */
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import RankingTable from '../components/intents/RankingTable';
import DifferentialTable from '../components/intents/DifferentialTable';
import ResourceRankingTable from '../components/intents/ResourceRankingTable';
import TransferSuggestionCard from '../components/intents/TransferSuggestionCard';
import CaptainCard from '../components/intents/CaptainCard';
import ChipCard from '../components/intents/ChipCard';
import FixtureRunTable from '../components/intents/FixtureRunTable';
import PlayerCard from '../components/intents/PlayerCard';
import {
  rankingOkResponse,
  differentialOkResponse,
  transferSuggestionOkResponse,
  playerSnapshotOkResponse,
} from './fixtures/sample-responses';
import type { CaptainScoreMeta, ChipAdviceMeta, FixtureRunMeta, ResourceRows } from '../lib/types';

describe('RankingTable — name cell truncation', () => {
  test('web_name span is block + truncate (not bare inline truncate)', () => {
    render(<RankingTable data={rankingOkResponse.captain_ranking!} />);
    const name = screen.getByText('Haaland');
    expect(name.className).toEqual(expect.stringContaining('block'));
    expect(name.className).toEqual(expect.stringContaining('truncate'));
    // The row wrapper must allow the name column to shrink below content size.
    expect(name.parentElement?.className).toEqual(expect.stringContaining('min-w-0'));
  });
});

describe('DifferentialTable — name cell truncation', () => {
  test('web_name span is block + truncate', () => {
    render(<DifferentialTable data={differentialOkResponse.differential!} />);
    const name = screen.getByText('Palmer');
    expect(name.className).toEqual(expect.stringContaining('block'));
    expect(name.className).toEqual(expect.stringContaining('truncate'));
  });
});

describe('PlayerCard — name cell truncation', () => {
  test('web_name span is block + truncate, header row allows shrink', () => {
    render(<PlayerCard data={playerSnapshotOkResponse.player_snapshot!} />);
    const name = screen.getByText('Haaland');
    expect(name.className).toEqual(expect.stringContaining('block'));
    expect(name.className).toEqual(expect.stringContaining('truncate'));
    expect(name.parentElement?.className).toEqual(expect.stringContaining('min-w-0'));
  });
});

describe('ResourceRankingTable — name cell truncation', () => {
  test('web_name span is block + truncate', () => {
    const data: ResourceRows = {
      resource: 'top_form',
      title: 'Mejor forma',
      columns: ['#', 'Jugador', 'Equipo', 'Pos', 'Forma'],
      rows: [
        { web_name: 'Konstantinos Mavropanos', team_short: 'WHU', position: 'DEF', value: 8.4 },
      ],
    };
    render(<ResourceRankingTable data={data} />);
    const name = screen.getByText('Konstantinos Mavropanos');
    expect(name.className).toEqual(expect.stringContaining('block'));
    expect(name.className).toEqual(expect.stringContaining('truncate'));
  });
});

describe('TransferSuggestionCard — alternative row name truncation', () => {
  test('alt row web_name span is block + truncate', () => {
    render(<TransferSuggestionCard data={transferSuggestionOkResponse.transfer_suggestion!} />);
    // First pick renders in the hero block (not truncate-block pattern);
    // alternatives use the AltRow grid — assert on one of those instead.
    const picks = transferSuggestionOkResponse.transfer_suggestion!.picks;
    if (picks.length > 1) {
      const altName = screen.getByText(picks[1].web_name);
      expect(altName.className).toEqual(expect.stringContaining('block'));
      expect(altName.className).toEqual(expect.stringContaining('truncate'));
    }
  });
});

describe('CaptainCard — header row shrinks around the tier badge', () => {
  test('name container is min-w-0, name is truncate, badge is flex-shrink-0', () => {
    const data: CaptainScoreMeta = {
      web_name: 'Christian Eriksen-Thorvaldsen',
      team_short: 'MUN',
      captain_score: 55.2,
      tier: 'safe',
      role_bonus: 0,
      set_piece_notes: [],
    };
    render(<CaptainCard data={data} />);
    const name = screen.getByText(data.web_name);
    expect(name.className).toEqual(expect.stringContaining('truncate'));
    expect(name.parentElement?.className).toEqual(expect.stringContaining('min-w-0'));
    const badge = screen.getByText('Favorito');
    expect(badge.className).toEqual(expect.stringContaining('flex-shrink-0'));
  });
});

describe('ChipCard — header row shrinks around the recommendation pill', () => {
  test('chip label wrapper is min-w-0, label truncates', () => {
    const data: ChipAdviceMeta = {
      chip: 'triple_captain',
      recommendation: 'conditions_favorable',
      gw: 12,
      signal_value: 88.4,
      signal_label: 'Fixture DGW',
      chip_unavailable: false,
    };
    render(<ChipCard data={data} />);
    const label = screen.getByText('Triple Capitán');
    expect(label.className).toEqual(expect.stringContaining('truncate'));
    expect(label.parentElement?.className).toEqual(expect.stringContaining('min-w-0'));
  });
});

describe('FixtureRunTable — header row name truncates', () => {
  test('web_name span carries min-w-0 + truncate', () => {
    const data: FixtureRunMeta = {
      web_name: 'Konstantinos Mavropanos',
      team_short: 'WHU',
      position: 'DEF',
      horizon: 5,
      current_gameweek: 10,
      fixtures: [
        { gameweek: 11, opponent_short: 'ARS', is_home: true, difficulty: 4 },
      ],
    };
    render(<FixtureRunTable data={data} />);
    const name = screen.getByText(data.web_name);
    expect(name.className).toEqual(expect.stringContaining('truncate'));
    expect(name.className).toEqual(expect.stringContaining('min-w-0'));
  });
});
