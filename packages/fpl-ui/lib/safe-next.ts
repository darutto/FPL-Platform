/**
 * Sanitiser for the post-login destination (`?next=`).
 *
 * `next` is UNTRUSTED (anyone can craft a /login?next=… link), so the only
 * thing that ever leaves this module is `/chat` or `/chat?q=<prompt>` —
 * rebuilt from parsed parts, never echoed from the input. Anything else
 * (absolute URLs, //host, backslashes, other paths, `/chatx`, uppercase…)
 * falls back to `/chat`. Pure: no DOM, no Next imports.
 */
export const DEFAULT_NEXT = '/chat';
/** Longest `q` honoured; longer prompts are cut (by code point). The web side must respect it. */
export const MAX_Q_LENGTH = 300;
/** Longest raw `next` inspected at all (q is percent-encoded, up to 9 bytes per code point). */
const MAX_RAW_LENGTH = 4096;

const CONTROL_OR_BACKSLASH = /[\u0000-\u001f\u007f\\]/;

export function sanitizeNext(raw: unknown): string {
  if (typeof raw !== 'string' || raw.length === 0 || raw.length > MAX_RAW_LENGTH) {
    return DEFAULT_NEXT;
  }
  // Exactly `/chat`, optionally followed by a query. `/chatx`, `/chat/..`, `//x`,
  // `https://…`, `javascript:` and `%2f%2f…` all fail here (case-sensitive on purpose).
  if (!(raw === DEFAULT_NEXT || raw.startsWith(DEFAULT_NEXT + '?'))) return DEFAULT_NEXT;
  if (CONTROL_OR_BACKSLASH.test(raw)) return DEFAULT_NEXT;

  let url: URL;
  try {
    url = new URL(raw, 'http://same-origin.invalid');
  } catch {
    return DEFAULT_NEXT;
  }
  if (url.origin !== 'http://same-origin.invalid' || url.pathname !== DEFAULT_NEXT) {
    return DEFAULT_NEXT;
  }

  const q = url.searchParams.get('q');
  if (q === null) return DEFAULT_NEXT;
  const trimmed = Array.from(q).slice(0, MAX_Q_LENGTH).join('').trim();
  if (trimmed.length === 0) return DEFAULT_NEXT;
  return `${DEFAULT_NEXT}?q=${encodeURIComponent(trimmed)}`;
}

/** `/login?next=…` for an anonymous hit on `pathAndSearch`; plain `/login` if nothing worth keeping. */
export function loginPathFor(pathAndSearch: string): string {
  const safe = sanitizeNext(pathAndSearch);
  return safe === DEFAULT_NEXT ? '/login' : `/login?next=${encodeURIComponent(safe)}`;
}

/** Clerk redirect target after sign-in / sign-up; carries the sanitised destination. */
export function postLoginPathFor(rawNext: unknown): string {
  const safe = sanitizeNext(rawNext);
  return safe === DEFAULT_NEXT ? '/post-login' : `/post-login?next=${encodeURIComponent(safe)}`;
}

/** sessionStorage fallback: survives the Patreon round-trip in the same tab if Clerk drops the URL param. */
export const PENDING_NEXT_KEY = 'bf_post_login_next';
