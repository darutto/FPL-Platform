/**
 * DefensiveZonesCard — structured rendering for zonal_opportunity OK turns (T4b).
 *
 * Rendered beneath final_text when:
 *   response.outcome            === 'ok'
 *   response.intent             === 'zonal_opportunity'
 *   response.zonal_opportunity  !== null (with 3 zone cells)
 *
 * Recreates the "Defensive Zones Card" design handoff with DS tokens:
 * header (kicker + team + coral weakness pill), verdict with turquoise pct,
 * inline-SVG penalty-box pitch with the three zone thirds shaded by
 * opportunity (saturation scales with the zone's strength; the % reading
 * lives inside its region, average zones read '≈ media'), per-zone
 * labels + pills, the "Quién lo explota" zone-fit table, and the footer
 * (penalty xGA + IA ACTIVA badge).
 *
 * Color semantics (do not invert): turquoise = your best zone, gold = slight
 * advantage, grey = none. Coral only for the opponent-weakness pill.
 *
 * The handoff's outer composition (user question pill, "Seguir conversación"
 * ghost button) is already provided by the chat shell (user bubble +
 * MessageList's FollowUpButton) — this component is the data card itself.
 */
import type { DefensiveZonesMeta, ZonalExploiter } from '@/lib/types';
import { CARD_BASE, CARD_ACCENT, PILL_BASE } from '@/lib/theme';
import {
  LEVEL_PILL_LABEL,
  LEVEL_TEXT_CLASS,
  LEVEL_PILL_CLASS,
  ZONE_SHADE_HEX,
  zoneShadeOpacity,
  isAverageZone,
  formatDeltaFine,
  LATERAL_LABEL,
  formatPct,
  formatFit,
  formatPenalty,
  rankOpacity,
  zonePillLabel,
  levelForZone,
  exploiterSub,
  splitVerdict,
} from '@/lib/defensive-zones';

interface Props {
  data: DefensiveZonesMeta;
}

/** Penalty-box thirds in SVG units: x origin per zone, region width/bounds. */
const ZONE_X = [30, 130, 230];
const ZONE_WIDTH = 100;
const ZONE_CENTER_X = [80, 180, 280];

export default function DefensiveZonesCard({ data }: Props) {
  const { opponent, weakness_label, verdict, zones, exploiters } = data;

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.coral.border}`}>
      <div className="relative z-10 p-5">
        {/* Header — kicker + team, opponent-weakness pill (coral = alert) */}
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <div className="flex flex-col gap-0.5">
            <span className="text-[11px] font-extrabold uppercase tracking-[0.13em] text-bf-coral whitespace-nowrap">
              Zonas que concede
            </span>
            <span className="text-base font-black tracking-tight text-bf-text">
              {opponent}
            </span>
          </div>
          <span
            className={`${PILL_BASE} text-[10px] font-extrabold bg-bf-coral/10 border-bf-coral/40 text-bf-coral whitespace-nowrap`}
          >
            {weakness_label}
          </span>
        </div>

        {/* Verdict — backend Spanish string, headline pct bolded turquoise */}
        <p className="mb-3.5 text-[13.5px] leading-normal text-bf-text/80">
          {splitVerdict(verdict).map((seg, i) =>
            seg.highlight ? (
              <strong key={i} className="font-bold text-bf-turquoise">
                {seg.text}
              </strong>
            ) : (
              <span key={i}>{seg.text}</span>
            ),
          )}{' '}
          <span className="text-bf-gray/60">
            Cuanto más verde, mayor tu ventaja.
          </span>
        </p>

        {/* Pitch view — penalty box with the three zone thirds shaded by
            opportunity; each zone's reading lives inside its region */}
        <div className="relative mx-auto w-full max-w-[420px]">
          <svg
            viewBox="0 0 360 210"
            className="block h-auto w-full"
            role="img"
            aria-label={zones
              .map(
                (z) =>
                  `${LATERAL_LABEL[z.lateral]}: ${
                    isAverageZone(z.pct_over_avg)
                      ? '≈ media'
                      : formatPct(z.pct_over_avg)
                  }`,
              )
              .join(' · ')}
          >
            {/* shaded thirds first, pitch lines on top */}
            {zones.map((zone, i) => (
              <rect
                key={zone.lateral}
                data-testid={`zone-shade-${zone.lateral}`}
                x={ZONE_X[i]}
                y={26}
                width={ZONE_WIDTH}
                height={150}
                fill={ZONE_SHADE_HEX[zone.opportunity_level]}
                fillOpacity={zoneShadeOpacity(
                  zone.opportunity_level,
                  zone.pct_over_avg,
                )}
              />
            ))}
            <rect x="30" y="26" width="300" height="150" fill="none" stroke="rgba(255,255,255,.18)" strokeWidth="1.5" />
            <rect x="110" y="26" width="140" height="46" fill="none" stroke="rgba(255,255,255,.14)" strokeWidth="1.5" />
            <rect x="150" y="20" width="60" height="6" fill="rgba(255,255,255,.85)" />
            <line x1="130" y1="26" x2="130" y2="176" stroke="rgba(255,255,255,.08)" strokeWidth="1" strokeDasharray="4 5" />
            <line x1="230" y1="26" x2="230" y2="176" stroke="rgba(255,255,255,.08)" strokeWidth="1" strokeDasharray="4 5" />
            <circle cx="180" cy="112" r="3" fill="rgba(255,255,255,.4)" />
            <path d="M 140 176 A 45 45 0 0 0 220 176" fill="none" stroke="rgba(255,255,255,.12)" strokeWidth="1.5" />
            {/* per-zone reading inside its shaded region */}
            {zones.map((zone, i) =>
              isAverageZone(zone.pct_over_avg) ? (
                <text
                  key={zone.lateral}
                  x={ZONE_CENTER_X[i]}
                  y={132}
                  textAnchor="middle"
                  fill="#ABA9AC"
                  fillOpacity={0.55}
                  style={{ fontSize: 13, fontWeight: 700 }}
                >
                  ≈ media
                </text>
              ) : (
                <g key={zone.lateral}>
                  <text
                    x={ZONE_CENTER_X[i]}
                    y={128}
                    textAnchor="middle"
                    fill={ZONE_SHADE_HEX[zone.opportunity_level]}
                    style={{
                      fontSize: 28,
                      fontWeight: 900,
                      letterSpacing: '-1px',
                    }}
                  >
                    {formatPct(zone.pct_over_avg)}
                  </text>
                  <text
                    x={ZONE_CENTER_X[i]}
                    y={146}
                    textAnchor="middle"
                    fill={ZONE_SHADE_HEX[zone.opportunity_level]}
                    fillOpacity={0.75}
                    style={{ fontSize: 12, fontWeight: 600 }}
                  >
                    {formatDeltaFine(zone.pct_over_avg)}
                  </text>
                </g>
              ),
            )}
          </svg>
        </div>

        {/* Per-zone labels + opportunity pills (the % lives in the box now) */}
        <div className="mb-1.5 mt-2 grid grid-cols-3 gap-2">
          {zones.map((zone) => (
            <div
              key={zone.lateral}
              className="flex flex-col items-center gap-1.5 text-center"
            >
              <span
                className={`text-[10.5px] font-extrabold uppercase tracking-[0.08em] ${LEVEL_TEXT_CLASS[zone.opportunity_level]}`}
              >
                {LATERAL_LABEL[zone.lateral]}
              </span>
              <span
                className={`${PILL_BASE} text-[10px] font-extrabold whitespace-nowrap ${LEVEL_PILL_CLASS[zone.opportunity_level]}`}
              >
                {LEVEL_PILL_LABEL[zone.opportunity_level]}
              </span>
            </div>
          ))}
        </div>
        <div className="mb-4 text-center text-[10.5px] text-bf-gray/50">
          goles esperados por encima de un equipo medio de la liga
        </div>

        {/* "Quién lo explota" — zone-fit table */}
        {exploiters.length > 0 ? (
          <div className="mb-4 overflow-hidden rounded-[10px] border border-white/[0.08]">
            <div className="flex items-center justify-between border-b border-white/[0.08] bg-white/[0.02] px-3 py-2">
              <span className="text-[11px] font-extrabold uppercase tracking-[0.08em] text-bf-text">
                Quién lo explota
              </span>
              <span className="text-[10.5px] text-bf-gray/60">
                ajuste a la zona
              </span>
            </div>
            <div className="grid grid-cols-[1.4rem_1fr_auto_auto] gap-3 border-b border-white/[0.06] px-3 py-1.5 text-[9.5px] font-extrabold uppercase tracking-[0.06em] text-bf-gray/60">
              <span>#</span>
              <span>Jugador</span>
              <span className="text-center">Zona</span>
              <span className="text-right">Ajuste</span>
            </div>
            {exploiters.map((e, i) => (
              <ExploiterRow key={e.rank} exploiter={e} striped={i % 2 === 0} data={data} />
            ))}
          </div>
        ) : (
          <div className="mb-4 rounded-[10px] border border-white/[0.08] px-3 py-2.5 text-[11px] text-bf-gray/60">
            Sin perfiles de jugador que encajen en estas zonas todavía.
          </div>
        )}

        {/* Footer — penalty context + IA badge */}
        <div className="flex flex-wrap items-center justify-between gap-2.5 border-t border-white/[0.07] pt-3.5">
          <span className="text-[11px] text-bf-gray/60">
            Penaltis (excluidos):{' '}
            <span className="font-bold text-bf-gray">
              {formatPenalty(data.penalty_xga_per_game)} xGA/partido
            </span>
          </span>
          {data.ai_active && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-bf-turquoise/40 bg-bf-turquoise/10 px-3 py-1 text-[11px] font-bold uppercase tracking-[0.1em] text-bf-turquoise">
              <span
                aria-hidden="true"
                className="h-1.5 w-1.5 rounded-full bg-bf-turquoise"
              />
              IA activa
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function ExploiterRow({
  exploiter,
  striped,
  data,
}: {
  exploiter: ZonalExploiter;
  striped: boolean;
  data: DefensiveZonesMeta;
}) {
  const level = levelForZone(exploiter.zone, data.zones);
  const numberClass = LEVEL_TEXT_CLASS[level];
  const opacity = rankOpacity(exploiter.rank);
  const sub = exploiterSub(exploiter.team_short, exploiter.position);

  return (
    <div
      className={`grid grid-cols-[1.4rem_1fr_auto_auto] items-center gap-3 px-3 py-2 ${
        striped ? 'bg-white/[0.035]' : ''
      }`}
    >
      <span
        className={`text-[15px] font-black leading-none tracking-[-0.5px] ${numberClass}`}
        style={{ opacity }}
      >
        {exploiter.rank}
      </span>
      <span className="min-w-0 truncate">
        <strong className="font-bold text-white">{exploiter.web_name}</strong>
        {sub && <span className="ml-1 text-[11px] text-bf-gray">{sub}</span>}
      </span>
      <span className="text-center">
        <span
          className={`${PILL_BASE} text-[10px] font-extrabold whitespace-nowrap ${LEVEL_PILL_CLASS[level]}`}
        >
          {zonePillLabel(exploiter.zone)}
        </span>
      </span>
      <span
        className={`text-right text-[15px] font-black leading-none tracking-[-0.5px] ${numberClass}`}
        style={{ opacity }}
      >
        {formatFit(exploiter.fit_score)}
      </span>
    </div>
  );
}
