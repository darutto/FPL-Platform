/**
 * The language of THIS request, for server components (layout, metadata). Gathers the facts
 * (rollout flag, Clerk role, bf_locale cookie, Accept-Language) and hands them to the shared
 * resolveLocale(); no policy lives here.
 */
import { cache } from 'react';
import { cookies, headers } from 'next/headers';
import { auth } from '@clerk/nextjs/server';
import { LOCALE_ROLLOUT } from '@/lib/features';
import { isAdminMetadata } from '@/lib/admin-role';
import { LOCALE_COOKIE, canChooseLocale, resolveLocale, type Locale } from './locale';

async function requestIsAdmin(): Promise<boolean> {
  // Same shortcut as the Presentar button: `next dev` has no Clerk session to speak of.
  if (process.env.NODE_ENV === 'development') return true;
  try {
    const { sessionClaims } = await auth();
    return isAdminMetadata(sessionClaims?.metadata);
  } catch {
    // No Clerk context (build, misconfiguration): treated as signed out, so Spanish.
    return false;
  }
}

export const getRequestLocale = cache(async (): Promise<{ locale: Locale; canSwitch: boolean }> => {
  const [isAdmin, jar, requestHeaders] = await Promise.all([requestIsAdmin(), cookies(), headers()]);
  const facts = {
    rollout: LOCALE_ROLLOUT,
    isAdmin,
    cookie: jar.get(LOCALE_COOKIE)?.value ?? null,
    acceptLanguage: requestHeaders.get('accept-language'),
  };
  return { locale: resolveLocale(facts), canSwitch: canChooseLocale(facts) };
});
