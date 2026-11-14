'use client';

/**
 * PlayerConclusions — the verdict above the player card: 0-3 one-line
 * conclusions that say what the card itself does NOT show.
 *
 * The backend sends structured keys + params + evidence (player_conclusions.py);
 * the wording lives here and in lib/i18n. Icon + label on the left, evidence
 * muted on the right; on narrow screens the evidence wraps under the label.
 * Empty list → renders nothing (no block at all).
 */

import type { ReactNode } from 'react';
import type { PlayerConclusion, PlayerPositionRole, SetPiece } from '@/lib/types';
import { useT } from '@/lib/i18n/LocaleProvider';

type T = ReturnType<typeof useT>;

const SVG_PROPS = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
  className: 'h-[18px] w-[18px] flex-none text-bf-purple',
};

const ICONS: Record<PlayerConclusion['key'], ReactNode> = {
  points_attack: (
    <svg {...SVG_PROPS}>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="5" />
      <circle cx="12" cy="12" r="1.5" fill="currentColor" />
    </svg>
  ),
  points_defence: (
    <svg {...SVG_PROPS}>
      <path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z" />
    </svg>
  ),
  points_clean_sheets: (
    <svg {...SVG_PROPS}>
      <path d="M3 20V6h18v14" />
      <path d="M3 10h18M8 6v14M16 6v14" strokeOpacity=".45" />
    </svg>
  ),
  position: (
    <svg {...SVG_PROPS}>
      <rect x="4" y="3" width="16" height="18" rx="1" />
      <circle cx="8" cy="15" r="1.6" strokeDasharray="1.5 1.5" />
      <circle cx="8" cy="9" r="2" fill="currentColor" />
    </svg>
  ),
  set_pieces: (
    <svg {...SVG_PROPS}>
      <path d="M5 21V4" />
      <path d="M5 4h11l-2 4 2 4H5" />
    </svg>
  ),
  starts: (
    <svg {...SVG_PROPS}>
      <path d="M8 3l-5 3 2 4 3-1v12h8V9l3 1 2-4-5-3c0 2-2 3-4 3s-4-1-4-3z" />
    </svg>
  ),
  zonal: (
    <svg {...SVG_PROPS}>
      <rect x="3" y="5" width="18" height="14" rx="1" />
      <path d="M12 5v14" />
      <rect x="3" y="9" width="4" height="6" />
      <rect x="17" y="9" width="4" height="6" fill="currentColor" fillOpacity=".35" />
    </svg>
  ),
};

const POSITION_ROLES: PlayerPositionRole[] = [
  'winger', 'wing_back', 'forward', 'attacking_mid', 'central_mid', 'holding_mid', 'centre_back', 'full_back',
];

function joinPieces(pieces: SetPiece[], t: T): string {
  const words = pieces.map((p) => t(`concl.piece.${p}`));
  if (words.length <= 1) return words.join('');
  return `${words.slice(0, -1).join(', ')}${t('concl.and')}${words[words.length - 1]}`;
}

/** The line's label, or null for a key/position this UI doesn't know (dropped, never shown raw). */
export function conclusionLabel(c: PlayerConclusion, t: T): string | null {
  switch (c.key) {
    case 'points_attack':
      return ['DEF', 'MID', 'FWD'].includes(c.params.position) ? t(`concl.attack.${c.params.position as 'DEF' | 'MID' | 'FWD'}`) : null;
    case 'points_defence':
      return ['DEF', 'MID'].includes(c.params.position) ? t(`concl.defence.${c.params.position as 'DEF' | 'MID'}`) : null;
    case 'points_clean_sheets':
      return t('concl.cleanSheets');
    case 'position': {
      // «Juega de extremo · 6 de 6»: the role word when his starts on that line agree on a role, else the line word,
      // then the position card's own count. Anything else is dropped.
      const { role, line } = c.params;
      const count = t('concl.position.count', { starts: c.params.starts, games: c.params.games });
      if (role && POSITION_ROLES.includes(role)) return `${t(`concl.position.role.${role}`)} · ${count}`;
      if (line && ['DEF', 'MID', 'FWD'].includes(line)) {
        return `${t(`concl.position.line.${line as 'DEF' | 'MID' | 'FWD'}`)} · ${count}`;
      }
      return null;
    }
    case 'set_pieces':
      return c.params.pieces.length > 0 ? t('concl.setPieces', { pieces: joinPieces(c.params.pieces, t) }) : null;
    case 'starts':
      return t('concl.starts', { starts: c.params.starts, games: c.params.games });
    case 'zonal':
      return c.params.opponents.length > 0 ? t('concl.zonal', { opponents: c.params.opponents.join(', ') }) : null;
    default:
      return null;
  }
}

/**
 * "xGI/90 · top 10 % de MID"; the clean-sheets line names its metric in the label, so evidence is "top N %" only.
 * The position line's evidence is the gameweeks of the position card's window («J5–J10»).
 */
export function conclusionEvidence(c: PlayerConclusion, t: T): string | null {
  if (c.key === 'position') {
    const ev = c.evidence;
    if (ev == null) return null;
    return ev.gw_from === ev.gw_to ? t('fx.gw', { n: ev.gw_from }) : t('fx.gwRange', { start: ev.gw_from, end: ev.gw_to });
  }
  const ev = c.evidence;
  if (ev == null) return null;
  const top = t('concl.top', { n: ev.top_pct, pos: ev.position });
  if (ev.metric === 'cs_per_90') return top;
  return `${t(`concl.metric.${ev.metric}`)} · ${top}`;
}

export default function PlayerConclusions({ conclusions }: { conclusions: PlayerConclusion[] | undefined | null }) {
  const t = useT();
  const rows = (conclusions ?? [])
    .map((c) => ({ c, label: conclusionLabel(c, t), evidence: conclusionEvidence(c, t) }))
    .filter((r): r is { c: PlayerConclusion; label: string; evidence: string | null } => r.label != null)
    .slice(0, 3);
  if (rows.length === 0) return null;
  return (
    <ul aria-label={t('concl.label')} className="flex list-none flex-col gap-1.5" data-testid="player-conclusions">
      {rows.map(({ c, label, evidence }) => (
        <li key={c.key} className="flex flex-wrap items-start gap-x-2.5 sm:flex-nowrap sm:items-center">
          {ICONS[c.key]}
          <span className="min-w-0 flex-1 text-[15px] font-semibold text-bf-text">{label}</span>
          {evidence && (
            <span className="basis-full pl-7 text-[13px] font-medium text-bf-gray sm:basis-auto sm:pl-0 sm:whitespace-nowrap">
              {evidence}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
