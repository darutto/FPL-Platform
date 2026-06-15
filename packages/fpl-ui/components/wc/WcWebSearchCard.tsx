/**
 * WcWebSearchCard — structured rendering for an unverified web-search answer
 * (web_search tool, premium path).
 *
 * Rendered beneath final_text when response.web_search is present (see
 * lib/wc-intent-renderer.ts selectWcIntentView). Ported from the design system's
 * WebSearchRiskCard (.design-import Hi-Fi), adapted for the World Cup domain:
 * cyan accent (the system's "web/search" color), a globe provenance strip, the
 * model's Spanish `summary`, the cited results, and a clickable sources footer.
 *
 * UNLIKE the deterministic cards, this content is AI synthesis over live web
 * sources — NOT grounded tournament data. The "sin verificar" banner + the
 * cyan "Búsqueda web + IA" origin badge (MessageList) make that explicit so it
 * never reads as "Datos verificados".
 */
import type { WcWebSearchPayload } from '@/lib/wc-types';
import { CARD_BASE, CARD_ACCENT, ACCENT_HEX } from '@/lib/theme';
import { TriangleField } from '@/components/intents/CardOrnaments';

interface Props {
  data: WcWebSearchPayload;
}

function IconGlobe({ color }: { color: string }) {
  return (
    <svg width={13} height={13} viewBox="0 0 22 22" fill="none" aria-hidden="true">
      <circle cx="11" cy="11" r="8" stroke={color} strokeWidth="1.6" />
      <path
        d="M3 11h16M11 3c2.5 2.5 4 5.5 4 8s-1.5 5.5-4 8c-2.5-2.5-4-5.5-4-8s1.5-5.5 4-8z"
        stroke={color}
        strokeWidth="1.4"
      />
    </svg>
  );
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString('es-ES', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function hostLabel(result: { source: string; url: string }): string {
  if (result.source) return result.source;
  try {
    return new URL(result.url).hostname.replace(/^www\./, '');
  } catch {
    return result.url;
  }
}

/** Inline **bold** → <strong>; everything else stays plain text. */
function renderInline(text: string): React.ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') ? (
      <strong key={i} className="font-bold text-white">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}

/** Minimal markdown for the model's web-search summary: paragraphs, bullet
 *  lists (`* ` / `- `), and inline bold. Avoids pulling in a markdown lib for
 *  the one place a WC card renders model prose. Snippets are pre-flattened
 *  server-side, so this only ever runs on the trusted summary. */
function MarkdownLite({ text }: { text: string }) {
  const lines = text.split('\n');
  const blocks: React.ReactNode[] = [];
  let bullets: string[] = [];

  const flushBullets = () => {
    if (bullets.length === 0) return;
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="list-disc pl-4 space-y-1">
        {bullets.map((b, i) => (
          <li key={i}>{renderInline(b)}</li>
        ))}
      </ul>,
    );
    bullets = [];
  };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      flushBullets();
      continue;
    }
    const bullet = line.match(/^[*-]\s+(.*)$/);
    if (bullet) {
      bullets.push(bullet[1]);
    } else {
      flushBullets();
      blocks.push(
        <p key={`p-${blocks.length}`} className="leading-relaxed">
          {renderInline(line)}
        </p>,
      );
    }
  }
  flushBullets();

  return <div className="space-y-2">{blocks}</div>;
}

export default function WcWebSearchCard({ data }: Props) {
  const { topic, summary, results, timestamp } = data;
  const when = formatTimestamp(timestamp);

  return (
    <div className={`mt-3 text-sm ${CARD_BASE} ${CARD_ACCENT.cyan.border}`}>
      {/* Provenance strip */}
      <div className="relative overflow-hidden flex items-center gap-2 px-4 py-2.5 border-b border-bf-cyan/20">
        <TriangleField color={ACCENT_HEX.cyan} corner="tr" />
        <span className="relative z-10 flex items-center gap-1.5">
          <IconGlobe color={ACCENT_HEX.cyan} />
          <span className="text-xs font-extrabold text-bf-cyan uppercase tracking-wide">
            Búsqueda web
          </span>
        </span>
        {when && <span className="relative z-10 text-[10px] text-bf-gray">· {when}</span>}
        <span className="relative z-10 ml-auto text-[10px] text-bf-gray">
          {results.length} {results.length === 1 ? 'fuente' : 'fuentes'}
        </span>
      </div>

      <div className="px-4 py-3 space-y-2">
        {/* Unverified disclaimer (Banner pattern, info tone) */}
        <div className="rounded-lg border border-bf-cyan/40 bg-bf-cyan/10 px-3 py-1.5 text-[11px] text-bf-cyan">
          Búsqueda web · IA · información sin verificar
        </div>

        {topic && (
          <div className="text-[15px] font-extrabold text-white leading-tight">{topic}</div>
        )}

        {/* Model's Spanish synthesis (== final_text). Rendered with minimal
            markdown (bold + bullets); snippets are flattened server-side. */}
        {summary && (
          <div className="text-sm text-bf-text/90">
            <MarkdownLite text={summary} />
          </div>
        )}
      </div>

      {/* Cited results */}
      {results.length > 0 && (
        <div className="border-t border-white/5">
          {results.map((r, idx) => (
            <div
              key={`${r.url}-${idx}`}
              className={`px-4 py-2.5 ${idx % 2 === 0 ? 'bg-white/[0.035]' : ''}`}
            >
              <div className="text-xs font-bold text-white leading-snug">{r.title}</div>
              {r.snippet && (
                <div className="mt-1 text-[11.5px] text-bf-text/75 leading-relaxed border-l-2 border-bf-cyan/40 pl-2 italic">
                  {r.snippet}
                </div>
              )}
              <div className="mt-1 text-[10px] text-bf-gray pl-2">
                — {hostLabel(r)}
                {r.published ? ` · ${r.published}` : ''}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Sources footer — clickable chips */}
      {results.length > 0 && (
        <div className="px-4 py-3 border-t border-white/10">
          <div className="text-[9px] font-bold text-bf-gray uppercase tracking-widest mb-1.5">
            Fuentes consultadas
          </div>
          <div className="flex flex-wrap gap-1.5">
            {results.map((r, idx) => (
              <a
                key={`chip-${r.url}-${idx}`}
                href={r.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 rounded-md bg-bf-cyan px-2.5 py-1 text-[10.5px] font-bold text-bf-ink no-underline hover:opacity-90 transition-opacity"
              >
                {hostLabel(r)}
                <svg width="9" height="9" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                  <path
                    d="M3 3h6v6M3 9l6-6"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                  />
                </svg>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
