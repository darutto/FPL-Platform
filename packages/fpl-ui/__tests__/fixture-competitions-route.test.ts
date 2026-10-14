/**
 * /api/fpl-fixture-competitions: forwards the server-set identity headers, never
 * caches (the answer differs per tier), and degrades to "unavailable".
 */
import { NextRequest } from 'next/server';

const mockFetch = jest.fn<Promise<Response>, [RequestInfo | URL, RequestInit?]>();
(global as unknown as Record<string, unknown>).fetch = mockFetch;

const request = (headers: Record<string, string> = {}, qs = '') =>
  new NextRequest(`http://localhost:3000/api/fpl-fixture-competitions${qs}`, { headers });

describe('/api/fpl-fixture-competitions', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    process.env.FPL_BACKEND_URL = 'http://backend.test';
  });

  test('forwards identity headers and the query, and does not cache', async () => {
    mockFetch.mockResolvedValueOnce(new Response(JSON.stringify({ available: true, tier: 'premium', teams: {} })));
    const { GET } = await import('../app/api/fpl-fixture-competitions/route');
    const res = await GET(request({ 'x-user-id': 'user_1', 'x-user-tier': 'patreon_basic' }, '?team=ARS&evil=1'));
    const [url, init] = mockFetch.mock.calls[0];
    expect(String(url)).toBe('http://backend.test/fixtures/competitions?team=ARS');
    expect(init?.headers).toMatchObject({ 'x-user-id': 'user_1', 'x-user-tier': 'patreon_basic' });
    expect(res.headers.get('Cache-Control')).toBe('private, no-store');
    expect(await res.json()).toMatchObject({ tier: 'premium' });
  });

  test('anonymous caller: no identity headers are invented', async () => {
    mockFetch.mockResolvedValueOnce(new Response(JSON.stringify({ available: false })));
    const { GET } = await import('../app/api/fpl-fixture-competitions/route');
    await GET(request());
    const headers = mockFetch.mock.calls[0][1]?.headers as Record<string, string>;
    expect(headers['x-user-id']).toBeUndefined();
    expect(headers['x-user-tier']).toBeUndefined();
  });

  test.each([
    ['backend error', () => mockFetch.mockResolvedValueOnce(new Response('{}', { status: 500 }))],
    ['backend unreachable', () => mockFetch.mockRejectedValueOnce(new Error('down'))],
  ])('%s -> unavailable, not an error', async (_name, arrange) => {
    arrange();
    const { GET } = await import('../app/api/fpl-fixture-competitions/route');
    const res = await GET(request());
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ available: false });
  });
});
