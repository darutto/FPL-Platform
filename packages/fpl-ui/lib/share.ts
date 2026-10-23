/**
 * share.ts — helpers for social/link share payloads.
 *
 * Centralizes copy and URL encoding so every share button emits a consistent
 * Club Bendito Fantasy invite with the same canonical app URL.
 */

import { translate } from './i18n/dictionary';
import { DEFAULT_LOCALE, type Locale } from './i18n/locale';

export const CLUB_NAME = translate('es', 'share.club');
export const DEFAULT_CTA = translate('es', 'share.cta');

const DEFAULT_APP_URL = 'https://app.benditofantasy.com/chat';

export interface ShareContext {
  question: string;
  appUrl?: string;
  cta?: string;
  /** Language of the invite text. Spanish when absent. */
  locale?: Locale;
}

export function canonicalAppUrl(input?: string): string {
  const raw = (input ?? DEFAULT_APP_URL).trim();
  if (!raw) return DEFAULT_APP_URL;

  const withScheme = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
  try {
    const u = new URL(withScheme);
    if (u.pathname === '/') {
      u.pathname = '/chat';
    }
    return u.toString().replace(/\/$/, '');
  } catch {
    return DEFAULT_APP_URL;
  }
}

export function buildShareText(ctx: ShareContext): string {
  const appUrl = canonicalAppUrl(ctx.appUrl);
  const locale = ctx.locale ?? DEFAULT_LOCALE;
  const defaultCta = translate(locale, 'share.cta');
  const cta = (ctx.cta ?? defaultCta).trim() || defaultCta;
  const q = ctx.question.trim();
  const intro = translate(locale, 'share.text', { club: translate(locale, 'share.club'), question: q });
  return `${intro}\n${cta}\n${appUrl}`;
}

export function buildCopyPayload(ctx: ShareContext): string {
  return buildShareText(ctx);
}

export function buildXIntentUrl(ctx: ShareContext): string {
  const text = buildShareText(ctx);
  return `https://x.com/intent/tweet?text=${encodeURIComponent(text)}`;
}

export function buildBlueskyUrl(ctx: ShareContext): string {
  const text = buildShareText(ctx);
  return `https://bsky.app/intent/compose?text=${encodeURIComponent(text)}`;
}

export function buildThreadsUrl(ctx: ShareContext): string {
  const text = buildShareText(ctx);
  return `https://www.threads.net/intent/post?text=${encodeURIComponent(text)}`;
}

export function buildInstagramUrl(): string {
  // Instagram web has no stable compose-intent URL that accepts prefilled
  // text/media from browser JS. This URL is only used as desktop fallback.
  return 'https://www.instagram.com/';
}

export function buildWhatsAppUrl(ctx: ShareContext): string {
  const text = buildShareText(ctx);
  return `https://wa.me/?text=${encodeURIComponent(text)}`;
}
