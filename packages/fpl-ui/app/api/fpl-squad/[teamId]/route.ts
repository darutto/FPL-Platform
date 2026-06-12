/**
 * Server-side proxy → FPL official API current-GW squad picks (U2 pitch view).
 *
 * Joins three public FPL endpoints into the compact shape the SquadPitch
 * component renders. Runs server-side so the browser never talks to
 * fantasy.premierleague.com directly (avoids CORS).
 *
 * GET /api/fpl-squad/{teamId}
 *   → {
 *       gw: number,
 *       summary: { gw_points, total_points, bank },        // bank in tenths of £
 *       players: SquadPickPlayer[15]                        // ordered by pick position
 *     }
 *
 * HTTP status:
 *   200 — all fetches succeeded
 *   400 — teamId is not a positive integer
 *   404 — FPL API returned 404 (team or picks not found)
 *   502 — FPL API unreachable or returned unexpected error
 *
 * FPL API references:
 *   https://fantasy.premierleague.com/api/bootstrap-static/
 *   https://fantasy.premierleague.com/api/entry/{id}/event/{gw}/picks/
 *   https://fantasy.premierleague.com/api/event/{gw}/live/
 */
import { NextRequest, NextResponse } from 'next/server';

const FPL_BASE = 'https://fantasy.premierleague.com/api';

const ELEMENT_TYPE_TO_POS: Record<number, 'GK' | 'DEF' | 'MID' | 'FWD'> = {
  1: 'GK',
  2: 'DEF',
  3: 'MID',
  4: 'FWD',
};

interface BootstrapElement {
  id: number;
  web_name: string;
  element_type: number;
  team: number;
  now_cost: number;
  selected_by_percent: string;
  form: string;
}

interface BootstrapTeam {
  id: number;
  short_name: string;
}

interface BootstrapEvent {
  id: number;
  is_current: boolean;
}

interface PickEntry {
  element: number;
  position: number; // 1-11 starters, 12-15 bench
  is_captain: boolean;
  is_vice_captain: boolean;
}

interface LiveElement {
  id: number;
  stats: { total_points: number };
}

export async function GET(
  _request: NextRequest,
  context: { params: Promise<{ teamId: string }> },
) {
  const { teamId } = await context.params;

  if (!/^\d+$/.test(teamId) || parseInt(teamId, 10) <= 0) {
    return NextResponse.json({ error: 'Invalid team ID' }, { status: 400 });
  }

  // 1) bootstrap-static — element/team metadata + current GW.
  //    Large payload; cache server-side for 5 minutes.
  let bootstrap: {
    events: BootstrapEvent[];
    elements: BootstrapElement[];
    teams: BootstrapTeam[];
  };
  try {
    const res = await fetch(`${FPL_BASE}/bootstrap-static/`, {
      next: { revalidate: 300 },
    });
    if (!res.ok) {
      return NextResponse.json(
        { error: `FPL API error (bootstrap: ${res.status})` },
        { status: 502 },
      );
    }
    bootstrap = await res.json();
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json(
      { error: `FPL API unreachable: ${message}` },
      { status: 502 },
    );
  }

  const currentEvent = bootstrap.events.find((e) => e.is_current);
  if (!currentEvent) {
    return NextResponse.json(
      { error: 'No current gameweek (pre-season?)' },
      { status: 404 },
    );
  }
  const gw = currentEvent.id;

  // 2) picks + live GW points, in parallel
  let picksRes: Response;
  let liveRes: Response;
  try {
    [picksRes, liveRes] = await Promise.all([
      fetch(`${FPL_BASE}/entry/${teamId}/event/${gw}/picks/`),
      fetch(`${FPL_BASE}/event/${gw}/live/`, { next: { revalidate: 60 } }),
    ]);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json(
      { error: `FPL API unreachable: ${message}` },
      { status: 502 },
    );
  }

  if (picksRes.status === 404) {
    return NextResponse.json({ error: 'Team ID not found' }, { status: 404 });
  }
  if (!picksRes.ok || !liveRes.ok) {
    return NextResponse.json(
      { error: `FPL API error (picks: ${picksRes.status}, live: ${liveRes.status})` },
      { status: 502 },
    );
  }

  const [picksData, liveData] = await Promise.all([
    picksRes.json() as Promise<{
      picks: PickEntry[];
      entry_history: { points: number; total_points: number; bank: number };
    }>,
    liveRes.json() as Promise<{ elements: LiveElement[] }>,
  ]);

  const elementById = new Map(bootstrap.elements.map((e) => [e.id, e]));
  const teamById = new Map(bootstrap.teams.map((t) => [t.id, t.short_name]));
  const liveById = new Map(liveData.elements.map((e) => [e.id, e.stats.total_points]));

  const players = picksData.picks
    .slice()
    .sort((a, b) => a.position - b.position)
    .map((pick) => {
      const el = elementById.get(pick.element);
      return {
        id: pick.element,
        web_name: el?.web_name ?? `#${pick.element}`,
        team_short: el ? teamById.get(el.team) ?? '—' : '—',
        position: el ? ELEMENT_TYPE_TO_POS[el.element_type] ?? 'MID' : 'MID',
        price: el?.now_cost ?? 0,
        sel: el?.selected_by_percent ?? '0.0',
        form: el?.form ?? '0.0',
        gw_points: liveById.get(pick.element) ?? 0,
        pick_position: pick.position,
        is_starter: pick.position <= 11,
        is_captain: pick.is_captain,
      };
    });

  return NextResponse.json({
    gw,
    summary: {
      gw_points: picksData.entry_history.points,
      total_points: picksData.entry_history.total_points,
      bank: picksData.entry_history.bank,
    },
    players,
  });
}
