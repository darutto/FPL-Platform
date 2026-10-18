'use client';

/**
 * Who may open the full-screen "Presentar" calendar: the owner's own accounts only.
 *
 * The Clerk user carries no email (the Patreon mapper cannot parse it), so the accounts
 * are not matched by address here. The sign-in sync already marks the addresses listed in
 * ADMIN_EMAILS with `publicMetadata.role = 'admin'` (see /api/auth/sync-patreon); that mark
 * is the one switch. Nothing is exposed by hiding the button: the view only re-lays-out data
 * the public calendar already shows.
 */
import { useUser } from '@clerk/nextjs';

export function usePresentationAccess(): boolean {
  const { isLoaded, user } = useUser();
  return isLoaded && (user?.publicMetadata as { role?: string } | undefined)?.role === 'admin';
}
