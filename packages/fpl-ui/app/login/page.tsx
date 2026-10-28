'use client';

import { Suspense, useEffect } from 'react';
import { useSearchParams } from 'next/navigation';
import { SignIn } from '@clerk/nextjs';
import { PENDING_NEXT_KEY, postLoginPathFor, sanitizeNext, DEFAULT_NEXT } from '@/lib/safe-next';
import { useT } from '@/lib/i18n/LocaleProvider';

function LoginView() {
  const t = useT();
  const next = sanitizeNext(useSearchParams().get('next'));
  const afterAuth = postLoginPathFor(next);

  // Fallback if Clerk drops the URL param during the Patreon OAuth round-trip:
  // /post-login reads this (same tab, same origin) and clears it after use.
  useEffect(() => {
    try {
      if (next === DEFAULT_NEXT) sessionStorage.removeItem(PENDING_NEXT_KEY);
      else sessionStorage.setItem(PENDING_NEXT_KEY, next);
    } catch {
      /* storage blocked: the URL param still works */
    }
  }, [next]);

  return (
    <main className="login-page flex min-h-screen flex-col items-center justify-center bg-bf-bg px-4 text-bf-text">
      <div className="mb-6 text-center">
        <h1 className="font-display text-2xl text-bf-text">{t('login.title')}</h1>
        <p className="mt-2 text-sm text-bf-gray">
          {t('login.subtitle')}
        </p>
      </div>
      <SignIn
        routing="hash"
        withSignUp
        forceRedirectUrl={afterAuth}
        signUpForceRedirectUrl={afterAuth}
        appearance={{
          variables: {
            colorPrimary: '#FF6A4D',
            colorBackground: '#211F29',
            colorForeground: '#f0f0f0',
            colorMuted: '#33303f',
            colorMutedForeground: '#cfcdd9',
            colorInput: '#1c1a26',
            colorInputForeground: '#f0f0f0',
          },
          elements: {
            // Patreon is the only way in: nothing of an email form (or the "or" between) should ever show.
            dividerRow: { display: 'none' },
          },
        }}
      />
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginView />
    </Suspense>
  );
}
