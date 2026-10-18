/**
 * What /api/auth/sync-patreon does with the Patreon email: the address listed in
 * ADMIN_EMAILS gets role 'admin' (the "Presentar" switch), and the log line says,
 * without the address, which step failed when it does not.
 */
const updateUserMetadata = jest.fn(async () => undefined);
jest.mock('@clerk/nextjs/server', () => ({
  auth: async () => ({ userId: 'user_1' }),
  clerkClient: async () => ({
    users: {
      getUser: async () => ({ publicMetadata: {} }),
      getUserOauthAccessToken: async () => ({ data: [{ token: 'tok' }] }),
      updateUserMetadata,
    },
  }),
}));

function load(adminEmails: string, identity: unknown) {
  process.env.ADMIN_EMAILS = adminEmails;
  global.fetch = jest.fn(async (url: RequestInfo | URL) =>
    String(url).includes('patreon.com')
      ? ({ ok: true, json: async () => identity } as Response)
      : ({ ok: true } as Response),
  ) as unknown as typeof fetch;
  let route: typeof import('@/app/api/auth/sync-patreon/route');
  jest.isolateModules(() => {
    route = require('@/app/api/auth/sync-patreon/route');
  });
  return route!;
}

const identityWith = (email?: string) => ({ data: { attributes: email ? { email } : {} }, included: [] });

describe('sync-patreon admin role', () => {
  let info: jest.SpyInstance;
  beforeEach(() => {
    updateUserMetadata.mockClear();
    info = jest.spyOn(console, 'info').mockImplementation(() => undefined);
  });
  afterEach(() => info.mockRestore());

  test('an address in ADMIN_EMAILS (any case, spaces) is marked admin', async () => {
    const { POST } = load(' Leo@Example.com , other@example.com', identityWith('leo@example.com'));
    await POST();
    expect(updateUserMetadata).toHaveBeenCalledWith('user_1', { publicMetadata: { tier: 'patreon_premium', role: 'admin' } });
    expect(info).toHaveBeenCalledWith('[sync-patreon]', { outcome: 'admin', patreon_returned_email: true, admin_emails_configured: 2 });
  });

  test('Patreon sending no email never sets admin, and the log says so (not the address)', async () => {
    const { POST } = load('leo@example.com', identityWith(undefined));
    await POST();
    expect(updateUserMetadata).not.toHaveBeenCalledWith('user_1', expect.objectContaining({ publicMetadata: expect.objectContaining({ role: 'admin' }) }));
    expect(info).toHaveBeenCalledWith('[sync-patreon]', { outcome: 'member_lookup', patreon_returned_email: false, admin_emails_configured: 1 });
  });

  test('an email that is not listed is a normal member, and the log never carries it', async () => {
    const { POST } = load('leo@example.com', identityWith('patron@example.com'));
    await POST();
    expect(JSON.stringify(info.mock.calls)).not.toContain('patron@example.com');
    expect(info).toHaveBeenCalledWith('[sync-patreon]', { outcome: 'member_lookup', patreon_returned_email: true, admin_emails_configured: 1 });
  });
});
