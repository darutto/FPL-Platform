/**
 * WcPlayerInfoCard — structured rendering for get_player_info results.
 *
 * Rendered beneath final_text when response.outcome === 'ok' and
 * response.players_info is non-empty (see lib/wc-intent-renderer.ts
 * selectWcIntentView). One entry = '/jugador' single-player profile; two
 * (or more) entries = '/comparar' side-by-side comparison, with the better
 * value per stat highlighted.
 */
import type { WcPlayerInfoRow, WcPlayer2022Stats } from '@/lib/wc-types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from '@/components/intents/CardOrnaments';

interface Props {
  data: WcPlayerInfoRow[];
  wc2022Stats?: WcPlayer2022Stats[] | null;
}

/** Accent-insensitive, lowercase, whitespace-trimmed — for loose name matching
 *  between FIFA Fantasy player names (players_info) and API-Football names
 *  (wc2022Stats), which may differ in form (e.g. "Messi" vs "Lionel Messi"). */
function normalizeName(value: string): string {
  return value
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .trim()
    .toLowerCase();
}

/** Find the WC2022 entry (if any) belonging to a players_info player, by
 *  shared name token (>= 3 chars) or substring match. */
function findWc2022(player: WcPlayerInfoRow, stats: WcPlayer2022Stats[] | null | undefined): WcPlayer2022Stats | undefined {
  if (!stats || stats.length === 0) return undefined;
  const playerKey = normalizeName(player.player);
  const playerTokens = new Set(playerKey.split(/\s+/).filter((t) => t.length >= 3));
  return stats.find((s) => {
    const statKey = normalizeName(s.name);
    if (statKey === playerKey) return true;
    const statTokens = statKey.split(/\s+/).filter((t) => t.length >= 3);
    if (statTokens.some((t) => playerTokens.has(t))) return true;
    return playerKey.length >= 4 && statKey.includes(playerKey);
  });
}

interface StatDef {
  key: keyof WcPlayerInfoRow;
  label: string;
  format?: (v: number) => string;
}

const STATS: StatDef[] = [
  { key: 'total_points', label: 'Pts fantasy' },
  { key: 'avg_points', label: 'Promedio' },
  { key: 'form', label: 'Forma' },
  { key: 'goals', label: 'Goles' },
  { key: 'assists', label: 'Asistencias' },
  { key: 'price', label: 'Valor', format: (v) => v.toFixed(1) },
];

export default function WcPlayerInfoCard({ data, wc2022Stats }: Props) {
  if (data.length === 0) return null;
  if (data.length === 1) return <SinglePlayer player={data[0]} wc2022Stats={wc2022Stats} />;
  return <ComparisonCard players={data} wc2022Stats={wc2022Stats} />;
}

function SinglePlayer({ player, wc2022Stats }: { player: WcPlayerInfoRow; wc2022Stats?: WcPlayer2022Stats[] | null }) {
  const wc2022 = findWc2022(player, wc2022Stats);
  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.turquoise.border}`}>
      <div className="relative overflow-hidden px-4 py-2.5 border-b border-bf-turquoise/20">
        <TriangleField color={ACCENT_HEX.turquoise} corner="tr" />
        <div className="relative z-10 flex items-center justify-between gap-2">
          <span className="text-xs font-extrabold text-white uppercase tracking-wide truncate">
            {player.player}
          </span>
          <span className="text-[10px] font-bold text-bf-turquoise uppercase tracking-wide flex-shrink-0">
            {player.position}
          </span>
        </div>
        {player.team && <div className="relative z-10 text-xs text-bf-gray mt-0.5">{player.team}</div>}
      </div>

      <div className="grid grid-cols-3 gap-px bg-white/5">
        {STATS.map((stat) => (
          <div key={stat.key} className="bg-bf-surface/80 px-3 py-2.5 text-center">
            <div className="font-display text-lg tracking-tighter text-bf-turquoise">
              {formatStat(player, stat)}
            </div>
            <div className="text-[10px] text-bf-gray uppercase tracking-wide mt-0.5">{stat.label}</div>
          </div>
        ))}
      </div>

      {wc2022 && <Wc2022Section stats={wc2022} />}
    </div>
  );
}

function Wc2022Section({ stats }: { stats: WcPlayer2022Stats }) {
  return (
    <div className="border-t border-white/5 px-4 py-2.5">
      <div className="text-[10px] font-bold text-bf-gray uppercase tracking-wide mb-1.5">
        Mundial 2022
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-bf-text">
        <span>{stats.appearances} partidos</span>
        <span>{stats.minutes}&apos;</span>
        <span>{stats.goals} goles</span>
        <span>{stats.assists} asistencias</span>
        {stats.saves > 0 && <span>{stats.saves} atajadas</span>}
        {(stats.yellow_cards > 0 || stats.red_cards > 0) && (
          <span>
            {stats.yellow_cards > 0 && `${stats.yellow_cards} amarillas`}
            {stats.yellow_cards > 0 && stats.red_cards > 0 && ', '}
            {stats.red_cards > 0 && `${stats.red_cards} rojas`}
          </span>
        )}
        {stats.avg_rating != null && <span>Valoración {stats.avg_rating.toFixed(2)}</span>}
      </div>
    </div>
  );
}

function ComparisonCard({ players, wc2022Stats }: { players: WcPlayerInfoRow[]; wc2022Stats?: WcPlayer2022Stats[] | null }) {
  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.cyan.border}`}>
      <div className="relative overflow-hidden px-4 py-2.5 border-b border-bf-cyan/20">
        <TriangleField color={ACCENT_HEX.cyan} corner="tr" />
        <span className="relative z-10 text-xs font-extrabold text-white uppercase tracking-wide">
          Comparativa
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-bf-gray text-[10px] uppercase tracking-wide">
              <th className="text-left px-4 py-1.5 font-bold">&nbsp;</th>
              {players.map((p) => (
                <th key={p.player} className="px-3 py-1.5 font-bold text-white text-center">
                  <div className="truncate max-w-[8rem]">{p.player}</div>
                  {p.team && <div className="text-[10px] text-bf-gray font-normal">{p.team}</div>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {STATS.map((stat, idx) => {
              const values = players.map((p) => p[stat.key] as number);
              const best = Math.max(...values);
              return (
                <tr key={stat.key} className={idx % 2 === 0 ? 'bg-white/[0.035]' : ''}>
                  <td className="px-4 py-1.5 font-bold text-bf-gray uppercase tracking-wide text-[10px]">
                    {stat.label}
                  </td>
                  {players.map((p, i) => {
                    const value = values[i];
                    const isBest = value === best && best > 0 && players.length > 1;
                    return (
                      <td
                        key={p.player}
                        className={`px-3 py-1.5 text-center font-display tracking-tighter ${
                          isBest ? 'text-bf-cyan' : 'text-bf-text'
                        }`}
                      >
                        {formatStat(p, stat)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
            <tr className="bg-white/[0.035]">
              <td className="px-4 py-1.5 font-bold text-bf-gray uppercase tracking-wide text-[10px]">
                Posición
              </td>
              {players.map((p) => (
                <td key={p.player} className="px-3 py-1.5 text-center text-bf-text">
                  {p.position}
                </td>
              ))}
            </tr>
            <Wc2022Rows players={players} wc2022Stats={wc2022Stats} />
          </tbody>
        </table>
      </div>
    </div>
  );
}

const WC2022_STATS: { key: keyof WcPlayer2022Stats; label: string }[] = [
  { key: 'appearances', label: 'Partidos M22' },
  { key: 'goals', label: 'Goles M22' },
  { key: 'assists', label: 'Asist. M22' },
  { key: 'minutes', label: 'Minutos M22' },
];

function Wc2022Rows({ players, wc2022Stats }: { players: WcPlayerInfoRow[]; wc2022Stats?: WcPlayer2022Stats[] | null }) {
  const matched = players.map((p) => findWc2022(p, wc2022Stats));
  if (matched.every((m) => !m)) return null;
  return (
    <>
      {WC2022_STATS.map((stat, idx) => {
        const values = matched.map((m) => (m ? (m[stat.key] as number) : null));
        const best = Math.max(...values.filter((v): v is number => v != null));
        return (
          <tr key={stat.key} className={idx % 2 === 0 ? 'bg-white/[0.035]' : ''}>
            <td className="px-4 py-1.5 font-bold text-bf-gray uppercase tracking-wide text-[10px]">
              {stat.label}
            </td>
            {players.map((p, i) => {
              const value = values[i];
              const isBest = value != null && value === best && best > 0 && players.length > 1;
              return (
                <td
                  key={p.player}
                  className={`px-3 py-1.5 text-center font-display tracking-tighter ${
                    isBest ? 'text-bf-cyan' : 'text-bf-text'
                  }`}
                >
                  {value != null ? String(value) : '—'}
                </td>
              );
            })}
          </tr>
        );
      })}
    </>
  );
}

function formatStat(player: WcPlayerInfoRow, stat: StatDef): string {
  const value = player[stat.key] as number;
  return stat.format ? stat.format(value) : String(value);
}
