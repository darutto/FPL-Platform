import { NextRequest } from 'next/server';
import { MAX_Q_LENGTH, loginPathFor, postLoginPathFor, sanitizeNext } from '@/lib/safe-next';

describe('sanitizeNext — open-redirect hardening', () => {
  test.each([
    'https://evil.com',
    'http://evil.com/chat?q=x',
    '//evil.com',
    '//evil.com/chat?q=x',
    '/\\evil.com',
    '/chat?q=x\\..\\evil',
    '\\\\evil.com',
    'javascript:alert(1)',
    ' javascript:alert(1)',
    '/chatx',
    '/chatx?q=hola',
    '/chat/../admin',
    '/chat/sub?q=x',
    '/chat%2f%2fevil.com',
    '%2f%2fevil.com',
    '%2fchat?q=x',
    '/CHAT?q=hola',
    '/Chat?q=hola',
    '/login',
    '/wc/chat?q=x',
    'chat?q=x',
    '/chat?q=a\nb',
    '/chat\r?q=x',
    '',
    '   ',
  ])('rejects %j → /chat', (raw) => {
    expect(sanitizeNext(raw)).toBe('/chat');
  });

  test.each([undefined, null, 42, {}, ['/chat?q=x']])('non-string %j → /chat', (raw) => {
    expect(sanitizeNext(raw)).toBe('/chat');
  });

  test('plain /chat and q-less/empty-q forms collapse to /chat', () => {
    expect(sanitizeNext('/chat')).toBe('/chat');
    expect(sanitizeNext('/chat?')).toBe('/chat');
    expect(sanitizeNext('/chat?q=')).toBe('/chat');
    expect(sanitizeNext('/chat?q=%20%20')).toBe('/chat');
    expect(sanitizeNext('/chat?other=1')).toBe('/chat');
  });

  test('keeps only q; drops other params and fragments', () => {
    expect(sanitizeNext('/chat?evil=//x&q=hola&next=https://evil.com#frag')).toBe('/chat?q=hola');
  });

  test('a q that merely looks like a URL stays inert data', () => {
    expect(sanitizeNext('/chat?q=https%3A%2F%2Fevil.com')).toBe('/chat?q=https%3A%2F%2Fevil.com');
  });

  test('q longer than the cap is cut, by code point', () => {
    const out = sanitizeNext(`/chat?q=${'a'.repeat(1000)}`);
    expect(decodeURIComponent(out.slice('/chat?q='.length))).toBe('a'.repeat(MAX_Q_LENGTH));
    const emoji = sanitizeNext(`/chat?q=${encodeURIComponent('⚽'.repeat(400))}`);
    expect(Array.from(decodeURIComponent(emoji.slice('/chat?q='.length)))).toHaveLength(MAX_Q_LENGTH);
  });

  test('absurdly long raw input is ignored', () => {
    expect(sanitizeNext(`/chat?q=${'a'.repeat(10000)}`)).toBe('/chat');
  });
});

describe('round trip (accents, ¿?, &, spaces)', () => {
  const prompts = [
    'Rendimiento de Haaland',
    '¿Quién capitanear en la jornada 12? Salah & Haaland',
    'Mbappé, Müller y Ødegaard: a=b&c=d #1 100%',
    '⚽ ¿Vale la pena Saka?',
  ];

  test.each(prompts)('middleware → /login → /post-login preserves %j', (prompt) => {
    const original = `/chat?q=${encodeURIComponent(prompt)}`;
    // middleware step: /login?next=<encoded>
    const login = new URL(loginPathFor(original), 'http://localhost');
    expect(login.pathname).toBe('/login');
    // /login reads ?next= (searchParams decodes once) and builds the Clerk redirect
    const afterAuth = new URL(postLoginPathFor(login.searchParams.get('next')), 'http://localhost');
    expect(afterAuth.pathname).toBe('/post-login');
    // /post-login reads ?next= and navigates
    const dest = new URL(sanitizeNext(afterAuth.searchParams.get('next')), 'http://localhost');
    expect(dest.pathname).toBe('/chat');
    expect(dest.searchParams.get('q')).toBe(prompt);
  });

  test('no q → plain /login and /post-login', () => {
    expect(loginPathFor('/chat')).toBe('/login');
    expect(postLoginPathFor(null)).toBe('/post-login');
    expect(postLoginPathFor('https://evil.com')).toBe('/post-login');
  });
});

describe('middleware redirect for anonymous visitors', () => {
  const mockAuth = jest.fn();
  beforeAll(() => {
    jest.doMock('@clerk/nextjs/server', () => ({
      clerkMiddleware: (h: (a: () => unknown, r: NextRequest) => unknown) => (r: NextRequest) => h(mockAuth, r),
      createRouteMatcher: (patterns: string[]) => (r: NextRequest) =>
        patterns.some((p) => new RegExp('^' + p.replace('(.*)', '.*') + '$').test(r.nextUrl.pathname)),
    }));
  });
  beforeEach(() => mockAuth.mockReset());

  async function visit(path: string, userId: string | null) {
    mockAuth.mockResolvedValue({ userId, sessionClaims: undefined });
    const mod = await import('../middleware');
    const res = await (mod.default as unknown as (r: NextRequest) => Promise<Response>)(
      new NextRequest(`http://localhost:3000${path}`),
    );
    return res;
  }

  test('anonymous /chat?q=… → /login?next=<encoded path+query>', async () => {
    const res = await visit('/chat?q=Rendimiento%20de%20Haaland', null);
    expect(res.status).toBe(307);
    const loc = new URL(res.headers.get('location')!);
    expect(loc.pathname).toBe('/login');
    expect(loc.searchParams.get('next')).toBe('/chat?q=Rendimiento%20de%20Haaland');
  });

  test('anonymous plain /chat and /wc/chat → plain /login', async () => {
    expect(new URL((await visit('/chat', null)).headers.get('location')!).search).toBe('');
    expect(new URL((await visit('/wc/chat?q=x', null)).headers.get('location')!).search).toBe('');
  });

  test('signed-in /chat?q=… is not redirected', async () => {
    const res = await visit('/chat?q=hola', 'user_1');
    expect(res.headers.get('location')).toBeNull();
  });
});
