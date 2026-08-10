/**
 * PlayerCard — rich "Hi-Fi" rendering for player_snapshot OK turns.
 *
 * Rendered beneath final_text when:
 *   response.outcome        === 'ok'
 *   response.intent         === 'player_snapshot'
 *   response.player_snapshot !== null
 *
 * Consumes from PlayerSnapshotMeta (stable conditional fields only):
 *   web_name, team_short, position, status, news, form, total_points,
 *   points_per_game, now_cost, selected_by_percent, expected_goals,
 *   expected_assists, expected_goal_involvements, ict_index,
 *   minutes_played_season.
 *
 * Also shows a compact next-5-fixtures strip (fixtures field, reusing
 * FixtureRunTable's FixtureChip) when the player's team is covered by
 * bootstrap["team_fixtures"] — empty array otherwise, strip omitted.
 *
 * Deliberately has no BF/position_score — get_player_snapshot is a pure
 * grounding-payload lookup, not a position_score.py caller. This card
 * renders the CURRENT snapshot fields with the same visual quality as
 * ComparisonCard/DifferentialTable; it is expected to evolve.
 */
import type { PlayerSnapshotMeta } from '@/lib/types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX, PILL_BASE } from '@/lib/theme';
import {
  UNIT_PRICE,
  UNIT_FORM,
  UNIT_OWNERSHIP,
  UNIT_PPG,
  UNIT_XG,
  UNIT_XA,
  UNIT_XGI,
  UNIT_ICT,
  UNIT_MINUTES,
} from '@/lib/copy';
import { FingerprintWaves } from './CardOrnaments';
import { resolveStatusBadge } from './InjuriesTable';
import { FixtureChip, fixtureKey } from './FixtureRunTable';

interface Props {
  data: PlayerSnapshotMeta;
}

const ACCENT = 'purple' as const;

export default function PlayerCard({ data }: Props) {
  const {
    web_name,
    team_short,
    position,
    status,
    news,
    form,
    total_points,
    points_per_game,
    now_cost,
    selected_by_percent,
    expected_goals,
    expected_assists,
    expected_goal_involvements,
    ict_index,
    minutes_played_season,
    fixtures,
  } = data;

  const { className: badgeClass, label: badgeLabel } = resolveStatusBadge(status);
  const showNews = status !== 'Available' && news.trim().length > 0;

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT[ACCENT].border}`}>
      <FingerprintWaves color={ACCENT_HEX.purple} corner="br" />
      <div className="relative z-10 p-4 space-y-3">
        {/* Header — name/team/position + status badge */}
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <span className="block truncate text-lg font-extrabold text-white">{web_name}</span>
            <span className="text-xs text-bf-gray">
              {team_short} · {position}
            </span>
          </div>
          <span className={`flex-shrink-0 ${PILL_BASE} ${badgeClass}`}>{badgeLabel}</span>
        </div>

        {showNews && <p className="text-xs text-bf-text/80 line-clamp-2">{news}</p>}

        {/* Hero metric — season total points */}
        <div>
          <div className="flex items-baseline gap-0.5 font-display leading-none tracking-tighter text-bf-purple">
            <span style={{ fontSize: 30 }}>{total_points}</span>
            <span className="text-[11px] font-bold text-bf-gray">pts</span>
          </div>
          <div className="text-[9px] font-bold uppercase tracking-wide text-bf-gray">
            {UNIT_PPG} {points_per_game.toFixed(1)}
          </div>
        </div>

        {/* Primary stat grid */}
        <div className="grid grid-cols-3 gap-2.5">
          <Stat label={UNIT_PRICE} value={`£${(now_cost / 10).toFixed(1)}m`} />
          <Stat label={UNIT_OWNERSHIP} value={`${selected_by_percent.toFixed(1)}%`} />
          <Stat label={UNIT_FORM} value={form.toFixed(1)} />
        </div>

        {/* Underlying stats — muted secondary row */}
        <div className="grid grid-cols-4 gap-2 border-t border-white/10 pt-2.5">
          <Stat label={UNIT_XG} value={expected_goals.toFixed(2)} muted />
          <Stat label={UNIT_XA} value={expected_assists.toFixed(2)} muted />
          <Stat label={UNIT_XGI} value={expected_goal_involvements.toFixed(2)} muted />
          <Stat label={UNIT_ICT} value={ict_index.toFixed(1)} muted />
        </div>

        <div className="text-[10px] text-bf-gray">
          {minutes_played_season} {UNIT_MINUTES}
        </div>

        {/* Next-5 fixture strip — reuses FixtureRunTable's chip so the two
            cards stay visually identical for the same underlying data. */}
        {fixtures.length > 0 && (
          <div className="flex flex-wrap gap-1.5 border-t border-white/10 pt-2.5">
            {fixtures.map((f) => (
              <FixtureChip key={fixtureKey(f)} entry={f} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, muted = false }: { label: string; value: string; muted?: boolean }) {
  return (
    <div className="min-w-0">
      <div
        className={`truncate font-display tracking-tighter leading-none ${
          muted ? 'text-sm text-bf-gray' : 'text-base text-white'
        }`}
      >
        {value}
      </div>
      <div className="text-[9px] font-bold uppercase tracking-wide text-bf-gray">{label}</div>
    </div>
  );
}
