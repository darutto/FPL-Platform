/**
 * Proxy route unit tests — Phase 2.5 dev connectivity
 *
 * Tests the /api/proxy route handler in isolation (no live backend).
 * Validates:
 *   1. A well-formed POST request is forwarded to FPL_BACKEND_URL/ask.
 *   2. Backend 200 is passed through with its JSON body intact.
 *   3. Backend unreachable (fetch throws) returns 502 with a descriptive error.
 *   4. Malformed JSON in the incoming request returns 400.
 *   5. FPL_BACKEND_URL env var is respected; defaults to localhost:8000.
 */

import { NextRequest } from 'next/server';

// ---------------------------------------------------------------------------
// Module-level fetch mock — must be defined before importing the route module
// so the mock is in place when the module evaluates BACKEND_URL.
// ---------------------------------------------------------------------------

const mockFetch = jest.fn<Promise<Response>, [RequestInfo | URL, RequestInit?]>();

// next/server's globalThis.fetch used at module level reads process.env at
// import time. We patch it here before the dynamic import below.
(global as unknown as Record<string, unknown>).fetch = mockFetch;

// ---------------------------------------------------------------------------
// Helper: build a minimal NextRequest pointing at /api/proxy
// ---------------------------------------------------------------------------

function makeProxyRequest(body: unknown): NextRequest {
  return new NextRequest('http://localhost:3000/api/proxy', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

function makeBackendResponse(
  body: unknown,
  status = 200,
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('/api/proxy — POST handler', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    // Default env — tests that rely on a specific URL set it themselves
    process.env.FPL_BACKEND_URL = 'http://localhost:8000';
  });

  test('forwards request body to backend /ask and returns 200 with JSON body', async () => {
    const backendBody = {
      final_text: 'Haaland is a safe captain pick.',
      outcome: 'ok',
      supported: true,
      intent: 'captain_score',
      review_passed: true,
      llm_used: false,
      orch_outcome: null,
      captain: null,
      captain_ranking: null,
      comparison: null,
      transfer: null,
      chip: null,
      fixture_run: null,
      differential: null,
      sub_responses: null,
    };
    mockFetch.mockResolvedValueOnce(makeBackendResponse(backendBody, 200));

    // Dynamic import ensures BACKEND_URL is read after we set the env var.
    const { POST } = await import('../app/api/proxy/route');
    const request = makeProxyRequest({ question: 'should I captain Haaland' });
    const response = await POST(request);

    expect(response.status).toBe(200);
    const data = await response.json();
    expect(data.final_text).toBe('Haaland is a safe captain pick.');
    expect(data.outcome).toBe('ok');
    expect(data.orch_outcome).toBeNull();

    // Verify the backend was called at the correct URL with the right body
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [calledUrl, calledInit] = mockFetch.mock.calls[0];
    expect(calledUrl).toMatch(/\/ask$/);
    expect(calledInit?.method).toBe('POST');
    const sentBody = JSON.parse(calledInit?.body as string);
    expect(sentBody.question).toBe('should I captain Haaland');
  });

  test('backend unreachable → 502 with descriptive error', async () => {
    mockFetch.mockRejectedValueOnce(new Error('ECONNREFUSED'));

    const { POST } = await import('../app/api/proxy/route');
    const request = makeProxyRequest({ question: 'gameweek?' });
    const response = await POST(request);

    expect(response.status).toBe(502);
    const data = await response.json();
    expect(data.error).toMatch(/Backend unreachable/i);
    expect(data.error).toMatch(/ECONNREFUSED/);
  });

  test('malformed JSON in incoming request → 400', async () => {
    const { POST } = await import('../app/api/proxy/route');
    const badRequest = new NextRequest('http://localhost:3000/api/proxy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: 'not json at all {{{',
    });
    const response = await POST(badRequest);

    expect(response.status).toBe(400);
    const data = await response.json();
    expect(data.error).toMatch(/Invalid JSON/i);
  });

  test('backend 422 is passed through to caller', async () => {
    mockFetch.mockResolvedValueOnce(
      makeBackendResponse({ detail: 'question field required' }, 422),
    );

    const { POST } = await import('../app/api/proxy/route');
    const request = makeProxyRequest({});
    const response = await POST(request);

    expect(response.status).toBe(422);
  });

  test('FPL_BACKEND_URL env var controls the target URL', async () => {
    process.env.FPL_BACKEND_URL = 'https://my-railway-backend.up.railway.app';
    mockFetch.mockResolvedValueOnce(makeBackendResponse({ ok: true }, 200));

    // Re-import with the new env var value by clearing Jest module cache
    jest.resetModules();
    (global as unknown as Record<string, unknown>).fetch = mockFetch;
    const { POST } = await import('../app/api/proxy/route');
    const request = makeProxyRequest({ question: 'test' });
    await POST(request);

    const [calledUrl] = mockFetch.mock.calls[0];
    expect(String(calledUrl)).toContain('my-railway-backend.up.railway.app/ask');
  });
});
