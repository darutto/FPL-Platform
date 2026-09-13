/**
 * Route inventory — every API route that talks to a backend must forward the
 * caller's identity through `lib/identity-headers.ts`, or be listed here with
 * a reason. This is how the NEXT proxy route cannot be born without identity
 * (i79 was exactly that: `/session/{id}/ask` written without the headers).
 *
 * To add a route: import `forwardIdentityHeaders` and use it. To exempt one:
 * add it to EXEMPT with the reason — and be sure the backend endpoint it hits
 * does not read X-User-Id / X-User-Tier.
 */
import * as fs from 'fs';
import * as path from 'path';

const API_ROOT = path.join(__dirname, '..', 'app', 'api');

const EXEMPT: Record<string, string> = {
  'auth/sync-patreon/route.ts':
    'Talks to Patreon (OAuth) and to the backend /events/tier-sync, which is ' +
    'authenticated by x-internal-token and carries the user id in its body; ' +
    'the backend endpoint does not read X-User-Id / X-User-Tier.',
};

function walk(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    return e.isDirectory() ? walk(p) : e.name === 'route.ts' ? [p] : [];
  });
}

const backendRoutes = walk(API_ROOT)
  .filter((p) => /BACKEND_URL/.test(fs.readFileSync(p, 'utf8')))
  .map((p) => path.relative(API_ROOT, p).split(path.sep).join('/'))
  .sort();

describe('identity forwarding inventory', () => {
  test('the inventory finds the backend-facing routes (sanity)', () => {
    expect(backendRoutes.length).toBeGreaterThanOrEqual(9);
    expect(backendRoutes).toContain('proxy/route.ts');
    expect(backendRoutes).toContain('session/[id]/ask/route.ts');
  });

  test.each(backendRoutes)('%s forwards identity or is exempt with a reason', (rel) => {
    const src = fs.readFileSync(path.join(API_ROOT, rel), 'utf8');
    if (rel in EXEMPT) {
      expect(EXEMPT[rel].length).toBeGreaterThan(20);
      return;
    }
    expect(src).toMatch(/from '@\/lib\/identity-headers'/);
    expect(src).toMatch(/forwardIdentityHeaders\(/);
    // No hand-rolled header copying next to the helper either.
    expect(src).not.toMatch(/headers\.get\('x-user-(id|tier)'\)/);
  });

  test('every EXEMPT entry still exists (no stale exemptions)', () => {
    for (const rel of Object.keys(EXEMPT)) expect(backendRoutes).toContain(rel);
  });
});
