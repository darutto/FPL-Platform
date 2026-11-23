/**
 * /api/eo-warm: signed-in users only (identity set by the middleware); body and status passed through.
 */
import { NextRequest } from 'next/server';
import { POST } from '../app/api/eo-warm/route';

const body = JSON.stringify({ team_id: 5, league_id: 7 });

function req(headers: Record<string, string> = {}) {
  return new NextRequest('http://localhost/api/eo-warm', { method: 'POST', headers, body });
}

describe('POST /api/eo-warm', () => {
  const realFetch = global.fetch;
  afterEach(() => {
    global.fetch = realFetch;
  });

  test('an anonymous request is refused and never reaches the backend', async () => {
    const f = jest.fn();
    global.fetch = f as unknown as typeof fetch;
    expect((await POST(req())).status).toBe(401);
    expect(f).not.toHaveBeenCalled();
  });

  test('a signed-in request is forwarded with its identity; the backend status is passed through', async () => {
    const f = jest.fn().mockResolvedValue(new Response(JSON.stringify({ started: {} }), { status: 429 }));
    global.fetch = f as unknown as typeof fetch;
    const res = await POST(req({ 'x-user-id': 'user_1', 'x-user-tier': 'free' }));
    expect(res.status).toBe(429);
    const [url, init] = f.mock.calls[0];
    expect(String(url)).toMatch(/\/eo\/warm$/);
    expect(init.headers['x-user-id']).toBe('user_1');
    expect(JSON.parse(init.body)).toEqual({ team_id: 5, league_id: 7 });
  });
});
