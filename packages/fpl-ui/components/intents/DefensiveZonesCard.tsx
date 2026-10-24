/**
 * DefensiveZonesCard — structured rendering for zonal_opportunity OK turns (T4b).
 *
 * Rendered beneath final_text when:
 *   response.outcome            === 'ok'
 *   response.intent             === 'zonal_opportunity'
 *   response.zonal_opportunity  !== null (with 3 zone cells)
 *
 * Recreates the "Defensive Zones Card" design handoff with DS tokens:
 * header (kicker + team + opportunity pill), verdict with turquoise pct,
 * inline-SVG penalty-box pitch with the three zone thirds (plus, when the
 * payload carries them, the edge-of-box band in front — the headline can name
 * a frontal zone, so the pitch draws every zone it can name) shaded by
 * opportunity (saturation scales with the zone's strength; the % reading
 * lives inside its region, average zones read '≈ media'), per-zone
 * labels + pills, the "Quién lo explota" zone-fit table, and the footer
 * (penalty xGA + IA ACTIVA badge).
 *
 * Color semantics (do not invert): turquoise = your best zone, gold = slight
 * advantage, grey = none. The header pill follows the same coding (by
 * weakness_strength); no coral anywhere — this is the user's opportunity.
 *
 * i74: a season stamp sits under the verdict, above the numbers it qualifies.
 * It is always present and reads as a caption when the data is the live
 * season's; when it is not (or the sample is too thin) it escalates to a
 * gold notice carrying the backend's own warning text. Gold, not coral/red —
 * this informs, it does not alarm.
 *
 * The handoff's outer composition (user question pill, "Seguir conversación"
 * ghost button) is already provided by the chat shell (user bubble +
 * MessageList's FollowUpButton) — this component is the data card itself.
 */
import type {
  DefensiveZoneCell,
  DefensiveZonesMeta,
  ZonalExploiter,
  ZonalDataProvenance,
} from '@/lib/types';
import { CARD_BASE, CARD_ACCENT, PILL_BASE } from '@/lib/theme';
import {
  levelPillLabel,
  LEVEL_TEXT_CLASS,
  LEVEL_PILL_CLASS,
  ZONE_SHADE_HEX,
  zoneShadeOpacity,
  isAverageZone,
  lateralLabel,
  formatPct,
  formatFit,
  formatPenalty,
  rankOpacity,
  zonePillLabel,
  levelForZone,
  exploiterSub,
  splitVerdict,
} from '@/lib/defensive-zones';
import { PitchLines, ZONE_X, ZONE_WIDTH, ZONE_CENTER_X } from './PitchGeometry';
import { useLocale, useT } from '@/lib/i18n/LocaleProvider';
import { translate } from '@/lib/i18n/dictionary';
import type { Locale } from '@/lib/i18n/locale';

/** Frontal band under the box, in SVG units (same geometry as PlayerZonesPitch). */
const FRONTAL_Y = 176;
const FRONTAL_H = 130;
const VIEW_H_WITH_FRONTAL = 316;
// One number per cell: its baseline sits where the old two-line reading (big % + one-decimal twin) was centred.
const IN_BOX_READING_Y = 142;
const FRONTAL_READING_DROP = 10;

/** Header pill follows the opportunity coding; never a warning colour. */
function headerPillClass(strength: DefensiveZonesMeta['weakness_strength']): string {
  if (strength === 'none') return LEVEL_PILL_CLASS.cool;
  if (strength === 'marginal') return LEVEL_PILL_CLASS.warm;
  return LEVEL_PILL_CLASS.opp;
}

interface Props {
  data: DefensiveZonesMeta;
}


export default function DefensiveZonesCard({ data }: Props) {
  const { opponent, weakness_label, verdict, zones, exploiters } = data;
  const t = useT();
  const { locale } = useLocale();
  const frontal = data.frontal_zones ?? [];
  const hasFrontal = frontal.length > 0;
  const provenance = data.data_provenance ?? null;
  const scope = scopeLabel(data.team_filter ?? null, opponent, locale);
  const fixtureGroups =
    data.team_filter?.source === 'fixtures' ? groupExploitersByFixture(exploiters) : null;
  // i91: absent/true means a real get_zonal_opportunity result (exploiters
  // may legitimately be []); false means "zonas débiles" alone was asked --
  // no player table was ever looked for, so none renders, not an empty one.
  const hasExploiters = data.has_exploiters !== false;

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.turquoise.border}`}>
      <div className="relative z-10 p-5">
        {/* Header — kicker + team, opportunity pill */}
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <div className="min-w-0 flex flex-col gap-0.5">
            <span className="text-[11px] font-extrabold uppercase tracking-[0.13em] text-bf-turquoise whitespace-nowrap">
              {t('z.kicker')}
            </span>
            <span className="block truncate text-base font-black tracking-tight text-bf-text">
              {opponent}
            </span>
          </div>
          <span
            className={`${PILL_BASE} flex-shrink-0 text-[10px] font-extrabold ${headerPillClass(data.weakness_strength)} whitespace-nowrap`}
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
            {t('z.legend')}
          </span>
        </p>

        {/* Season stamp (i74) — what season these numbers describe */}
        {provenance && <ProvenanceStamp provenance={provenance} />}

        {/* Pitch view — penalty box with the three zone thirds (and the frontal
            band when present) shaded by opportunity; each zone's reading lives inside its region */}
        <div className="relative mx-auto w-full max-w-[420px]">
          <svg
            viewBox={`0 0 360 ${hasFrontal ? VIEW_H_WITH_FRONTAL : 210}`}
            className="block h-auto w-full"
            role="img"
            aria-label={[
              ...zones.map((z) => zoneAria(z, hasFrontal ? t('z.aria.box') : '', locale)),
              ...frontal.map((z) => zoneAria(z, t('z.aria.edge'), locale)),
            ].join(' · ')}
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
            {hasFrontal && (
              <rect x="30" y={FRONTAL_Y} width="300" height={FRONTAL_H} fill="none" stroke="rgba(255,255,255,.10)" strokeWidth="1.5" strokeDasharray="4 5" />
            )}
            {frontal.map((zone, i) => (
              <rect
                key={`f-${zone.lateral}`}
                data-testid={`zone-shade-frontal-${zone.lateral}`}
                x={ZONE_X[i]}
                y={FRONTAL_Y}
                width={ZONE_WIDTH}
                height={FRONTAL_H}
                fill={ZONE_SHADE_HEX[zone.opportunity_level]}
                fillOpacity={zoneShadeOpacity(
                  zone.opportunity_level,
                  zone.pct_over_avg,
                )}
              />
            ))}
            <PitchLines />
            {frontal.map((zone, i) => (
              <ZoneReading key={`ft-${zone.lateral}`} zone={zone} cx={ZONE_CENTER_X[i]} y={FRONTAL_Y + 76} />
            ))}
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
                  {t('z.avg')}
                </text>
              ) : (
                <text
                  key={zone.lateral}
                  x={ZONE_CENTER_X[i]}
                  y={IN_BOX_READING_Y}
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
              ),
            )}
          </svg>
        </div>

        {/* Per-zone labels + opportunity pills (the % lives in the box now) */}
        <ZoneLabels zones={zones} caption={hasFrontal ? t('z.insideBox') : null} />
        {hasFrontal && <ZoneLabels zones={frontal} caption={t('z.edgeBox')} />}
        <div className="mb-4 text-center text-[10.5px] text-bf-gray/50">
          {t('z.axis')}
        </div>

        {/* "Quién lo explota" — zone-fit table. i91: omitted entirely (not
            even the empty state) when this turn never asked about players
            — hasExploiters is false only for a weakness-only card. */}
        {hasExploiters && (
          exploiters.length > 0 ? (
            <div className="mb-4 overflow-hidden rounded-[10px] border border-white/[0.08]">
              <div className="flex items-center justify-between border-b border-white/[0.08] bg-white/[0.02] px-3 py-2">
                <span className="text-[11px] font-extrabold uppercase tracking-[0.08em] text-bf-text">
                  {t('z.who')}
                  {scope && (
                    <span
                      data-testid="zonal-scope"
                      className="ml-2 normal-case tracking-normal text-bf-turquoise"
                    >
                      · {scope}
                    </span>
                  )}
                </span>
                <span className="text-[10.5px] text-bf-gray/60">
                  {data.weakness_strength === 'marginal' ? (
                    <span data-testid="zonal-marginal" className="text-bf-gold">
                      {t('z.marginal')}{' '}
                    </span>
                  ) : null}
                  {t('z.fitTo')}
                </span>
              </div>
              <div className="grid grid-cols-[1.4rem_1fr_auto_auto] gap-3 border-b border-white/[0.06] px-3 py-1.5 text-[9.5px] font-extrabold uppercase tracking-[0.06em] text-bf-gray/60">
                <span>#</span>
                <span>{t('z.col.player')}</span>
                <span className="text-center">{t('z.col.zone')}</span>
                <span className="text-right">{t('z.col.fit')}</span>
              </div>
              {fixtureGroups ? (
                fixtureGroups.map((group) => (
                  <div key={`${group.gameweek}-${group.teamShort}`}>
                    <div
                      data-testid="zonal-fixture-group"
                      className="border-b border-white/[0.06] bg-white/[0.015] px-3 py-1.5 text-[10.5px] font-bold text-bf-gray/70"
                    >
                      {fixtureGroupLabel(group.gameweek, group.teamShort, group.isHome, opponent, locale)}
                    </div>
                    {group.rows.map((e, i) => (
                      <ExploiterRow key={e.rank} exploiter={e} striped={i % 2 === 0} data={data} />
                    ))}
                  </div>
                ))
              ) : (
                exploiters.map((e, i) => (
                  <ExploiterRow key={e.rank} exploiter={e} striped={i % 2 === 0} data={data} />
                ))
              )}
            </div>
          ) : (
            <div
              data-testid="zonal-no-exploiters"
              className="mb-4 rounded-[10px] border border-white/[0.08] px-3 py-2.5 text-[11px] text-bf-gray/60"
            >
              {t('z.noExploiters')}
            </div>
          )
        )}

        {/* Footer — penalty context + IA badge */}
        <div className="flex flex-wrap items-center justify-between gap-2.5 border-t border-white/[0.07] pt-3.5">
          <span className="text-[11px] text-bf-gray/60">
            {t('z.penalties')}{' '}
            <span className="font-bold text-bf-gray">
              {t('z.xgaPerGame', { value: formatPenalty(data.penalty_xga_per_game) })}
            </span>
          </span>
          {data.ai_active && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-bf-turquoise/40 bg-bf-turquoise/10 px-3 py-1 text-[11px] font-bold uppercase tracking-[0.1em] text-bf-turquoise">
              <span
                aria-hidden="true"
                className="h-1.5 w-1.5 rounded-full bg-bf-turquoise"
              />
              {t('z.ai')}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function zoneAria(z: DefensiveZoneCell, prefix: string, locale: Locale): string {
  return `${prefix}${lateralLabel(z.lateral, locale)}: ${
    isAverageZone(z.pct_over_avg) ? translate(locale, 'z.avg') : formatPct(z.pct_over_avg)
  }`;
}

/** The % (or the muted '≈ media') of one frontal cell: one number, one place. */
function ZoneReading({ zone, cx, y }: { zone: DefensiveZoneCell; cx: number; y: number }) {
  const t = useT();
  if (isAverageZone(zone.pct_over_avg)) {
    return (
      <text
        x={cx}
        y={y + 4}
        textAnchor="middle"
        fill="#ABA9AC"
        fillOpacity={0.55}
        style={{ fontSize: 13, fontWeight: 700 }}
      >
        {t('z.avg')}
      </text>
    );
  }
  return (
    <text
      x={cx}
      y={y + FRONTAL_READING_DROP}
      textAnchor="middle"
      fill={ZONE_SHADE_HEX[zone.opportunity_level]}
      style={{ fontSize: 28, fontWeight: 900, letterSpacing: '-1px' }}
    >
      {formatPct(zone.pct_over_avg)}
    </text>
  );
}

/** Per-zone label + opportunity pill, one row of three. */
function ZoneLabels({ zones, caption }: { zones: DefensiveZoneCell[]; caption: string | null }) {
  const { locale } = useLocale();
  return (
    <>
      {caption && (
        <div className="mt-2 text-center text-[10px] font-bold uppercase tracking-[0.1em] text-bf-gray/50">
          {caption}
        </div>
      )}
      <div className="mb-1.5 mt-2 grid grid-cols-3 gap-2">
        {zones.map((zone) => (
          <div
            key={zone.lateral}
            className="flex flex-col items-center gap-1.5 text-center"
          >
            <span
              className={`text-[10.5px] font-extrabold uppercase tracking-[0.08em] ${LEVEL_TEXT_CLASS[zone.opportunity_level]}`}
            >
              {lateralLabel(zone.lateral, locale)}
            </span>
            <span
              className={`${PILL_BASE} text-[10px] font-extrabold whitespace-nowrap ${LEVEL_PILL_CLASS[zone.opportunity_level]}`}
            >
              {levelPillLabel(zone.opportunity_level, locale)}
            </span>
          </div>
        ))}
      </div>
    </>
  );
}

/**
 * The i74 season stamp. Always rendered when the payload carries provenance:
 * a muted caption for live-season data, a gold notice for anything else. The
 * text is the backend's `label` verbatim (it already carries the ⚠) so the
 * card and the plain-text zonal answers state the same fact the same way.
 */
export function ProvenanceStamp({ provenance }: { provenance: ZonalDataProvenance }) {
  const stale = provenance.status !== 'current';
  return (
    <p
      data-testid="zonal-provenance"
      data-status={provenance.status}
      className={
        stale
          ? 'mb-3.5 rounded-[8px] border border-bf-gold/35 bg-bf-gold/[0.07] px-3 py-2 text-[11.5px] font-semibold leading-snug text-bf-gold'
          : 'mb-3.5 text-[10.5px] font-medium tracking-[0.02em] text-bf-gray/55'
      }
    >
      {provenance.label}
    </p>
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
  const { locale } = useLocale();
  const level = levelForZone(exploiter.zone, data.zones, data.frontal_zones ?? []);
  const numberClass = LEVEL_TEXT_CLASS[level];
  const opacity = rankOpacity(exploiter.rank);
  const sub = exploiterSub(exploiter.team_short, exploiter.position, exploiter.club_note, locale);

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
      <span className="min-w-0">
        <span className="block truncate">
          <strong className="font-bold text-white">{exploiter.web_name}</strong>
          {sub && <span className="ml-1 text-[11px] text-bf-gray">{sub}</span>}
        </span>
        <EvidenceLine exploiter={exploiter} />
      </span>
      <span className="text-center">
        <span
          className={`${PILL_BASE} text-[10px] font-extrabold whitespace-nowrap ${LEVEL_PILL_CLASS[level]}`}
        >
          {zonePillLabel(exploiter.zone, locale)}
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


/**
 * i85–i87: "Liverpool" / "Liverpool · según tu pregunta" when the table is
 * scoped to one team; null on the league-wide answer. Uses the resolved store
 * name (`matched`), never the raw request, so a filter that resolved to
 * nothing is not presented as a scope.
 */
function scopeLabel(tf: DefensiveZonesMeta['team_filter'], opponent: string, locale: Locale): string | null {
  if (!tf) return null;
  // i90: the scope wasn't named -- it came from opponent's own calendar.
  if (tf.source === 'fixtures' && tf.fixture_window) {
    return translate(locale, 'z.scope.fixtures', { opponent, gw: tf.fixture_window.to_gw });
  }
  if (!tf.matched) return null;
  // i89: `matched` is already the joined display ("Arsenal, Liverpool, Manchester City").
  return tf.source === 'inferred' ? translate(locale, 'z.scope.inferred', { matched: tf.matched }) : tf.matched;
}

/**
 * i90: buckets the (already fit-ranked) exploiter rows by fixture so the
 * table can render "J5 · BUR visita a Fulham" section headers. Keyed by
 * (gameweek, team) — NOT gameweek alone: a genuine double gameweek can have
 * the weak team play two DIFFERENT rivals in the same numbered gameweek
 * (found in review — gameweek-only keying would merge both rivals' rows
 * under one team's header, misattributing team and home/away for the
 * other). Groups are ordered by gameweek, then by first appearance in the
 * already-ranked `exploiters` array.
 */
function groupExploitersByFixture(exploiters: ZonalExploiter[]): {
  gameweek: number;
  teamShort: string;
  isHome: boolean;
  rows: ZonalExploiter[];
}[] {
  const byKey = new Map<string, { gameweek: number; teamShort: string; isHome: boolean; rows: ZonalExploiter[] }>();
  const order: string[] = [];
  for (const e of exploiters) {
    if (e.gameweek == null) continue;
    const key = `${e.gameweek}::${e.team_short}`;
    if (!byKey.has(key)) {
      byKey.set(key, { gameweek: e.gameweek, teamShort: e.team_short, isHome: !!e.is_home, rows: [] });
      order.push(key);
    }
    byKey.get(key)!.rows.push(e);
  }
  // Array.prototype.sort is stable (ES2019+), so ties keep first-appearance order.
  return order.map((key) => byKey.get(key)!).sort((a, b) => a.gameweek - b.gameweek);
}

/** "J5 · BUR visita a Fulham" / "J6 · AVL recibe a Fulham" -- always names
 * who has the ball (subject) and never bare "(L)/(V)". `isHome` is already
 * attacker-perspective by the time it reaches this component. */
function fixtureGroupLabel(
  gameweek: number,
  teamShort: string,
  isHome: boolean,
  opponent: string,
  locale: Locale,
): string {
  return translate(locale, isHome ? 'z.group.home' : 'z.group.away', { gw: gameweek, team: teamShort, opponent });
}

const ORIGIN_KEYS = {
  open_play: 'z.origin.open_play',
  set_piece: 'z.origin.set_piece',
  mixed: 'z.origin.mixed',
} as const satisfies Record<NonNullable<ZonalExploiter['origin']>, string>;

/**
 * i87/i88: the evidence under a player's name — how many shots they struck
 * in the ranked zone, where that xG came from, and a thin-sample flag. A
 * centre-back ranked on two corner headers must read as "2 tiros en zona ·
 * balón parado", not as a winger. Renders nothing for payloads predating
 * these fields.
 */
function EvidenceLine({ exploiter }: { exploiter: ZonalExploiter }) {
  const t = useT();
  const parts: string[] = [];
  if (exploiter.zone_share != null) {
    // i89: how much of THIS player's xG lands in the ranked zone -- a 27%
    // fit (Palmer, left) must read differently from a 90% one (Isak, centre).
    parts.push(t('z.ev.share', { pct: Math.round(exploiter.zone_share * 100) }));
  }
  if (exploiter.zone_shots != null) {
    parts.push(t(exploiter.zone_shots === 1 ? 'z.ev.shot' : 'z.ev.shots', { n: exploiter.zone_shots }));
  }
  if (exploiter.origin) parts.push(t(ORIGIN_KEYS[exploiter.origin]));
  if (parts.length === 0 && exploiter.sample !== 'thin') return null;
  const setPiece = exploiter.origin === 'set_piece';
  return (
    <span
      data-testid="zonal-evidence"
      data-origin={exploiter.origin ?? undefined}
      data-sample={exploiter.sample ?? undefined}
      className={`mt-0.5 block truncate text-[10px] ${
        setPiece ? 'text-bf-gold' : 'text-bf-gray/60'
      }`}
    >
      {parts.join(' · ')}
      {exploiter.sample === 'thin' && (
        <span className="ml-1.5 rounded-full border border-bf-gold/40 px-1.5 py-px text-[9px] font-bold uppercase tracking-[0.06em] text-bf-gold">
          {t('z.ev.thin')}
        </span>
      )}
    </span>
  );
}
