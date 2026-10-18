/**
 * @jest-environment jsdom
 *
 * Who sees "Presentar": the owner accounts (Clerk role 'admin') in any deployed build,
 * and everyone only under `next dev`.
 */
import { renderHook } from '@testing-library/react';

import { usePresentationAccess } from '@/lib/presentation-access';

let clerkUser: { isLoaded: boolean; user: { publicMetadata: Record<string, unknown> } | null };
jest.mock('@clerk/nextjs', () => ({ useUser: () => clerkUser }));

const env = process.env as Record<string, string | undefined>;
const original = env.NODE_ENV;
afterEach(() => {
  env.NODE_ENV = original;
});

const access = (nodeEnv: string) => {
  env.NODE_ENV = nodeEnv;
  return renderHook(() => usePresentationAccess()).result.current;
};
const signedIn = (publicMetadata: Record<string, unknown>) => {
  clerkUser = { isLoaded: true, user: { publicMetadata } };
};

describe.each(['production', 'test'])('a deployed build (%s)', (nodeEnv) => {
  test('only the admin role opens it', () => {
    signedIn({ tier: 'patreon_premium', role: 'admin' });
    expect(access(nodeEnv)).toBe(true);
  });

  test.each([
    ['a premium patron without the role', { tier: 'patreon_premium' }],
    ['a free user', { tier: 'free' }],
    ['another role', { role: 'editor' }],
    ['no metadata at all', {}],
  ])('%s does not', (_label, metadata) => {
    signedIn(metadata);
    expect(access(nodeEnv)).toBe(false);
  });

  test('nobody signed in, or Clerk not loaded yet, does not', () => {
    clerkUser = { isLoaded: true, user: null };
    expect(access(nodeEnv)).toBe(false);
    clerkUser = { isLoaded: false, user: { publicMetadata: { role: 'admin' } } };
    expect(access(nodeEnv)).toBe(false);
  });
});

test('next dev shows it without a Clerk session, so local review works', () => {
  clerkUser = { isLoaded: true, user: null };
  expect(access('development')).toBe(true);
});
