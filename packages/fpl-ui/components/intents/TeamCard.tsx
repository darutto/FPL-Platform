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
 */
import { useState } from 'react';
import type { FixtureAxis, TeamCardBody, TeamCardMetric, TeamCardStats } from '@/lib/types';
import { CARD_ACCENT, CARD_BASE } from '@/lib/theme';
import { useLocale, useT } from '@/lib/i18n/LocaleProvider';
import { axisLabel } from '@/lib/fixture-outlook-format';
import type { DictKey } from '@/lib/i18n/dictionary';
import PillSwitcher from '@/components/chat/PillSwitcher';
import { PlayerFixtureStrip } from './PlayerFixtureStrip';

const ACCENT = 'turquoise' as const;

const STAT_ROWS: { key: keyof TeamCardStats['season']; label: DictKey; decimals: number }[] = [
  { key: 'goals_for', label: 'tc.goalsFor', decimals: 0 },
  { key: 'xg_for', label: 'tc.xgFor', decimals: 2 },
  { key: 'goals_against', label: 'tc.goalsAgainst', decimals: 0 },
  { key: 'xg_against', label: 'tc.xgAgainst', decimals: 2 },
];

const RESULT_CLASS: Record<'W' | 'D' | 'L', string> = {
  W: 'bg-bf-turquoise text-bf-ink',
  D: 'bg-white/15 text-bf-text',
  L: 'bg-bf-coral text-bf-ink',
};

const RESULT_KEY: Record<'W' | 'D' | 'L', DictKey> = { W: 'tc.won.short', D: 'tc.drawn.short', L: 'tc.lost.short' };

export default function TeamCard({ data }: { data: TeamCardBody }) {
  const t = useT();
  const { locale } = useLocale();
  const [axis, setAxis] = useState<FixtureAxis>('attack');
  const { team, table, stats, fixtures, players, last_finished_gameweek: lastGw, data_provenance: provenance } =
    data.card;
  const missing = (title: DictKey) => (
    <p className="text-[11px] text-bf-gray">
      {t(title)}: {t('tc.unavailable')}
    </p>
  );

  return (
    <div className={`mt-3 ${CARD_BASE} ${CARD_ACCENT[ACCENT].border}`} data-testid="team-card">
      <div className="relative z-10 space-y-3 p-4">
        <header className="flex items-baseline justify-between gap-3">
          <h3 className={`font-display text-lg leading-none ${CARD_ACCENT[ACCENT].heading}`}>{team.name}</h3>
          <span className="text-[11px] font-bold uppercase tracking-wide text-bf-gray">{team.short_name}</span>
        </header>

        {table ? (
          <div className="space-y-2">
            <div className="grid grid-cols-4 gap-2">
              <Figure label={t('tc.position')} value={`${table.position}/${table.teams}`} />
              <Figure label={t('tc.points')} value={String(table.points)} />
              <Figure label={t('tc.record')} value={`${table.won}-${table.drawn}-${table.lost}`} />
              <Figure
                label={t('tc.goals')}
                value={`${table.gf}-${table.ga}`}
                note={table.gd > 0 ? `+${table.gd}` : String(table.gd)}
              />
            </div>
            <div className="flex items-center gap-1" data-testid="team-card-form">
              {table.form.map((m) => (
                <span
                  key={`${m.gameweek}-${m.opponent_short}-${m.is_home}`}
                  title={`${t('tc.gw', { gw: m.gameweek ?? '—' })} · ${m.opponent_short} ${m.goals_for}-${m.goals_against}`}
                  className={`inline-flex h-5 w-5 items-center justify-center rounded text-[10px] font-extrabold ${RESULT_CLASS[m.result]}`}
                >
                  {t(RESULT_KEY[m.result])}
                </span>
              ))}
            </div>
            <p className="text-[10px] text-bf-gray/80">{t('tc.computed')}</p>
          </div>
        ) : (
          missing('tc.table')
        )}

        {stats ? (
          <table className="w-full border-t border-white/10 text-sm" data-testid="team-card-stats">
            <thead>
              <tr className="text-[9px] font-bold uppercase tracking-wide text-bf-gray">
                <th className="pt-2 text-left" />
                <th className="pt-2 text-right">{t('tc.season')}</th>
                <th className="pt-2 text-right">{t('tc.lastN', { n: stats.recent_gameweeks })}</th>
              </tr>
            </thead>
            <tbody>
              {STAT_ROWS.map((row) => (
                <tr key={row.key}>
                  <th scope="row" className="py-1 text-left text-[11px] font-bold text-bf-gray">
                    {t(row.label)}
                  </th>
                  <StatCell metric={stats.season[row.key]} decimals={row.decimals} />
                  <StatCell metric={stats.recent[row.key]} decimals={row.decimals} />
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          missing('tc.stats')
        )}

        {fixtures ? (
          <div className="space-y-2">
            {fixtures.next.length > 0 && (
              <>
                <PillSwitcher<FixtureAxis>
                  items={(['attack', 'defence'] as const).map((key) => ({ key, label: axisLabel(key, locale) }))}
                  value={axis}
                  onChange={setAxis}
                  label={t('tc.axis')}
                  className="w-fit"
                />
                <PlayerFixtureStrip fixtures={fixtures.next} teamShort={team.short_name} position="" observedAxis={axis} />
              </>
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
          <ul className="space-y-1 border-t border-white/10 pt-2.5" data-testid="team-card-players">
            {players.map((p) => (
              <li key={p.id} className="flex items-baseline gap-2 text-sm">
                <span className="min-w-0 flex-1 truncate text-white">{p.web_name}</span>
                <span className="text-[10px] font-bold uppercase text-bf-gray">{p.position}</span>
                <span className="w-12 text-right text-bf-gray">{p.price == null ? '—' : `£${p.price.toFixed(1)}`}</span>
                <span className="w-14 text-right font-bold text-white">
                  {p.total_points} {t('tc.pts')}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          missing('tc.players')
        )}

        <footer className="text-[10px] text-bf-gray">
          {[provenance?.label, lastGw == null ? null : t('tc.through', { gw: t('tc.gw', { gw: lastGw }) })]
            .filter(Boolean)
            .join(' · ')}
        </footer>
      </div>
    </div>
  );
}

type T = ReturnType<typeof useT>;

function gwList(gameweeks: number[], t: T): string {
  return gameweeks.map((gw) => t('tc.gw', { gw })).join(', ');
}

function Figure({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="min-w-0">
      <div className="truncate font-display text-base leading-none tracking-tighter text-white">{value}</div>
      <div className="text-[9px] font-bold uppercase tracking-wide text-bf-gray">
        {label}
        {note && ` ${note}`}
      </div>
    </div>
  );
}

/** Total over per-match. A range (the source disagrees with itself) is shown as a range, in both. */
function StatCell({ metric, decimals }: { metric: TeamCardMetric; decimals: number }) {
  const t = useT();
  if (metric.total == null || metric.per_match == null) {
    return (
      <td className="py-1 text-right align-top text-bf-gray">
        —
        {metric.missing_gameweeks.length > 0 && (
          <span className="block text-[10px]">{t('tc.missing', { gws: gwList(metric.missing_gameweeks, t) })}</span>
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
    <td className="py-1 text-right align-top">
      <span className="font-bold text-white">{total}</span>
      <span className="block text-[10px] text-bf-gray">
        {perMatch} {t('tc.perMatch')}
      </span>
    </td>
  );
}
