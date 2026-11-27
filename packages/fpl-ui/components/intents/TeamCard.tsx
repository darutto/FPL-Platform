'use client';

/**
 * TeamCard — one club's season, as the backend computed it (team_card.py). Rendered for intent 'team_card'
 * (a bare club name, or the club chip under a player card).
 *
 * - The table is OURS, computed from finished results: it is labelled so.
 * - A figure the backend could not measure is «—» with the missing gameweeks, never a partial sum.
 * - The next fixtures are the player card's strip (same bands, same plan gating), with an axis switch since a
 *   club has both; it starts on attack, as the /fixtures calendar does.
 * - Each section fails on its own.
 *
 * Look: nothing here is its own style. Shell, header, hero and stat grid follow PlayerCard; section headings
 * follow PlayerZonasSection/PlayerSignals; both tables follow StatComparisonTable; result pills use theme's
 * PILL_BASE and tones; the hero, stat grid and data stamp are the shared blocks.
 */
import HeroStat from '@/components/blocks/HeroStat';
import StatGrid from '@/components/blocks/StatGrid';
import { useState } from 'react';
import type { FixtureAxis, TeamCardBody, TeamCardMetric, TeamCardStats } from '@/lib/types';
import { ACCENT_HEX, CARD_ACCENT, CARD_BASE, GENERIC_TONE_CLASSES, PILL_BASE } from '@/lib/theme';
import { useLocale, useT } from '@/lib/i18n/LocaleProvider';
import { axisLabel } from '@/lib/fixture-outlook-format';
import type { DictKey } from '@/lib/i18n/dictionary';
import PillSwitcher from '@/components/chat/PillSwitcher';
import { PlayerFixtureStrip } from './PlayerFixtureStrip';
import { FingerprintWaves } from './CardOrnaments';
import ProvenanceStamp from '@/components/blocks/ProvenanceStamp';

const ACCENT = 'turquoise' as const;

const STAT_ROWS: { key: keyof TeamCardStats['season']; label: DictKey; decimals: number }[] = [
  { key: 'goals_for', label: 'tc.goalsFor', decimals: 0 },
  { key: 'xg_for', label: 'tc.xgFor', decimals: 2 },
  { key: 'goals_against', label: 'tc.goalsAgainst', decimals: 0 },
  { key: 'xg_against', label: 'tc.xgAgainst', decimals: 2 },
];

const RESULT_TONE: Record<'W' | 'D' | 'L', keyof typeof GENERIC_TONE_CLASSES> = { W: 'good', D: 'neutral', L: 'bad' };

const RESULT_KEY: Record<'W' | 'D' | 'L', DictKey> = { W: 'tc.won.short', D: 'tc.drawn.short', L: 'tc.lost.short' };

/** PlayerZonasSection / PlayerSignals heading. */
const HEADING = 'text-[10px] font-extrabold uppercase tracking-wider text-bf-gray';
/** StatComparisonTable header cell, body cell and row label. */
const TH = 'px-2 py-1.5 text-[10px] font-extrabold uppercase tracking-wide text-bf-gray';
const TD = 'px-2 py-1.5 text-right align-top font-display tabular-nums tracking-tighter';
const ROW_LABEL = 'px-2 py-1.5 text-left align-top font-normal text-bf-text/80';
const banded = (i: number) => (i % 2 === 0 ? 'bg-white/[0.035]' : '');

export default function TeamCard({ data }: { data: TeamCardBody }) {
  const t = useT();
  const { locale } = useLocale();
  const [axis, setAxis] = useState<FixtureAxis>('attack');
  const { team, table, stats, fixtures, players, last_finished_gameweek: lastGw, data_provenance: provenance } =
    data.card;
  const missing = (title: DictKey) => (
    <p className="border-t border-white/10 pt-2.5 text-[11px] text-bf-gray">
      {t(title)}: {t('tc.unavailable')}
    </p>
  );

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT[ACCENT].border}`} data-testid="team-card">
      <FingerprintWaves color={ACCENT_HEX[ACCENT]} corner="br" />
      <div className="relative z-10 space-y-3 p-4">
        <div className="min-w-0">
          <span className="block truncate text-lg font-extrabold text-white">{team.name}</span>
          <span className="text-xs text-bf-gray">
            {team.short_name}
            {lastGw != null && ` · ${t('tc.through', { gw: t('tc.gw', { gw: lastGw }) })}`}
          </span>
        </div>

        {table ? (
          <>
            <div data-testid="team-card-hero">
              <HeroStat
                size="score"
                value={table.points}
                suffix={t('unit.pts')}
                caption={t('tc.positionOf', { position: table.position, teams: table.teams })}
                toneClass="text-bf-turquoise"
              />
            </div>
            <StatGrid
              columns={3}
              stats={[
                { label: t('tc.played'), value: String(table.played) },
                { label: t('tc.record'), value: `${table.won}-${table.drawn}-${table.lost}` },
                { label: t('tc.goalDiff'), value: table.gd > 0 ? `+${table.gd}` : String(table.gd) },
              ]}
            />
            {table.form.length > 0 && (
              <div className="space-y-1" data-testid="team-card-form">
                <h3 className={HEADING}>{t('tc.form')}</h3>
                <div className="flex flex-wrap items-center gap-1.5">
                  {table.form.map((m) => (
                    <span
                      key={`${m.gameweek}-${m.opponent_short}-${m.is_home}`}
                      title={`${t('tc.gw', { gw: m.gameweek ?? '—' })} · ${m.opponent_short} ${m.goals_for}-${m.goals_against}`}
                      className={`${PILL_BASE} ${GENERIC_TONE_CLASSES[RESULT_TONE[m.result]]}`}
                    >
                      {t(RESULT_KEY[m.result])} {m.goals_for}-{m.goals_against}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <p className="text-[10px] text-bf-gray">{t('tc.computed')}</p>
          </>
        ) : (
          missing('tc.table')
        )}

        {stats ? (
          <div className="border-t border-white/10 pt-1">
            <table className="w-full border-collapse text-xs" data-testid="team-card-stats">
              <thead>
                <tr className="border-b border-white/10">
                  <th scope="col" className={`${TH} text-left`}>{t('tc.stats')}</th>
                  <th scope="col" className={`${TH} text-right`}>{t('tc.season')}</th>
                  <th scope="col" className={`${TH} text-right`}>{t('tc.lastN', { n: stats.recent_gameweeks })}</th>
                </tr>
              </thead>
              <tbody>
                {STAT_ROWS.map((row, i) => (
                  <tr key={row.key} className={banded(i)}>
                    <th scope="row" className={ROW_LABEL}>{t(row.label)}</th>
                    <StatCell metric={stats.season[row.key]} decimals={row.decimals} />
                    <StatCell metric={stats.recent[row.key]} decimals={row.decimals} />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          missing('tc.stats')
        )}

        {fixtures ? (
          <div className="space-y-2 border-t border-white/10 pt-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className={HEADING}>{t('tc.fixtures')}</h3>
              {fixtures.next.length > 0 && (
                <PillSwitcher<FixtureAxis>
                  items={(['attack', 'defence'] as const).map((key) => ({ key, label: axisLabel(key, locale) }))}
                  value={axis}
                  onChange={setAxis}
                  label={t('tc.axis')}
                  className="w-fit"
                />
              )}
            </div>
            {fixtures.next.length > 0 && (
              // The strip draws its own top rule for the player card; this section already has one.
              <div className="[&>div]:border-t-0 [&>div]:pt-0">
                <PlayerFixtureStrip fixtures={fixtures.next} teamShort={team.short_name} position="" observedAxis={axis} />
              </div>
            )}
            {fixtures.blank_gameweeks.length > 0 && (
              <p className="text-[11px] text-bf-gold" data-testid="team-card-blanks">
                {t('tc.noMatch', { gws: gwList(fixtures.blank_gameweeks, t) })}
              </p>
            )}
          </div>
        ) : (
          missing('tc.fixtures')
        )}

        {players ? (
          <div className="space-y-1 border-t border-white/10 pt-2.5" data-testid="team-card-players">
            <h3 className={HEADING}>{t('tc.players')}</h3>
            <table className="w-full table-fixed border-collapse text-xs">
              <thead>
                <tr className="border-b border-white/10">
                  <th scope="col" className={`${TH} text-left`}>{t('tc.player')}</th>
                  <th scope="col" className={`${TH} w-12 text-left`}>{t('tc.pos')}</th>
                  <th scope="col" className={`${TH} w-16 text-right`}>{t('tc.price')}</th>
                  <th scope="col" className={`${TH} w-16 text-right`}>{t('tc.points')}</th>
                </tr>
              </thead>
              <tbody>
                {players.map((p, i) => (
                  <tr key={p.id} className={banded(i)}>
                    <th scope="row" className={`${ROW_LABEL} truncate`}>{p.web_name}</th>
                    <td className="px-2 py-1.5 text-left text-bf-gray">{p.position}</td>
                    <td className={`${TD} text-bf-text/70`}>{p.price == null ? '—' : `£${p.price.toFixed(1)}m`}</td>
                    <td className={`${TD} text-white`}>{p.total_points}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          missing('tc.players')
        )}

        {provenance && (
          <div className="[&>p]:mb-0">
            <ProvenanceStamp provenance={provenance} />
          </div>
        )}
      </div>
    </div>
  );
}

type T = ReturnType<typeof useT>;

function gwList(gameweeks: number[], t: T): string {
  return gameweeks.map((gw) => t('tc.gw', { gw })).join(', ');
}

/** Total over per-match. A range (the source disagrees with itself) is shown as a range, in both. */
function StatCell({ metric, decimals }: { metric: TeamCardMetric; decimals: number }) {
  const t = useT();
  if (metric.total == null || metric.per_match == null) {
    return (
      <td className={`${TD} text-bf-gray`}>
        —
        {metric.missing_gameweeks.length > 0 && (
          <span className="block font-sans text-[10px] tracking-normal">
            {t('tc.missing', { gws: gwList(metric.missing_gameweeks, t) })}
          </span>
        )}
      </td>
    );
  }
  const total = metric.range
    ? `${metric.range[0].toFixed(decimals)}–${metric.range[1].toFixed(decimals)}`
    : metric.total.toFixed(decimals);
  const perMatch = metric.per_match_range
    ? `${metric.per_match_range[0].toFixed(2)}–${metric.per_match_range[1].toFixed(2)}`
    : metric.per_match.toFixed(2);
  return (
    <td className={`${TD} text-white`}>
      {total}
      <span className="block font-sans text-[10px] tracking-normal text-bf-gray">
        {perMatch} {t('tc.perMatch')}
      </span>
    </td>
  );
}
