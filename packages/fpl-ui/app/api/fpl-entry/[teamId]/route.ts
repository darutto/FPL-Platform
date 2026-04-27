/**
 * Server-side proxy → FPL official API entry + history.
 *
 * Fetches two public FPL endpoints in parallel and returns the combined
 * data needed to build a SquadContext. Runs server-side so the browser
 * never talks to fantasy.premierleague.com directly (avoids CORS).
 *
 * GET /api/fpl-entry/{teamId}
 *   → { entry: FplEntryRaw, history: FplHistoryRaw }
 *
 * HTTP status:
 *   200  — both fetches succeeded
 *   400  — teamId is not a positive integer
 *   404  — FPL API returned 404 (team ID does not exist)
 *   502  — FPL API unreachable or returned unexpected error
 *
 * FPL API references:
 *   https://fantasy.premierleague.com/api/entry/{id}/
 *   https://fantasy.premierleague.com/api/entry/{id}/history/
 */
import { NextRequest, NextResponse } from 'next/server';

const FPL_BASE = 'https://fantasy.premierleague.com/api';

export async function GET(
  _request: NextRequest,
  context: { params: Promise<{ teamId: string }> },
) {
  const { teamId } = await context.params;

  // Validate: must be a positive integer
  if (!/^\d+$/.test(teamId) || parseInt(teamId, 10) <= 0) {
    return NextResponse.json({ error: 'Invalid team ID' }, { status: 400 });
  }

  let entryRes: Response;
  let historyRes: Response;
  try {
    [entryRes, historyRes] = await Promise.all([
      fetch(`${FPL_BASE}/entry/${teamId}/`),
      fetch(`${FPL_BASE}/entry/${teamId}/history/`),
    ]);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json(
      { error: `FPL API unreachable: ${message}` },
      { status: 502 },
    );
  }

  // Treat 404 from either endpoint as an unknown team ID
  if (entryRes.status === 404 || historyRes.status === 404) {
    return NextResponse.json(
      { error: 'Team ID not found' },
      { status: 404 },
    );
  }

  if (!entryRes.ok || !historyRes.ok) {
    return NextResponse.json(
      { error: `FPL API error (entry: ${entryRes.status}, history: ${historyRes.status})` },
      { status: 502 },
    );
  }

  const [entry, history] = await Promise.all([
    entryRes.json(),
    historyRes.json(),
  ]);

  return NextResponse.json({ entry, history });
}
