/**
 * The one definition of "owner account": Clerk publicMetadata.role === 'admin', which
 * /api/auth/sync-patreon sets for the addresses in ADMIN_EMAILS at sign-in. Shared by the
 * Presentar button and the English version's rollout gate.
 */
export function isAdminMetadata(metadata: unknown): boolean {
  return (metadata as { role?: unknown } | null | undefined)?.role === 'admin';
}
