/**
 * Middleware trust boundary — i79 (and the forgery hole found with it).
 *
 * Asserts on the request that LEAVES the middleware, not on local variables:
 * `NextResponse.next({ request: { headers } })` publishes the outgoing request
 * headers as `x-middleware-override-headers` (the full list) plus one
 * `x-middleware-request-<name>` per header. That is what Next hands to the
 * route handler, so it is the only thing worth asserting.
 *
 *   anonymous  + forged x-user-*         → nothing reaches the route
 *   signed-in  + forged x-user-* (other) → Clerk's values, not the forged ones
 *   signed-in  + no x-user-*             → Clerk's values
 *   anonymous  on a protected route      → redirect (unchanged behaviour)
 *
 * Mutation notes (each was tried while writing this file):
 *   - drop a `headers.delete(...)`             → test 1 fails
 *   - return bare `NextResponse.next()` for
 *     anonymous callers (the pre-i79 shape)    → test 1 fails (headers untouched)
 *   - set identity before the delete           → test 2 fails
 */
import { NextRequest } from 'next/server';

const mockAuth = jest.fn();

jest.mock('@clerk/nextjs/server', () => ({
  // Reduce clerkMiddleware to "call the handler with (auth, req)". We are not
  // testing Clerk; we are testing what our handler does with the request.
  clerkMiddleware: (handler: (auth: () => unknown, req: NextRequest) => unknown) =>
    (req: NextRequest) => handler(mockAuth, req),
  createRouteMatcher: (patterns: string[]) => (req: NextRequest) =>
    patterns.some((p) => new RegExp('^' + p.replace('(.*)', '.*') + '$').test(req.nextUrl.pathname)),
}));

type Outgoing = { list: string[]; get: (name: string) => string | null };

/** Decode the outgoing-request headers published by NextResponse.next(). */
function outgoing(res: { headers: Headers }): Outgoing {
  const raw = res.headers.get('x-middleware-override-headers');
  const list = raw ? raw.split(',').map((s) => s.trim()) : [];
  return {
    list,
    get: (name) => res.headers.get(`x-middleware-request-${name}`),
  };
}

function req(path: string, headers: Record<string, string> = {}): NextRequest {
  return new NextRequest(`http://localhost:3000${path}`, { method: 'POST', headers });
}

async function run(path: string, headers?: Record<string, string>) {
  const mod = await import('../middleware');
  const res = await (mod.default as unknown as (r: NextRequest) => Promise<{ headers: Headers; status: number }>)(
    req(path, headers),
  );
  return res;
}

describe('middleware identity trust boundary', () => {
  beforeEach(() => {
    mockAuth.mockReset();
  });

  test('anonymous caller with forged identity headers → stripped before the route', async () => {
    mockAuth.mockResolvedValue({ userId: null, sessionClaims: undefined });
    const res = await run('/api/proxy', {
      'x-user-id': 'user_forged',
      'x-user-tier': 'patreon_premium',
      'x-keep-me': 'yes',
    });
    const out = outgoing(res);
    // The middleware DID rewrite the request (override list present) …
    expect(out.list).toContain('x-keep-me');
    // … and the forged identity is gone from it.
    expect(out.list).not.toContain('x-user-id');
    expect(out.list).not.toContain('x-user-tier');
    expect(out.get('x-user-id')).toBeNull();
    expect(out.get('x-user-tier')).toBeNull();
  });

  test('signed-in caller with forged headers → Clerk identity wins', async () => {
    mockAuth.mockResolvedValue({
      userId: 'user_clerk_123',
      sessionClaims: { metadata: { tier: 'patreon_basic' } },
    });
    const res = await run('/api/proxy', {
      'x-user-id': 'user_someone_else',
      'x-user-tier': 'patreon_premium',
    });
    const out = outgoing(res);
    expect(out.get('x-user-id')).toBe('user_clerk_123');
    expect(out.get('x-user-tier')).toBe('patreon_basic');
  });

  test('signed-in caller without identity headers → Clerk identity set', async () => {
    mockAuth.mockResolvedValue({
      userId: 'user_clerk_456',
      sessionClaims: { metadata: { tier: 'patreon_premium' } },
    });
    const res = await run('/api/session/abc/ask');
    const out = outgoing(res);
    expect(out.get('x-user-id')).toBe('user_clerk_456');
    expect(out.get('x-user-tier')).toBe('patreon_premium');
  });

  test('signed-in caller with no tier claim → free', async () => {
    mockAuth.mockResolvedValue({ userId: 'user_clerk_789', sessionClaims: {} });
    const out = outgoing(await run('/api/proxy'));
    expect(out.get('x-user-tier')).toBe('free');
  });

  test('anonymous caller on a protected route → redirect to /login', async () => {
    mockAuth.mockResolvedValue({ userId: null, sessionClaims: undefined });
    const res = await run('/chat');
    expect(res.status).toBe(307);
    expect(res.headers.get('location')).toMatch(/\/login$/);
  });
});
