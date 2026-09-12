/**
 * Identity forwarding on the session routes — i79.
 *
 * The bug: `/api/session/{id}/ask` sent only `Content-Type` to the backend, so
 * the follow-up-session turn arrived as anonymous/free and a premium member
 * lost squad, tier and quota bucket mid-conversation. Mirrors proxy.test.ts.
 *
 * Asserts on what `fetch` was CALLED with (the outgoing backend request), not
 * on the helper's return value.
 */
import { NextRequest } from 'next/server';

const mockFetch = jest.fn<Promise<Response>, [RequestInfo | URL, RequestInit?]>();
(global as unknown as Record<string, unknown>).fetch = mockFetch;

const IDENTITY = { 'x-user-id': 'user_clerk_123', 'x-user-tier': 'patreon_premium' };

function jsonReq(url: string, body: unknown, headers: Record<string, string> = {}) {
  return new NextRequest(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  });
}

function backend(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function sentHeaders(): Record<string, string> {
  const [, init] = mockFetch.mock.calls[0];
  return (init?.headers ?? {}) as Record<string, string>;
}

beforeEach(() => {
  mockFetch.mockReset();
  process.env.FPL_BACKEND_URL = 'http://localhost:8000';
});

describe('/api/session/[id]/ask — identity forwarding', () => {
  const ctx = { params: Promise.resolve({ id: 'sess-1' }) };

  test('forwards x-user-id / x-user-tier set by middleware to the backend', async () => {
    mockFetch.mockResolvedValueOnce(backend({ final_text: 'ok', session_id: 'sess-1' }));
    const { POST } = await import('../app/api/session/[id]/ask/route');
    const res = await POST(
      jsonReq('http://localhost:3000/api/session/sess-1/ask', { question: 'y ahora?' }, IDENTITY),
      ctx,
    );

    expect(res.status).toBe(200);
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(String(mockFetch.mock.calls[0][0])).toMatch(/\/session\/sess-1\/ask$/);
    expect(sentHeaders()).toMatchObject({ 'Content-Type': 'application/json', ...IDENTITY });
  });

  test('anonymous (no identity headers) → none forwarded, Content-Type kept', async () => {
    mockFetch.mockResolvedValueOnce(backend({ final_text: 'ok' }));
    const { POST } = await import('../app/api/session/[id]/ask/route');
    await POST(jsonReq('http://localhost:3000/api/session/sess-1/ask', { question: 'q' }), ctx);

    const h = sentHeaders();
    expect(h['Content-Type']).toBe('application/json');
    expect(h['x-user-id']).toBeUndefined();
    expect(h['x-user-tier']).toBeUndefined();
  });

  test('backend 404 (expired session) passes through', async () => {
    mockFetch.mockResolvedValueOnce(backend({ detail: 'session not found' }, 404));
    const { POST } = await import('../app/api/session/[id]/ask/route');
    const res = await POST(
      jsonReq('http://localhost:3000/api/session/sess-1/ask', { question: 'q' }, IDENTITY),
      ctx,
    );
    expect(res.status).toBe(404);
  });
});

describe('/api/session — identity forwarding on create', () => {
  test('with seed: identity + Content-Type + body', async () => {
    mockFetch.mockResolvedValueOnce(backend({ session_id: 's' }));
    const { POST } = await import('../app/api/session/route');
    await POST(jsonReq('http://localhost:3000/api/session', { seed: { a: 1 } }, IDENTITY));

    const [, init] = mockFetch.mock.calls[0];
    expect(init?.headers).toMatchObject({ 'Content-Type': 'application/json', ...IDENTITY });
    expect(JSON.parse(init?.body as string)).toEqual({ seed: { a: 1 } });
  });

  test('without seed: identity forwarded, no body, no Content-Type', async () => {
    mockFetch.mockResolvedValueOnce(backend({ session_id: 's' }));
    const { POST } = await import('../app/api/session/route');
    await POST(
      new NextRequest('http://localhost:3000/api/session', { method: 'POST', headers: IDENTITY }),
    );

    const [, init] = mockFetch.mock.calls[0];
    expect(init?.headers).toEqual(IDENTITY);
    expect(init?.body).toBeUndefined();
  });
});

describe('/api/session/[id] — identity forwarding on delete', () => {
  test('DELETE forwards identity', async () => {
    mockFetch.mockResolvedValueOnce(backend({ status: 'cleared', session_id: 'sess-1' }));
    const { DELETE } = await import('../app/api/session/[id]/route');
    await DELETE(
      new NextRequest('http://localhost:3000/api/session/sess-1', {
        method: 'DELETE',
        headers: IDENTITY,
      }),
      { params: Promise.resolve({ id: 'sess-1' }) },
    );
    const [, init] = mockFetch.mock.calls[0];
    expect(init?.method).toBe('DELETE');
    expect(init?.headers).toEqual(IDENTITY);
  });
});
