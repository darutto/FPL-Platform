'use client';

/**
 * Who may open the full-screen "Presentar" calendar: the owner's own accounts only.
 *
 * The Clerk user carries no email (the Patreon mapper cannot parse it), so the accounts
 * are not matched by address here. The sign-in sync already marks the addresses listed in
 * ADMIN_EMAILS with `publicMetadata.role = 'admin'` (see /api/auth/sync-patreon); that mark
 * is the one switch. Nothing is exposed by hiding the button: the view only re-lays-out data
 * the public calendar already shows.
 *
 * `next dev` shows it to everyone so the view can be reviewed locally without a Clerk
 * session. NODE_ENV is 'production' in every deployed build (Vercel previews included),
 * so a deployed build never takes that branch.
 */
import { useUser } from '@clerk/nextjs';
import { isAdminMetadata } from '@/lib/admin-role';

export function usePresentationAccess(): boolean {
  const { isLoaded, user } = useUser();
  if (process.env.NODE_ENV === 'development') return true;
  return isLoaded && isAdminMetadata(user?.publicMetadata);
}
