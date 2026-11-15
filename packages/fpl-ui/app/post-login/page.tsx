'use client';

import { useEffect } from 'react';
import { useAuth } from '@clerk/nextjs';
import { useT } from '@/lib/i18n/LocaleProvider';
import { PENDING_NEXT_KEY, sanitizeNext } from '@/lib/safe-next';

/** Destination from ?next= (preferred) or the sessionStorage fallback set on /login; consumed once. */
function takeDestination(): string {
  let stored: string | null = null;
  try {
    stored = sessionStorage.getItem(PENDING_NEXT_KEY);
    sessionStorage.removeItem(PENDING_NEXT_KEY);
  } catch {
    /* storage blocked */
  }
  const fromUrl = new URLSearchParams(window.location.search).get('next');
  return sanitizeNext(fromUrl ?? stored);
}

export default function PostLoginPage() {
  const { getToken } = useAuth();
  const t = useT();

  useEffect(() => {
    let cancelled = false;
    fetch('/api/auth/sync-patreon', { method: 'POST' })
      .then((res) => res.json())
      .then(async () => {
        if (cancelled) return;
        // updateUserMetadata doesn't refresh the active session token, so
        // refresh it before navigating so middleware/quota see the freshly
        // synced tier.
        await getToken({ skipCache: true });
        // Everyone lands in the chat: free gets a limited taste (5 msgs/day),
        // paid tiers get more. /subscribe is reached via in-app upgrade prompts
        // (e.g. the quota wall), never forced here.
        window.location.href = takeDestination();
      })
      .catch(() => {
        // Sync failed — still let them in; middleware admits any signed-in user
        // and the backend defaults to the free quota bucket.
        if (!cancelled) window.location.href = takeDestination();
      });
    return () => {
      cancelled = true;
    };
  }, [getToken]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-bf-bg text-bf-text">
      <p className="text-sm text-bf-gray">{t('postLogin.verifying')}</p>
    </main>
  );
}
