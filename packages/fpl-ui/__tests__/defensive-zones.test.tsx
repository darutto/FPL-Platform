/**
 * @jest-environment jsdom
 *
 * Defensive Zones card tests (T4b).
 *
 * Covers:
 *   - pure helpers in lib/defensive-zones.ts (formatting, level→class maps,
 *     zone-pill labels, verdict splitting, graceful sub-line degradation)
 *   - selectIntentView gating for the zonal_opportunity intent
 *   - DefensiveZonesCard rendering (jsdom + Testing Library): header,
 *     3 zone readings with correct opportunity coding, exploiter table,
 *     penalty footer, IA badge, empty-exploiters fallback
 */
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import {
  LEVEL_PILL_LABEL,
  LEVEL_TEXT_CLASS,
  ZONE_SHADE_HEX,
  ZONE_SHADE_MAX_OPACITY,
  zoneShadeOpacity,
  isAverageZone,
  formatDeltaFine,
  formatPct,
  formatFit,
  formatPenalty,
  rankOpacity,
  zonePillLabel,
  levelForZone,
  positionEs,
  exploiterSub,
  splitVerdict,
} from '../lib/defensive-zones';
import { selectIntentView } from '../lib/intent-renderer';
import DefensiveZonesCard from '../components/intents/DefensiveZonesCard';
import type {
  AskResponse,
  DefensiveZonesMeta,
  ZonalDataProvenance,
  ZonalTeamFilter,
} from '../lib/types';

// ---------------------------------------------------------------------------
// Fixture — mirrors the real Crystal Palace payload with the corrected
// flank handedness (2026-07-09): Palace's weak band is the attacker's
// RIGHT flank — where Saka/Bowen actually attack — and the verdict speaks
// the same attacker/opportunity frame.
// ---------------------------------------------------------------------------

const palaceMeta: DefensiveZonesMeta = {
  opponent: 'Crystal Palace',
  weakness_label: 'Débil dentro del área',
  verdict:
    'Ataca a Crystal Palace por la derecha dentro del área — concede un ' +
    '+70% sobre un equipo medio ahí.',
  zones: [
    { lateral: 'left', pct_over_avg: -31.7, opportunity_level: 'cool' },
    { lateral: 'central', pct_over_avg: 1.5, opportunity_level: 'warm' },
    { lateral: 'right', pct_over_avg: 69.8, opportunity_level: 'opp' },
  ],
  exploiters: [
    { rank: 1, web_name: 'Saka', team_short: 'ARS', position: 'MID', zone: 'in-box / right', fit_score: 10.0 },
    { rank: 2, web_name: 'Bowen', team_short: 'WHU', position: 'FWD', zone: 'in-box / right', fit_score: 9.5 },
    { rank: 3, web_name: 'Alejandro Jiménez', team_short: 'BOU', position: '', zone: 'in-box / right', fit_score: 3.2 },
  ],
  penalty_xga_per_game: 0.1402,
  ai_active: true,
};

// i74 season stamps — the card renders the backend's `label` verbatim so the
// card and the plain-text zonal answers cannot word the same fact differently.
const currentProvenance: ZonalDataProvenance = {
  season: '2026-2027',
  season_label: '2026-27',
  live_season: '2026-2027',
  is_current: true,
  status: 'current',
  label: 'Datos: temporada 2026-27',
  ingested_at: '2026-09-01T10:00:00Z',
  n_matches: 380,
  n_shots: 9524,
};

const staleProvenance: ZonalDataProvenance = {
  season: '2025-2026',
  season_label: '2025-26',
  live_season: '2026-2027',
  is_current: false,
  status: 'stale_season',
  label: '⚠ Datos de 2025-26, no de la temporada en curso (2026-27)',
  ingested_at: '2026-07-07T11:52:14Z',
  n_matches: 380,
  n_shots: 9524,
};

const zonalOkResponse: AskResponse = {
  final_text: 'Crystal Palace concede más de lo normal dentro del área…',
  outcome: 'ok',
  supported: true,
  intent: 'zonal_opportunity',
  review_passed: true,
  llm_used: true,
  orch_outcome: 'ok',
  captain: null,
  captain_ranking: null,
  comparison: null,
  transfer: null,
  chip: null,
  fixture_run: null,
  differential: null,
  sub_responses: null,
  zonal_opportunity: palaceMeta,
  degraded: false,
  resource_rows: null,
};

// ---------------------------------------------------------------------------
// Helpers — formatting
// ---------------------------------------------------------------------------

describe('formatPct', () => {
  test('real edge rounds to whole percent with +', () => {
    expect(formatPct(69.8)).toBe('+70%');
    expect(formatPct(1.5)).toBe('+2%');
    expect(formatPct(15)).toBe('+15%');
  });

  test('below +0.5% (incl. negatives) reads ≈ 0% — no negative opportunity', () => {
    expect(formatPct(0.4)).toBe('≈ 0%');
    expect(formatPct(0)).toBe('≈ 0%');
    expect(formatPct(-31.7)).toBe('≈ 0%');
  });
});

describe('formatFit / formatPenalty / rankOpacity', () => {
  test('fit renders one decimal', () => {
    expect(formatFit(10)).toBe('10.0');
    expect(formatFit(9.53)).toBe('9.5');
  });

  test('penalty renders three decimals', () => {
    expect(formatPenalty(0.1402)).toBe('0.140');
  });

  test('rank fade 1 → .85 → .72 then held', () => {
    expect(rankOpacity(1)).toBe(1);
    expect(rankOpacity(2)).toBe(0.85);
    expect(rankOpacity(3)).toBe(0.72);
    expect(rankOpacity(5)).toBe(0.72);
  });
});

// ---------------------------------------------------------------------------
// Helpers — zone naming + level lookup
// ---------------------------------------------------------------------------

describe('zonePillLabel', () => {
  test('in-box zones use short lateral labels', () => {
    expect(zonePillLabel('in-box / left')).toBe('Izq');
    expect(zonePillLabel('in-box / central')).toBe('Centro');
    expect(zonePillLabel('in-box / right')).toBe('Der');
  });

  test('edge-of-box zones are prefixed', () => {
    expect(zonePillLabel('edge-of-box / left')).toBe('Frontal izq');
  });

  test('unknown zone strings pass through untouched', () => {
    expect(zonePillLabel('weird')).toBe('weird');
  });
});

describe('levelForZone', () => {
  test('in-box zones read the matching cell level', () => {
    expect(levelForZone('in-box / right', palaceMeta.zones)).toBe('opp');
    expect(levelForZone('in-box / central', palaceMeta.zones)).toBe('warm');
    expect(levelForZone('in-box / left', palaceMeta.zones)).toBe('cool');
  });

  test('edge-of-box weak zones default to warm (not on the pitch view)', () => {
    expect(levelForZone('edge-of-box / left', palaceMeta.zones)).toBe('warm');
  });
});

describe('level maps encode opportunity, never coral', () => {
  test('opp is turquoise, warm gold, cool grey', () => {
    expect(LEVEL_TEXT_CLASS.opp).toContain('turquoise');
    expect(LEVEL_TEXT_CLASS.warm).toContain('gold');
    expect(LEVEL_TEXT_CLASS.cool).toContain('gray');
    for (const cls of Object.values(LEVEL_TEXT_CLASS)) {
      expect(cls).not.toContain('coral');
    }
  });

  test('pill copy matches the handoff', () => {
    expect(LEVEL_PILL_LABEL).toEqual({
      opp: 'tu mejor zona',
      warm: 'ventaja leve',
      cool: 'sin ventaja',
    });
  });

  test('shade hexes stay on the existing palette, never coral', () => {
    expect(ZONE_SHADE_HEX.opp).toBe('#02EBAE');
    expect(ZONE_SHADE_HEX.warm).toBe('#F2C572');
    expect(ZONE_SHADE_HEX.cool).toBe('#6b6975');
    for (const hex of Object.values(ZONE_SHADE_HEX)) {
      expect(hex.toLowerCase()).not.toBe('#ff6a4d');
    }
  });
});

// ---------------------------------------------------------------------------
// Helpers — zone shading
// ---------------------------------------------------------------------------

describe('zoneShadeOpacity', () => {
  test('scales with strength: stronger zone reads more saturated', () => {
    expect(zoneShadeOpacity('opp', 69.8)).toBeGreaterThan(
      zoneShadeOpacity('opp', 20),
    );
    expect(zoneShadeOpacity('opp', 20)).toBeGreaterThan(
      zoneShadeOpacity('warm', 1.5),
    );
    expect(zoneShadeOpacity('warm', 1.5)).toBeGreaterThan(
      zoneShadeOpacity('cool', -31.7),
    );
  });

  test('caps so an outlier never becomes a solid block', () => {
    expect(zoneShadeOpacity('opp', 400)).toBe(ZONE_SHADE_MAX_OPACITY);
    // light-tint tune (2026-07-09): the wash must stay well under half
    // opacity even at the cap
    expect(ZONE_SHADE_MAX_OPACITY).toBeLessThan(0.4);
  });

  test('cool zones are a flat faint wash regardless of pct', () => {
    expect(zoneShadeOpacity('cool', -31.7)).toBe(zoneShadeOpacity('cool', 0));
    expect(zoneShadeOpacity('cool', 0)).toBeLessThan(0.1);
  });

  test('negative pct never dims below the level floor', () => {
    expect(zoneShadeOpacity('warm', -5)).toBe(zoneShadeOpacity('warm', 0));
  });
});

describe('isAverageZone / formatDeltaFine', () => {
  test('below +0.5% (incl. negatives) is an average zone', () => {
    expect(isAverageZone(0.4)).toBe(true);
    expect(isAverageZone(-31.7)).toBe(true);
    expect(isAverageZone(0.5)).toBe(false);
    expect(isAverageZone(69.8)).toBe(false);
  });

  test('fine delta keeps one decimal, always signed', () => {
    expect(formatDeltaFine(69.8)).toBe('+69.8%');
    expect(formatDeltaFine(1.5)).toBe('+1.5%');
    expect(formatDeltaFine(-31.7)).toBe('−31.7%');
    expect(formatDeltaFine(0)).toBe('+0.0%');
  });
});

// ---------------------------------------------------------------------------
// Helpers — player sub-line + verdict split
// ---------------------------------------------------------------------------

describe('positionEs / exploiterSub', () => {
  test('FPL position codes map to Spanish', () => {
    expect(positionEs('MID')).toBe('MED');
    expect(positionEs('FWD')).toBe('DEL');
    expect(positionEs('GKP')).toBe('POR');
    expect(positionEs('DEF')).toBe('DEF');
  });

  test('sub-line joins with · and drops empty segments (join-miss degrade)', () => {
    expect(exploiterSub('ARS', 'MID')).toBe('ARS · MED');
    expect(exploiterSub('BOU', '')).toBe('BOU');
    expect(exploiterSub('', '')).toBe('');
  });
});

describe('splitVerdict', () => {
  test('bolds the +NN% token and keeps surrounding text', () => {
    const segs = splitVerdict(palaceMeta.verdict);
    const highlighted = segs.filter((s) => s.highlight);
    expect(highlighted).toHaveLength(1);
    expect(highlighted[0].text).toBe('+70%');
    expect(segs.map((s) => s.text).join('')).toBe(palaceMeta.verdict);
  });

  test('verdicts without a pct stay a single plain segment', () => {
    const segs = splitVerdict('Sin debilidad clara en ninguna zona.');
    expect(segs).toEqual([
      { text: 'Sin debilidad clara en ninguna zona.', highlight: false },
    ]);
  });
});

// ---------------------------------------------------------------------------
// selectIntentView gating
// ---------------------------------------------------------------------------

describe('selectIntentView — zonal_opportunity', () => {
  test('ok + meta with zones → defensive_zones', () => {
    expect(selectIntentView(zonalOkResponse)).toBe('defensive_zones');
  });

  test('non-ok outcome → null', () => {
    expect(
      selectIntentView({ ...zonalOkResponse, outcome: 'not_found' }),
    ).toBeNull();
  });

  test('ok but null meta → null (field CAN be null on ok turns)', () => {
    expect(
      selectIntentView({ ...zonalOkResponse, zonal_opportunity: null }),
    ).toBeNull();
  });

  test('ok but empty zones → null (never a half-empty card)', () => {
    expect(
      selectIntentView({
        ...zonalOkResponse,
        zonal_opportunity: { ...palaceMeta, zones: [] },
      }),
    ).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// DefensiveZonesCard rendering
// ---------------------------------------------------------------------------

describe('DefensiveZonesCard', () => {
  test('renders header: kicker, opponent, weakness pill', () => {
    render(<DefensiveZonesCard data={palaceMeta} />);
    expect(screen.getByText('Zonas que concede')).toBeInTheDocument();
    expect(screen.getByText('Crystal Palace')).toBeInTheDocument();
    expect(screen.getByText('Débil dentro del área')).toBeInTheDocument();
  });

  test('renders in-box readings: big pct + fine delta, ≈ media for average', () => {
    render(<DefensiveZonesCard data={palaceMeta} />);
    // +70% appears twice: bolded in the verdict AND inside the right region
    expect(screen.getAllByText('+70%').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('+69.8%')).toBeInTheDocument();
    expect(screen.getByText('+2%')).toBeInTheDocument();
    expect(screen.getByText('+1.5%')).toBeInTheDocument();
    // average (left) zone: muted '≈ media', no numbers at all
    expect(screen.getByText('≈ media')).toBeInTheDocument();
    expect(screen.queryByText('≈ 0%')).not.toBeInTheDocument();
    expect(screen.queryByText('−31.7%')).not.toBeInTheDocument();
  });

  test('readings row keeps labels + pills but no duplicated numbers', () => {
    render(<DefensiveZonesCard data={palaceMeta} />);
    expect(screen.getByText('Izquierda')).toBeInTheDocument();
    expect(screen.getByText('Centro')).toBeInTheDocument();
    expect(screen.getByText('Derecha')).toBeInTheDocument();
    expect(screen.getByText('tu mejor zona')).toBeInTheDocument();
    expect(screen.getByText('ventaja leve')).toBeInTheDocument();
    expect(screen.getByText('sin ventaja')).toBeInTheDocument();
    // each in-box number renders exactly once (the row no longer repeats it)
    expect(screen.getAllByText('+2%')).toHaveLength(1);
  });

  test('zone thirds are shaded with level color + strength-scaled opacity', () => {
    render(<DefensiveZonesCard data={palaceMeta} />);
    const left = screen.getByTestId('zone-shade-left');
    const central = screen.getByTestId('zone-shade-central');
    const right = screen.getByTestId('zone-shade-right');
    expect(right).toHaveAttribute('fill', ZONE_SHADE_HEX.opp);
    expect(central).toHaveAttribute('fill', ZONE_SHADE_HEX.warm);
    expect(left).toHaveAttribute('fill', ZONE_SHADE_HEX.cool);
    const opacity = (el: HTMLElement) =>
      parseFloat(el.getAttribute('fill-opacity') ?? '0');
    expect(opacity(right)).toBeCloseTo(zoneShadeOpacity('opp', 69.8), 5);
    expect(opacity(right)).toBeGreaterThan(opacity(central));
    expect(opacity(central)).toBeGreaterThan(opacity(left));
    // regions tile the full penalty box (x 30..330 in thirds)
    expect(left).toHaveAttribute('x', '30');
    expect(central).toHaveAttribute('x', '130');
    expect(right).toHaveAttribute('x', '230');
  });

  test('renders exploiter table with rank, name, team·pos, zone pill, fit', () => {
    render(<DefensiveZonesCard data={palaceMeta} />);
    expect(screen.getByText('Quién lo explota')).toBeInTheDocument();
    expect(screen.getByText('Saka')).toBeInTheDocument();
    expect(screen.getByText('ARS · MED')).toBeInTheDocument();
    expect(screen.getByText('10.0')).toBeInTheDocument();
    // corrected handedness: the right-siders' zone pill reads 'Der'
    expect(screen.getAllByText('Der')).toHaveLength(3);
    // join-miss degrade: player still listed, no dangling separator
    expect(screen.getByText('Alejandro Jiménez')).toBeInTheDocument();
    expect(screen.getByText('BOU')).toBeInTheDocument();
    expect(screen.queryByText('BOU ·')).not.toBeInTheDocument();
  });

  test('renders penalty footer and IA badge when ai_active', () => {
    render(<DefensiveZonesCard data={palaceMeta} />);
    expect(screen.getByText('0.140 xGA/partido')).toBeInTheDocument();
    expect(screen.getByText('IA activa')).toBeInTheDocument();
  });

  test('hides IA badge when ai_active=false', () => {
    render(
      <DefensiveZonesCard data={{ ...palaceMeta, ai_active: false }} />,
    );
    expect(screen.queryByText('IA activa')).not.toBeInTheDocument();
  });

  test('empty exploiters shows the fallback line, not the table', () => {
    render(<DefensiveZonesCard data={{ ...palaceMeta, exploiters: [] }} />);
    expect(screen.queryByText('Quién lo explota')).not.toBeInTheDocument();
    expect(
      screen.getByText('Sin perfiles de jugador que encajen en estas zonas todavía.'),
    ).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // i91 — "zonas débiles de X" alone (no players asked about) still gets the
  // pitch view. has_exploiters=false must omit the exploiter section
  // ENTIRELY, not show the "no matching players" fallback -- that fallback
  // is a real finding (opportunity asked, zero players fit); this is a
  // different case (never asked).
  // -------------------------------------------------------------------------

  test('has_exploiters=false renders the pitch but no exploiter section at all', () => {
    render(
      <DefensiveZonesCard
        data={{ ...palaceMeta, exploiters: [], has_exploiters: false }}
      />,
    );
    // pitch view still there
    expect(screen.getByText('Débil dentro del área')).toBeInTheDocument();
    expect(screen.getByText(/Ataca a Crystal Palace/)).toBeInTheDocument();
    // no table, no header, no empty-state fallback
    expect(screen.queryByText('Quién lo explota')).not.toBeInTheDocument();
    expect(screen.queryByTestId('zonal-no-exploiters')).not.toBeInTheDocument();
    expect(
      screen.queryByText('Sin perfiles de jugador que encajen en estas zonas todavía.'),
    ).not.toBeInTheDocument();
  });

  test('has_exploiters omitted (undefined) behaves as true (pre-i91 payloads)', () => {
    // palaceMeta never sets has_exploiters -- exactly a pre-i91 payload shape.
    render(<DefensiveZonesCard data={palaceMeta} />);
    expect(screen.getByText('Quién lo explota')).toBeInTheDocument();
    expect(screen.getByText('Saka')).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // i74 — season stamp. The card used to present a full, confident verdict
  // computed on last season's shots without naming a season anywhere.
  // -------------------------------------------------------------------------

  test('live-season data gets a discreet stamp, not a warning', () => {
    render(
      <DefensiveZonesCard
        data={{ ...palaceMeta, data_provenance: currentProvenance }}
      />,
    );
    const stamp = screen.getByTestId('zonal-provenance');
    expect(stamp).toHaveTextContent('Datos: temporada 2026-27');
    expect(stamp).toHaveAttribute('data-status', 'current');
    expect(stamp.className).toContain('text-bf-gray/55');
    expect(stamp.className).not.toContain('bf-gold');
  });

  test('out-of-season data escalates to an explicit gold notice', () => {
    render(
      <DefensiveZonesCard
        data={{ ...palaceMeta, data_provenance: staleProvenance }}
      />,
    );
    const stamp = screen.getByTestId('zonal-provenance');
    expect(stamp).toHaveTextContent(
      '⚠ Datos de 2025-26, no de la temporada en curso (2026-27)',
    );
    expect(stamp).toHaveAttribute('data-status', 'stale_season');
    expect(stamp.className).toContain('bf-gold');
    // informs, never alarms — coral/red stays reserved for the weakness pill
    expect(stamp.className).not.toContain('coral');
    // and it still shows the analysis: declare, never withhold
    expect(screen.getByText('Saka')).toBeInTheDocument();
  });

  test('the stamp sits above the numbers it qualifies', () => {
    const { container } = render(
      <DefensiveZonesCard
        data={{ ...palaceMeta, data_provenance: staleProvenance }}
      />,
    );
    const stamp = screen.getByTestId('zonal-provenance');
    const pitch = container.querySelector('svg')!;
    expect(
      stamp.compareDocumentPosition(pitch) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  test('a payload with no provenance renders no stamp at all', () => {
    render(<DefensiveZonesCard data={palaceMeta} />);
    expect(screen.queryByTestId('zonal-provenance')).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// i85–i88 — team scope + per-row evidence. Found 2026-09-11 on Liverpool vs
// Fulham: the table was correctly scoped but nothing said so, and Virgil van
// Dijk ranked #2 "Izq" on two corner headers with nothing to say why.
// ---------------------------------------------------------------------------

describe('DefensiveZonesCard — scope + evidence (i85–i88)', () => {
  const scoped = {
    ...palaceMeta,
    team_filter: {
      requested: 'Liverpool',
      matched: 'Liverpool',
      source: 'inferred' as const,
      min_shots: 1,
      zone_share_threshold: 0,
    },
    exploiters: [
      {
        rank: 1, web_name: 'Isak', team_short: 'LIV', position: 'FWD',
        zone: 'in-box / central', fit_score: 10,
        n_shots: 9, zone_share: 0.898, sample: 'thin' as const,
        zone_shots: 8, set_piece_share: 0, origin: 'open_play' as const,
      },
      {
        rank: 2, web_name: 'Virgil', team_short: 'LIV', position: 'DEF',
        zone: 'in-box / left', fit_score: 3.1,
        n_shots: 2, zone_share: 0.534, sample: 'thin' as const,
        zone_shots: 2, set_piece_share: 1, origin: 'set_piece' as const,
      },
    ],
  };

  test('team-scoped table names the scope, and says it came from the question', () => {
    render(<DefensiveZonesCard data={scoped} />);
    expect(screen.getByTestId('zonal-scope')).toHaveTextContent(
      'Liverpool · según tu pregunta',
    );
  });

  test('explicit scope names the team without the inference suffix', () => {
    render(
      <DefensiveZonesCard
        data={{ ...scoped, team_filter: { ...scoped.team_filter, source: 'explicit' } }}
      />,
    );
    expect(screen.getByTestId('zonal-scope')).toHaveTextContent('Liverpool');
    expect(screen.getByTestId('zonal-scope')).not.toHaveTextContent('según tu pregunta');
  });

  test('an unresolved filter is not presented as a scope', () => {
    render(
      <DefensiveZonesCard
        data={{ ...scoped, team_filter: { ...scoped.team_filter, matched: null } }}
      />,
    );
    expect(screen.queryByTestId('zonal-scope')).not.toBeInTheDocument();
  });

  test('league-wide table (no team_filter) has no scope caption', () => {
    render(<DefensiveZonesCard data={palaceMeta} />);
    expect(screen.queryByTestId('zonal-scope')).not.toBeInTheDocument();
  });

  test('a set-piece exploiter is labelled as such, in gold, with its zone shots', () => {
    render(<DefensiveZonesCard data={scoped} />);
    const lines = screen.getAllByTestId('zonal-evidence');
    const virgil = lines.find((el) => el.getAttribute('data-origin') === 'set_piece')!;
    expect(virgil).toHaveTextContent('53% de su xG aquí · 2 tiros · balón parado');
    expect(virgil).toHaveTextContent('muestra corta');
    expect(virgil.className).toContain('text-bf-gold');
  });

  test('an open-play exploiter reads "jugada" and is not gold', () => {
    render(<DefensiveZonesCard data={scoped} />);
    const lines = screen.getAllByTestId('zonal-evidence');
    const isak = lines.find((el) => el.getAttribute('data-origin') === 'open_play')!;
    expect(isak).toHaveTextContent('90% de su xG aquí · 8 tiros · jugada');
    expect(isak.className).not.toContain('text-bf-gold');
  });

  test('singular "tiro" for one shot', () => {
    render(
      <DefensiveZonesCard
        data={{ ...scoped, exploiters: [{ ...scoped.exploiters[1], zone_shots: 1 }] }}
      />,
    );
    expect(screen.getByTestId('zonal-evidence')).toHaveTextContent('1 tiro');
    expect(screen.getByTestId('zonal-evidence')).not.toHaveTextContent('1 tiros');
  });

  test('pre-i87 payload rows (no evidence fields) render no evidence line', () => {
    render(<DefensiveZonesCard data={palaceMeta} />);
    expect(screen.queryAllByTestId('zonal-evidence')).toHaveLength(0);
  });
});

describe('DefensiveZonesCard — multi-team scope + marginal read (i89)', () => {
  test('several matched teams show as one joined scope', () => {
    render(
      <DefensiveZonesCard
        data={{
          ...palaceMeta,
          team_filter: {
            requested: 'ARS, LIV, MCI',
            matched: 'Arsenal, Liverpool, Manchester City',
            source: 'inferred',
            requested_teams: ['ARS', 'LIV', 'MCI'],
            matched_teams: ['Arsenal', 'Liverpool', 'Manchester City'],
            unmatched_teams: [],
          },
        }}
      />,
    );
    expect(screen.getByTestId('zonal-scope')).toHaveTextContent(
      'Arsenal, Liverpool, Manchester City · según tu pregunta',
    );
  });

  test('a marginal read is flagged in the table header', () => {
    render(<DefensiveZonesCard data={{ ...palaceMeta, weakness_strength: 'marginal' }} />);
    expect(screen.getByTestId('zonal-marginal')).toHaveTextContent('lectura marginal');
  });

  test('a clear read (or a pre-i89 payload) has no marginal flag', () => {
    render(<DefensiveZonesCard data={{ ...palaceMeta, weakness_strength: 'clear' }} />);
    expect(screen.queryByTestId('zonal-marginal')).not.toBeInTheDocument();
    render(<DefensiveZonesCard data={palaceMeta} />);
    expect(screen.queryByTestId('zonal-marginal')).not.toBeInTheDocument();
  });
});

describe('DefensiveZonesCard — fixture-derived scope (i90)', () => {
  const fixtureTeamFilter: ZonalTeamFilter = {
    requested: null,
    matched: 'Burnley, Aston Villa',
    source: 'fixtures',
    requested_teams: [],
    matched_teams: ['Burnley', 'Aston Villa'],
    unmatched_teams: [],
    fixture_window: { from_gw: 5, to_gw: 6, horizon: 2 },
    fixtures: [
      { gameweek: 5, team: 'Burnley', is_home: false },
      { gameweek: 6, team: 'Aston Villa', is_home: true },
    ],
    scheduled_opponents: ['Burnley', 'Aston Villa'],
  };

  const fixtureScoped: DefensiveZonesMeta = {
    ...palaceMeta,
    team_filter: fixtureTeamFilter,
    exploiters: [
      {
        rank: 1, web_name: 'Right Poacher', team_short: 'BUR', position: 'FWD',
        zone: 'in-box / right', fit_score: 10.0, gameweek: 5, is_home: false,
      },
      {
        rank: 2, web_name: 'Someone', team_short: 'BUR', position: '',
        zone: 'in-box / right', fit_score: 4.0, gameweek: 5, is_home: false,
      },
      {
        rank: 3, web_name: 'Heavy Hitter', team_short: 'AVL', position: 'MID',
        zone: 'in-box / right', fit_score: 9.0, gameweek: 6, is_home: true,
      },
    ],
  };

  test('scope caption reads "rivales de X hasta la J{to_gw}"', () => {
    render(<DefensiveZonesCard data={fixtureScoped} />);
    expect(screen.getByTestId('zonal-scope')).toHaveTextContent(
      'rivales de Crystal Palace hasta la J6',
    );
  });

  test('table groups by gameweek, one header per fixture, subject named', () => {
    render(<DefensiveZonesCard data={fixtureScoped} />);
    const groups = screen.getAllByTestId('zonal-fixture-group');
    expect(groups).toHaveLength(2);
    expect(groups[0]).toHaveTextContent('J5 · BUR visita a Crystal Palace');
    expect(groups[1]).toHaveTextContent('J6 · AVL recibe a Crystal Palace');
  });

  test('is_home flips the wording — never bare (L)/(V)', () => {
    const first = render(<DefensiveZonesCard data={fixtureScoped} />);
    const groups = screen.getAllByTestId('zonal-fixture-group');
    expect(groups[0]).not.toHaveTextContent('(V)');
    expect(groups[0]).not.toHaveTextContent('(L)');
    first.unmount();
    // flipping is_home flips which verb is used
    const flipped = {
      ...fixtureScoped,
      exploiters: fixtureScoped.exploiters.map((e) =>
        e.gameweek === 5 ? { ...e, is_home: true } : e,
      ),
    };
    render(<DefensiveZonesCard data={flipped} />);
    expect(screen.getAllByTestId('zonal-fixture-group')[0]).toHaveTextContent(
      'J5 · BUR recibe a Crystal Palace',
    );
  });

  test('rows within a group keep their rank/fit order', () => {
    render(<DefensiveZonesCard data={fixtureScoped} />);
    const names = screen.getAllByText(/Right Poacher|Someone|Heavy Hitter/);
    expect(names.map((n) => n.textContent)).toEqual(['Right Poacher', 'Someone', 'Heavy Hitter']);
  });

  test('a genuine double gameweek (two DIFFERENT rivals, same GW number) gets two separate groups', () => {
    // Found in review: grouping keyed by gameweek alone would merge both
    // rivals' rows under one team's header -- wrong team AND wrong
    // home/away for whichever rival lost the merge.
    const doubleGw: DefensiveZonesMeta = {
      ...fixtureScoped,
      team_filter: {
        ...fixtureTeamFilter,
        matched_teams: ['Burnley', 'Aston Villa'],
        fixture_window: { from_gw: 5, to_gw: 5, horizon: 1 },
        fixtures: [
          { gameweek: 5, team: 'Burnley', is_home: false },
          { gameweek: 5, team: 'Aston Villa', is_home: true },
        ],
        scheduled_opponents: ['Burnley', 'Aston Villa'],
      },
      exploiters: [
        {
          rank: 1, web_name: 'Right Poacher', team_short: 'BUR', position: 'FWD',
          zone: 'in-box / right', fit_score: 10.0, gameweek: 5, is_home: false,
        },
        {
          rank: 2, web_name: 'Heavy Hitter', team_short: 'AVL', position: 'MID',
          zone: 'in-box / right', fit_score: 9.0, gameweek: 5, is_home: true,
        },
      ],
    };
    render(<DefensiveZonesCard data={doubleGw} />);
    const groups = screen.getAllByTestId('zonal-fixture-group');
    expect(groups).toHaveLength(2);
    expect(groups[0]).toHaveTextContent('J5 · BUR visita a Crystal Palace');
    expect(groups[1]).toHaveTextContent('J5 · AVL recibe a Crystal Palace');
    // each rival's row sits under its OWN header container, not the other's
    const burSection = groups[0].parentElement!;
    const avlSection = groups[1].parentElement!;
    expect(burSection).toHaveTextContent('Right Poacher');
    expect(burSection).not.toHaveTextContent('Heavy Hitter');
    expect(avlSection).toHaveTextContent('Heavy Hitter');
    expect(avlSection).not.toHaveTextContent('Right Poacher');
  });

  test('a pre-i90 payload (no team_filter.source==="fixtures") renders no fixture groups', () => {
    render(<DefensiveZonesCard data={palaceMeta} />);
    expect(screen.queryAllByTestId('zonal-fixture-group')).toHaveLength(0);
  });

  test('an explicit-team payload (source !== "fixtures") also renders no fixture groups', () => {
    render(
      <DefensiveZonesCard
        data={{
          ...fixtureScoped,
          team_filter: { ...fixtureTeamFilter, source: 'explicit', matched: 'Burnley' },
        }}
      />,
    );
    expect(screen.queryAllByTestId('zonal-fixture-group')).toHaveLength(0);
  });
});
