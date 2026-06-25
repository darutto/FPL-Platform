/**
 * WcBracketTable — structured rendering for the World Cup knockout bracket
 * (get_bracket / '/brackets').
 *
 * Rendered beneath final_text when response.outcome === 'ok' and
 * response.bracket has matches (see lib/wc-intent-renderer.ts
 * selectWcIntentView). Matches arrive pre-sorted R32 → Final and already
 * locale_es-localized. Each side is either a confirmed team (bold) or a
 * pending slot whose Spanish origin (e.g. "2.º del Grupo A", "Ganador del
 * partido 74") is shown in muted italics — so the card explains who will
 * play whom even before the teams are known.
 */
import type { WcBracketMatch, WcBracketPayload } from '@/lib/wc-types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from '@/components/intents/CardOrnaments';

interface Props {
  data: WcBracketPayload;
}

export default function WcBracketTable({ data }: Props) {
  if (data.ties.length === 0) return null;

  // Group by localized stage label, preserving backend order (R32 → Final).
  const stages: { label: string; matches: WcBracketMatch[] }[] = [];
  for (const match of data.ties) {
    let bucket = stages[stages.length - 1];
    if (!bucket || bucket.label !== match.stage) {
      bucket = { label: match.stage, matches: [] };
      stages.push(bucket);
    }
    bucket.matches.push(match);
  }

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.cyan.border}`}>
      <div className="relative overflow-hidden px-4 py-2.5 border-b border-bf-cyan/20">
        <TriangleField color={ACCENT_HEX.cyan} corner="tr" />
        <span className="relative z-10 text-xs font-extrabold text-white uppercase tracking-wide">
          Cuadro de eliminatorias
        </span>
        {!data.bracket_complete && (
          <span className="relative z-10 ml-2 text-[10px] font-bold text-bf-gray normal-case tracking-normal">
            · cruces por confirmar
          </span>
        )}
      </div>

      {stages.map((stage) => (
        <div key={stage.label}>
          <div className="px-4 pt-2.5 pb-1">
            <span className="text-[10px] font-extrabold text-bf-cyan uppercase tracking-widest">
              {stage.label}
            </span>
          </div>
          {stage.matches.map((match, idx) => (
            <BracketRow key={match.match_num} match={match} banded={idx % 2 === 0} />
          ))}
        </div>
      ))}
    </div>
  );
}

function formatDate(date: string | null): string {
  if (!date) return '';
  const d = new Date(date);
  if (Number.isNaN(d.getTime())) return date;
  return d.toLocaleDateString('es-ES', { day: '2-digit', month: 'short' });
}

/** One side of a tie: bold team name when confirmed, muted italic slot
 *  description ("2.º del Grupo A") when still pending. */
function Side({ team, source, align }: { team: string | null; source: string | null; align: 'left' | 'right' }) {
  const alignCls = align === 'right' ? 'text-right' : 'text-left';
  if (team) {
    return <span className={`font-bold text-white truncate ${alignCls}`}>{team}</span>;
  }
  return (
    <span className={`italic text-bf-gray truncate ${alignCls}`}>
      {source ?? 'Por definir'}
    </span>
  );
}

function BracketRow({ match, banded }: { match: WcBracketMatch; banded: boolean }) {
  return (
    <div className={`flex items-center gap-3 px-4 py-2.5 ${banded ? 'bg-white/[0.035]' : ''}`}>
      <div className="flex-1 min-w-0">
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
          <Side team={match.home_team} source={match.home_source} align="left" />
          <span className="font-display text-xs tracking-tighter text-bf-cyan flex-shrink-0 px-1 text-center">
            vs
          </span>
          <Side team={match.away_team} source={match.away_source} align="right" />
        </div>
      </div>

      {match.date && (
        <div className="flex-shrink-0 text-right">
          <div className="text-[10px] text-bf-gray">{formatDate(match.date)}</div>
        </div>
      )}
    </div>
  );
}
