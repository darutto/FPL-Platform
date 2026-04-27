/**
 * CaptainCard — structured rendering for captain_score OK turns.
 *
 * Rendered beneath final_text when:
 *   response.outcome === 'ok'
 *   response.intent  === 'captain_score'
 *   response.captain !== null
 *
 * Consumes from CaptainScoreMeta (stable conditional fields only):
 *   web_name, team_short, captain_score, tier, role_bonus, set_piece_notes
 *
 * Tier badge colours (from V2_MVP_ROADMAP.md):
 *   safe=emerald, upside=amber, differential=violet, avoid=red, low_confidence=slate
 */
import type { CaptainScoreMeta, CaptainTier } from '@/lib/types';

interface Props {
  data: CaptainScoreMeta;
}

export default function CaptainCard({ data }: Props) {
  const { web_name, team_short, captain_score, tier, set_piece_notes } = data;
  const { label, className } = TIER_CONFIG[tier] ?? TIER_CONFIG.low_confidence;

  return (
    <div className="mt-3 rounded-xl border border-gray-700 bg-gray-900/60 p-4 text-sm space-y-3">
      {/* Header row */}
      <div className="flex items-center justify-between gap-3">
        <div>
          <span className="font-semibold text-white text-base">{web_name}</span>
          <span className="ml-2 text-gray-400 text-xs">{team_short}</span>
        </div>
        <TierBadge label={label} className={className} />
      </div>

      {/* Score bar */}
      <div className="space-y-1">
        <div className="flex items-center justify-between text-xs text-gray-400">
          <span>Puntuación de capitán</span>
          <span className="font-mono text-white">{captain_score.toFixed(1)}</span>
        </div>
        <div className="h-1.5 rounded-full bg-gray-700 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${TIER_CONFIG[tier]?.barClass ?? 'bg-slate-400'}`}
            style={{ width: `${Math.min(captain_score, 100)}%` }}
          />
        </div>
      </div>

      {/* Set piece notes */}
      {set_piece_notes.length > 0 && (
        <ul className="space-y-0.5">
          {set_piece_notes.map((note) => (
            <li key={note} className="text-xs text-gray-400 flex gap-1.5">
              <span className="text-indigo-400">•</span>
              {translateSetPieceNote(note)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TierBadge({ label, className }: { label: string; className: string }) {
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${className}`}>
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Tier config
// ---------------------------------------------------------------------------

const TIER_CONFIG: Record<
  CaptainTier,
  { label: string; className: string; barClass: string }
> = {
  safe: {
    label: 'Favorito',
    className: 'bg-emerald-900/60 text-emerald-300',
    barClass: 'bg-emerald-500',
  },
  upside: {
    label: 'Potencial',
    className: 'bg-amber-900/60 text-amber-300',
    barClass: 'bg-amber-500',
  },
  differential: {
    label: 'Diferencial',
    className: 'bg-violet-900/60 text-violet-300',
    barClass: 'bg-violet-500',
  },
  avoid: {
    label: 'Evitar',
    className: 'bg-red-900/60 text-red-300',
    barClass: 'bg-red-500',
  },
  low_confidence: {
    label: 'Datos limitados',
    className: 'bg-slate-700/60 text-slate-300',
    barClass: 'bg-slate-400',
  },
};

// ---------------------------------------------------------------------------
// Set piece note translation
// ---------------------------------------------------------------------------

const SET_PIECE_LABELS: Record<string, string> = {
  penalty_taker_1: '1.º lanzador de penaltis',
  penalty_taker_2: '2.º lanzador de penaltis',
  freekick_taker_1: '1.º ejecutor de faltas',
  freekick_taker_2: '2.º ejecutor de faltas',
  corner_taker_1: 'Primer sacador de córners',
  corner_taker_2: '2.º sacador de córners',
};

function translateSetPieceNote(note: string): string {
  return SET_PIECE_LABELS[note] ?? note.replace(/_/g, ' ');
}
