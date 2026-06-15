'use client';

import { useEffect } from 'react';
import { useAuth } from '@clerk/nextjs';

export default function PostLoginPage() {
  const { getToken } = useAuth();

  useEffect(() => {
    let cancelled = false;
    fetch('/api/auth/sync-patreon', { method: 'POST' })
      .then((res) => res.json())
      .then(async (data) => {
        if (cancelled) return;
        // updateUserMetadata doesn't refresh the active session token, so
        // middleware would still see the pre-sync tier without this.
        await getToken({ skipCache: true });
        window.location.href = data.tier === 'subscriber' ? '/chat' : '/subscribe';
      })
      .catch(() => {
        if (!cancelled) window.location.href = '/subscribe';
      });
    return () => {
      cancelled = true;
    };
  }, [getToken]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-bf-bg text-bf-text">
      <p className="text-sm text-bf-gray">Verificando tu membresía de Patreon...</p>
    </main>
  );
}
