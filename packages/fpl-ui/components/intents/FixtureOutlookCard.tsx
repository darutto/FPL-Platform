/**
 * FixtureOutlookCard — structured rendering for fixture_outlook OK turns.
 *
 * Rendered beneath final_text when:
 *   response.outcome         === 'ok'
 *   response.intent          === 'fixture_outlook'
 *   response.fixture_outlook !== null  (teams.length > 0)
 *
 * Track D / FI4. Two-axis fixture ticker with run detection. Foregrounds the
 * Spanish verdict (chat-first), with a per-GW colour strip and grouped run
 * rings as visual support (shared FixtureTickerRow — same rows as the /fixtures
 * page). The axis (attack / clean-sheet) is whatever the backend resolved for
 * the turn; the interactive toggle lives on the standalone Fixtures page (FI7).
 *
 * Analytical card → FingerprintWaves ornament (design-system semantics).
 */
import type { FixtureOutlookMeta } from '@/lib/types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { axisLabel } from '@/lib/fixture-outlook-format';
import { FixtureTickerRow, BandLegend } from './FixtureTickerRow';
import { FingerprintWaves } from './CardOrnaments';

interface Props {
  data: FixtureOutlookMeta;
}

export default function FixtureOutlookCard({ data }: Props) {
  const { axis, teams } = data;
  if (teams.length === 0) return null;

  return (
    <div className={`mt-3 ${CARD_BASE} ${CARD_ACCENT.turquoise.border}`}>
      {/* Analytical card → fingerprint waves (design-system semantics). */}
      <FingerprintWaves color={ACCENT_HEX.turquoise} corner="br" />
      <div className="relative z-10 p-4 space-y-3">
        {/* Header */}
        <div className="flex items-center gap-2 text-sm">
          <span className="font-extrabold text-white">Calendario</span>
          <span className="text-bf-gray/60">·</span>
          <span
            className="text-[10px] font-bold uppercase tracking-wider rounded px-1.5 py-0.5"
            style={{ backgroundColor: `${ACCENT_HEX.turquoise}22`, color: ACCENT_HEX.turquoise }}
          >
            {axisLabel(axis)}
          </span>
        </div>

        {/* Team rows */}
        <div className="space-y-3">
          {teams.map((t) => (
            <FixtureTickerRow key={t.team_short} team={t} />
          ))}
        </div>

        {/* Legend */}
        <BandLegend />
      </div>
    </div>
  );
}
