'use client';

/**
 * WebSearchSources — the cited web sources of a turn, as titled, clickable
 * links. Shown under another card (e.g. the player card) when search_web ran
 * beside it; the model's prose carries no URLs, this list is where they live.
 * A turn whose main view IS the web-search card keeps its own footer instead.
 */
import type { WebSearchResult } from '@/lib/types';
import { useT } from '@/lib/i18n/LocaleProvider';

function hostLabel(result: WebSearchResult): string {
  if (result.source) return result.source;
  try {
    return new URL(result.url).hostname.replace(/^www\./, '');
  } catch {
    return result.url;
  }
}

export default function WebSearchSources({ results }: { results: WebSearchResult[] | undefined | null }) {
  const t = useT();
  const items = (results ?? []).filter((r) => r.url);
  if (items.length === 0) return null;
  return (
    <section aria-label={t('web.sources')} className="border-t border-white/10 px-4 py-3" data-testid="web-sources">
      <div className="mb-1.5 text-[9px] font-bold uppercase tracking-widest text-bf-gray">{t('web.sources')}</div>
      <ul className="flex list-none flex-col gap-1">
        {items.map((r, idx) => (
          <li key={`${r.url}-${idx}`} className="text-xs leading-snug">
            <a
              href={r.url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-semibold text-bf-cyan underline-offset-2 hover:underline"
            >
              {r.title || hostLabel(r)}
            </a>
            <span className="text-bf-gray"> — {hostLabel(r)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
