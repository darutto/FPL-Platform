/**
 * GenericCard — structured rendering for the generic_card payload.
 *
 * The catch-all card for any intent without a bespoke component (Track B —
 * closes the "plain text block" gap). Rendered beneath final_text when:
 *   response.outcome === 'ok'
 *   response.generic_card !== null
 *   AND no bespoke intent branch matched first — see lib/intent-renderer.ts:
 *   generic_card sits below every bespoke check (captain/comparison/etc.)
 *   and above the web_search fallback (lowest precedence).
 *
 * Layout mirrors CaptainCard/ResourceRankingTable so it sits naturally next
 * to them: uppercase accent-colored title row (+ pills, wrapping on small
 * screens), optional subtitle, optional hero stat (font-display number +
 * uppercase micro-label, toned via lib/theme), a CardTable body when rows
 * are present, and a muted footer line. Mobile-safe at 360px — title/pills
 * wrap, the table scrolls inside itself (see CardTable).
 */
import type { GenericCardMeta } from '@/lib/types';
import {
  CARD_BASE,
  CARD_ACCENT,
  ACCENT_HEX,
  PILL_BASE,
  GENERIC_TONE_CLASSES,
  GENERIC_TONE_TEXT,
} from '@/lib/theme';
import { TriangleField } from './CardOrnaments';
import CardTable from './CardTable';

interface Props {
  data: GenericCardMeta;
}

export default function GenericCard({ data }: Props) {
  const { accent, title, subtitle, hero, pills, columns, rows, footer } = data;
  const accentClasses = CARD_ACCENT[accent] ?? CARD_ACCENT.gray;
  const accentHex = ACCENT_HEX[accent] ?? ACCENT_HEX.gray;

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${accentClasses.border}`}>
      <TriangleField color={accentHex} corner="tr" />
      <div className="relative z-10 space-y-3 p-4">
        {/* Title row + pills — wraps on small screens instead of overflowing */}
        <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
          <span className={`text-xs font-extrabold uppercase tracking-wide ${accentClasses.heading}`}>
            {title}
          </span>
          {pills.length > 0 && (
            <div className="flex flex-wrap items-center justify-end gap-1.5">
              {pills.map((pill, i) => (
                <span
                  key={`${pill.label}-${i}`}
                  className={`${PILL_BASE} ${GENERIC_TONE_CLASSES[pill.tone]}`}
                >
                  {pill.label}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Subtitle */}
        {subtitle != null && <p className="text-xs leading-relaxed text-bf-gray">{subtitle}</p>}

        {/* Hero stat */}
        {hero != null && (
          <div className="space-y-0.5">
            <span
              className={`block font-display text-3xl leading-none tracking-tighter ${
                hero.tone != null ? GENERIC_TONE_TEXT[hero.tone] : 'text-white'
              }`}
            >
              {hero.value}
            </span>
            <span className="text-[11px] uppercase tracking-wide text-bf-gray">{hero.label}</span>
          </div>
        )}

        {/* Table body */}
        {rows.length > 0 && columns.length > 0 && <CardTable columns={columns} rows={rows} />}

        {/* Footer */}
        {footer != null && (
          <p className="border-t border-white/10 pt-2 text-[11px] text-bf-gray/70">{footer}</p>
        )}
      </div>
    </div>
  );
}
