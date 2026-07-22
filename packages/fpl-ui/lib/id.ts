/**
 * generateId — client-side unique id for React list keys / message ids.
 *
 * `crypto.randomUUID()` only exists in secure contexts (HTTPS or `localhost`)
 * per the Web Crypto API spec — loading the dev server over plain HTTP from a
 * LAN IP (e.g. testing on a phone via `http://10.0.0.177:3000`) is NOT a
 * secure context in most mobile browsers, so `crypto.randomUUID` is undefined
 * there even though `crypto` itself exists. Falls back to a non-cryptographic
 * random id — fine here since these ids are only ever used as local React
 * keys / message identifiers, never for anything security-sensitive.
 */
export function generateId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `id-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}
