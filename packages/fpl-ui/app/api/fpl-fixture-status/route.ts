/**
 * Current/upcoming FPL gameweek for the public fixture ticker.
 *
 * Also reports `finished_gw` — how far the real league has actually got. That
 * is the independent yardstick the /fixtures provenance stamp compares the
 * shipped bundle's `gameweeks_played` against; without a live number the board
 * could only repeat what the bundle says about itself.
 */
import { NextResponse } from 'next/server';

const FPL_BASE = 'https://fantasy.premierleague.com/api';

interface BootstrapEvent {
  id: number;
  is_current: boolean;
  is_next: boolean;
  finished: boolean;
}

export async function GET() {
  try {
    const response = await fetch(`${FPL_BASE}/bootstrap-static/`, {
      next: { revalidate: 86_400 },
    });
    if (!response.ok) {
      return NextResponse.json({ next_gw: null, finished_gw: null }, { status: 502 });
    }

    const bootstrap = await response.json() as { events?: BootstrapEvent[] };
    const events = bootstrap.events ?? [];
    // `is_next` is the authoritative display anchor. During a live GW it is
    // the following GW; current is a safe fallback when no next event exists.
    const next = events.find((event) => event.is_next) ?? events.find((event) => event.is_current);
    const finished = events.filter((event) => event.finished).map((event) => event.id);
    return NextResponse.json(
      { next_gw: next?.id ?? null, finished_gw: finished.length ? Math.max(...finished) : 0 },
      { headers: { 'Cache-Control': 'public, max-age=86400, s-maxage=86400' } },
    );
  } catch {
    return NextResponse.json({ next_gw: null, finished_gw: null }, { status: 502 });
  }
}
