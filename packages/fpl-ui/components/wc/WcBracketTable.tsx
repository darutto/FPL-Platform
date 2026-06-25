/**
 * WcBracketTable — horizontal knockout-bracket card for the World Cup
 * (get_bracket / '/brackets').
 *
 * Reproduces the Bendito Fantasy bracket design: a horizontally-scrollable
 * tree of round columns (Dieciseisavos → Final), each tie a two-row card with
 * a FIFA abbreviation chip, team name, score, and a turquoise accent on the
 * side that advanced (gold for the champion's path in the final). The
 * third-place playoff and the champion are shown in the footer.
 *
 * Data arrives pre-sorted (R32 → Final) and already locale_es-localized.
 * Sides that aren't decided yet carry a Spanish slot description
 * (home_source/away_source, e.g. "2.º del Grupo A") instead of a team.
 */
import type { WcBracketMatch, WcBracketPayload } from '@/lib/wc-types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from '@/components/intents/CardOrnaments';

interface Props {
  data: WcBracketPayload;
}

/** Localized stage label → short column header + progression order. The
 *  third-place playoff is intentionally absent (rendered in the footer). */
const STAGE_COLUMN: Record<string, { short: string; order: number }> = {
  'Dieciseisavos de final': { short: 'Dieciseisavos', order: 0 },
  'Octavos de final': { short: 'Octavos', order: 1 },
  'Cuartos de final': { short: 'Cuartos', order: 2 },
  'Semifinales': { short: 'Semis', order: 3 },
  'Final': { short: 'Final', order: 4 },
};

export default function WcBracketTable({ data }: Props) {
  if (data.ties.length === 0) return null;

  // Split out the third-place playoff; group the rest into progression columns.
  const thirdPlace = data.ties.find((t) => t.stage === 'Tercer puesto') ?? null;
  const columnsMap = new Map<string, WcBracketMatch[]>();
  for (const tie of data.ties) {
    if (tie.stage === 'Tercer puesto') continue;
    const arr = columnsMap.get(tie.stage) ?? [];
    arr.push(tie);
    columnsMap.set(tie.stage, arr);
  }
  const columns = [...columnsMap.entries()]
    .map(([stage, ties]) => ({ stage, ties, meta: STAGE_COLUMN[stage] }))
    .sort((a, b) => (a.meta?.order ?? 99) - (b.meta?.order ?? 99));

  // Champion = the side that advanced in the final.
  const finalTie = columnsMap.get('Final')?.[0] ?? null;
  const champion =
    finalTie && finalTie.winner_side
      ? {
          team: finalTie.winner_side === 'home' ? finalTie.home_team : finalTie.away_team,
          abbr: finalTie.winner_side === 'home' ? finalTie.home_abbr : finalTie.away_abbr,
        }
      : null;

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.turquoise.border}`}>
      {/* Header */}
      <div className="relative overflow-hidden flex items-center gap-3 px-4 py-3 border-b border-bf-turquoise/20">
        <TriangleField color={ACCENT_HEX.turquoise} corner="tr" />
        <TrophyIcon className="relative z-10 w-5 h-5 text-bf-turquoise flex-shrink-0" />
        <div className="relative z-10 min-w-0 flex-1">
          <div className="font-display text-sm text-white leading-none tracking-tight">Mundial 2026</div>
          <div className="text-[10px] font-bold uppercase tracking-widest text-bf-text/45 mt-1">
            Fase final · Eliminatorias
          </div>
        </div>
        <span className="relative z-10 flex-shrink-0 inline-flex items-center gap-1 text-[10px] font-bold text-bf-gray border border-white/10 rounded-full px-2 py-0.5">
          Desliza <span aria-hidden>→</span>
        </span>
      </div>

      {/* Bracket tree (horizontal scroll) */}
      <div className="overflow-x-auto px-3 py-3">
        <div className="flex items-stretch gap-3 min-w-max">
          {columns.map((col) => (
            <div key={col.stage} className="flex flex-col w-[152px] flex-shrink-0">
              <div className="text-[10px] font-extrabold uppercase tracking-widest text-bf-turquoise px-1 pb-2">
                {col.meta?.short ?? col.stage}
              </div>
              <div className="flex-1 flex flex-col justify-around gap-2">
                {col.ties.map((tie) => (
                  <TieCard key={tie.match_num} tie={tie} isFinal={col.stage === 'Final'} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Footer: champion + third-place playoff */}
      {(champion || thirdPlace) && (
        <div className="border-t border-white/10 px-4 py-3 flex flex-wrap items-center gap-x-6 gap-y-3">
          {champion && (
            <div className="flex items-center gap-2.5">
              <TrophyIcon className="w-5 h-5 text-bf-gold flex-shrink-0" />
              <div className="min-w-0">
                <div className="text-[9px] font-bold uppercase tracking-widest text-bf-gold/80 leading-none">
                  Campeón del mundo
                </div>
                <div className="font-display text-sm text-white leading-tight mt-1 truncate">
                  {champion.team}
                </div>
              </div>
              {champion.abbr && <AbbrChip code={champion.abbr} tone="gold" />}
            </div>
          )}
          {thirdPlace && (
            <div className="min-w-0">
              <div className="text-[9px] font-bold uppercase tracking-widest text-bf-text/45 leading-none mb-1.5">
                Tercer puesto
              </div>
              <div className="w-[200px] max-w-full rounded-lg border border-white/10 overflow-hidden">
                <TeamRow tie={thirdPlace} side="home" isFinal={false} />
                <TeamRow tie={thirdPlace} side="away" isFinal={false} />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function TieCard({ tie, isFinal }: { tie: WcBracketMatch; isFinal: boolean }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/20 overflow-hidden">
      <TeamRow tie={tie} side="home" isFinal={isFinal} />
      <div className="h-px bg-white/10" />
      <TeamRow tie={tie} side="away" isFinal={isFinal} />
    </div>
  );
}

function TeamRow({ tie, side, isFinal }: { tie: WcBracketMatch; side: 'home' | 'away'; isFinal: boolean }) {
  const team = side === 'home' ? tie.home_team : tie.away_team;
  const abbr = side === 'home' ? tie.home_abbr : tie.away_abbr;
  const source = side === 'home' ? tie.home_source : tie.away_source;
  const score = side === 'home' ? tie.home_score : tie.away_score;
  const isWinner = tie.winner_side === side;
  const tone: 'gold' | 'turquoise' | 'none' = isWinner ? (isFinal ? 'gold' : 'turquoise') : 'none';

  const barClass =
    tone === 'gold' ? 'bg-bf-gold' : tone === 'turquoise' ? 'bg-bf-turquoise' : 'bg-transparent';
  const nameClass = isWinner ? 'text-white font-bold' : team ? 'text-bf-text/70' : 'text-bf-gray italic';
  const scoreClass =
    tone === 'gold' ? 'text-bf-gold' : tone === 'turquoise' ? 'text-bf-turquoise' : 'text-bf-gray';

  return (
    <div className="flex items-center gap-1.5 pr-2 h-[26px]">
      <span className={`w-[3px] self-stretch flex-shrink-0 ${barClass}`} />
      {abbr ? (
        <AbbrChip code={abbr} tone={tone === 'none' ? 'muted' : tone} />
      ) : (
        <span className="w-7 flex-shrink-0" />
      )}
      <span className={`flex-1 min-w-0 truncate text-xs leading-tight ${nameClass}`}>
        {team ?? source ?? 'Por definir'}
      </span>
      {score != null && (
        <span className={`flex-shrink-0 font-display text-xs tabular-nums ${scoreClass}`}>{score}</span>
      )}
    </div>
  );
}

function AbbrChip({ code, tone }: { code: string; tone: 'gold' | 'turquoise' | 'muted' }) {
  const cls =
    tone === 'gold'
      ? 'bg-bf-gold/15 text-bf-gold'
      : tone === 'turquoise'
        ? 'bg-bf-turquoise/15 text-bf-turquoise'
        : 'bg-white/5 text-bf-gray';
  return (
    <span
      className={`flex-shrink-0 inline-flex items-center justify-center w-7 rounded text-[9px] font-extrabold tracking-wide py-0.5 ${cls}`}
    >
      {code}
    </span>
  );
}

function TrophyIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6" />
      <path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18" />
      <path d="M4 22h16" />
      <path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22" />
      <path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22" />
      <path d="M18 2H6v7a6 6 0 0 0 12 0V2Z" />
    </svg>
  );
}
