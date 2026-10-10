/**
 * PlayerZonasSection — the «Zonas» section of PlayerCard (Bloque 10).
 *
 * Rendered only when the snapshot carries a `zonal` block (the backend
 * omits it when it cannot prove the player's identity or has no pending
 * match). Shows where the player generates his xG and how the PENDING
 * matches of the next 3 gameweeks line up with it.
 *
 * Units: `share` / `player_share` arrive as 0–1 fractions; `sharePercent`
 * converts them here, once, for display. Chips are not renormalised — they
 * need not sum to 100 % (shots outside every zone count toward the total
 * only).
 *
 * Colour: favorable → turquoise, neutral → grey, no_data → plain text
 * («Sin datos del rival»; never rendered as neutral). Framing is opportunity
 * only. The season stamp is the same component the zonal card uses.
 */
import type { PlayerZonalFixture, PlayerZonalOutlookMeta } from '@/lib/types';
import {
  LEVEL_PILL_CLASS,
  sharePercent,
  zoneChipLabel,
} from '@/lib/defensive-zones';
import { ProvenanceStamp } from './DefensiveZonesCard';
import { formatVenue } from './FixtureRunTable';
import { PITCH_LEGEND, hasPlaceableZones } from './PlayerZonesPitch';
import PlayerZonesPitchExpandable from './PlayerZonesPitchExpandable';

interface Props {
  zonal: PlayerZonalOutlookMeta;
  /** The player's name, for the enlarge button's accessible label. */
  playerName: string;
}

export default function PlayerZonasSection({ zonal, playerName }: Props) {
  if (zonal.zones.length === 0 || zonal.fixtures.length === 0) return null;
  const { gw_from, gw_to } = zonal;
  const hasPitch = hasPlaceableZones(zonal.zones);
  const range = gw_from === gw_to ? `J${gw_from}` : `J${gw_from}–J${gw_to}`;

  return (
    <section
      data-testid="player-zonas"
      data-verdict-kind={zonal.verdict_kind}
      className="space-y-2 border-t border-white/10 pt-2.5"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <h3 className="text-[10px] font-extrabold uppercase tracking-wider text-bf-gray">Zonas</h3>
        <span className="text-[10px] text-bf-gray">
          Partidos de las próximas 3 jornadas · {range}
        </span>
      </div>

      <p
        data-testid="player-zonas-verdict"
        className={`text-xs leading-snug ${
          zonal.verdict_kind === 'favorable'
            ? 'text-bf-turquoise'
            : zonal.verdict_kind === 'no_data'
              ? 'text-bf-gray'
              : 'text-bf-text/80'
        }`}
      >
        {zonal.verdict}
      </p>

      <div className="flex flex-col gap-3 min-[481px]:flex-row min-[481px]:items-start">
        {hasPitch && (
          <div className="w-full min-[481px]:w-[220px] min-[481px]:flex-shrink-0" data-testid="player-zonas-pitch-wrap">
            <PlayerZonesPitchExpandable
              playerName={playerName}
              zones={zonal.zones}
              fixtures={zonal.fixtures}
            />
          </div>
        )}
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap gap-1.5" data-testid="player-zonas-chips">
            {zonal.zones.map((z) => (
              <span
                key={z.zone}
                className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] font-bold text-white"
              >
                {zoneChipLabel(z.zone)} · {sharePercent(z.share)}% de su xG sin penalti
              </span>
            ))}
          </div>
          {zonal.fixtures.some((f) => f.status === 'favorable') && (
            <p data-testid="player-zonas-legend" className="text-[10px] leading-snug text-bf-gray">
              {PITCH_LEGEND}
            </p>
          )}
        </div>
      </div>

      <ul className="space-y-1" data-testid="player-zonas-rows">
        {zonal.fixtures.map((f) => (
          <ZonasRow key={`${f.fixture_id ?? 'x'}-${f.gameweek}-${f.opponent_short}`} fixture={f} />
        ))}
      </ul>

      {zonal.data_provenance && <ProvenanceStamp provenance={zonal.data_provenance} />}
    </section>
  );
}

function ZonasRow({ fixture }: { fixture: PlayerZonalFixture }) {
  const { gameweek, opponent, is_home, status, matches } = fixture;
  const zones = matches.map((m) => zoneChipLabel(m.zone)).join(', ');
  return (
    <li
      data-testid="player-zonas-row"
      data-status={status}
      className="flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5 text-xs"
    >
      <span className="min-w-0 truncate text-white">
        <span className="font-bold text-bf-gray">J{gameweek}</span>{' '}
        {opponent} <span className="text-bf-gray">({formatVenue(is_home)})</span>
      </span>
      {status === 'favorable' ? (
        <span
          className={`flex-shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-bold ${LEVEL_PILL_CLASS.opp}`}
        >
          Cruce favorable{zones ? ` · ${zones}` : ''}
        </span>
      ) : status === 'no_data' ? (
        <span className="flex-shrink-0 text-[10px] text-bf-gray">Sin datos del rival</span>
      ) : (
        <span
          className={`flex-shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-bold ${LEVEL_PILL_CLASS.cool}`}
        >
          Sin cruce destacado
        </span>
      )}
    </li>
  );
}
