import { NextRequest } from 'next/server';

const mockFetch = jest.fn<Promise<Response>, [RequestInfo | URL, RequestInit?]>();
(global as unknown as Record<string, unknown>).fetch = mockFetch;

function makeRequest(authorization?: string): NextRequest {
  return new NextRequest('http://localhost:3000/api/auth/patreon-userinfo', {
    method: 'GET',
    headers: authorization ? { Authorization: authorization } : {},
  });
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('/api/auth/patreon-userinfo', () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  test('rejects requests without a bearer token', async () => {
    const { GET } = await import('../app/api/auth/patreon-userinfo/route');
    const response = await GET(makeRequest());

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: 'missing_bearer_token' });
    expect(mockFetch).not.toHaveBeenCalled();
  });

  test('flattens Patreon JSON:API identity into Clerk claims', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        data: {
          id: 'patreon-user-123',
          type: 'user',
          attributes: { email: 'patron@example.com' },
        },
      }),
    );

    const { GET } = await import('../app/api/auth/patreon-userinfo/route');
    const response = await GET(makeRequest('Bearer secret-access-token'));

    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('no-store');
    expect(await response.json()).toEqual({
      sub: 'patreon-user-123',
      email: 'patron@example.com',
      email_verified: true,
    });

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0];
    expect(String(url)).toBe(
      'https://www.patreon.com/api/oauth2/v2/identity?fields[user]=email',
    );
    expect(init?.headers).toEqual({
      Accept: 'application/json',
      Authorization: 'Bearer secret-access-token',
    });
    expect(init?.cache).toBe('no-store');
  });

  test('does not expose the upstream response when Patreon rejects the token', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ error: 'sensitive upstream detail' }, 401),
    );

    const { GET } = await import('../app/api/auth/patreon-userinfo/route');
    const response = await GET(makeRequest('Bearer expired-token'));

    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ error: 'patreon_identity_error' });
  });

  test('rejects a successful Patreon response without a stable user id', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ data: { attributes: { email: 'patron@example.com' } } }),
    );

    const { GET } = await import('../app/api/auth/patreon-userinfo/route');
    const response = await GET(makeRequest('Bearer secret-access-token'));

    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ error: 'missing_patreon_user_id' });
  });

  test('returns a controlled error when Patreon is unreachable', async () => {
    mockFetch.mockRejectedValueOnce(new Error('network failure'));

    const { GET } = await import('../app/api/auth/patreon-userinfo/route');
    const response = await GET(makeRequest('Bearer secret-access-token'));

    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ error: 'patreon_unreachable' });
  });
});
