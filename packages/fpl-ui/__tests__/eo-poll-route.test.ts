/**
 * /api/eo-poll: signed-in users only (identity set by the middleware), body and status passed through.
 */
import { NextRequest } from 'next/server';
import { POST } from '../app/api/eo-poll/route';

const body = JSON.stringify({ tool: 'get_near_rank_eo', team_id: 5 });

function req(headers: Record<string, string> = {}, raw: string = body) {
  return new NextRequest('http://localhost/api/eo-poll', { method: 'POST', headers, body: raw });
}

describe('POST /api/eo-poll', () => {
  const realFetch = global.fetch;
  afterEach(() => {
    global.fetch = realFetch;
  });

  test('an anonymous request is refused and never reaches the backend', async () => {
    const f = jest.fn();
    global.fetch = f as unknown as typeof fetch;
    const res = await POST(req());
    expect(res.status).toBe(401);
    expect(f).not.toHaveBeenCalled();
  });

  test('a signed-in request is forwarded with its identity, and the backend status is passed through', async () => {
    const f = jest.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'computing' }), { status: 429 }));
    global.fetch = f as unknown as typeof fetch;
    const res = await POST(req({ 'x-user-id': 'user_1', 'x-user-tier': 'free' }));
    expect(res.status).toBe(429);
    const [url, init] = f.mock.calls[0];
    expect(String(url)).toMatch(/\/eo\/poll$/);
    expect(init.headers['x-user-id']).toBe('user_1');
    expect(JSON.parse(init.body)).toEqual({ tool: 'get_near_rank_eo', team_id: 5 });
  });
});
