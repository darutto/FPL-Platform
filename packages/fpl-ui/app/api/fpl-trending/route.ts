/**
 * Server-side proxy → FPL "trending transfers" for the chat starter prompts.
 *
 * Returns the current most-transferred-IN (top buys) and most-transferred-OUT
 * (top sells) player web_names, so the empty-chat prompts stay timely without
 * code edits. Runs server-side (no CORS) and caches the bootstrap for 10 min.
 *
 * GET /api/fpl-trending
 *   → { active: boolean, in: string[], out: string[] }
 *
 * `active` is false pre-season / between gameweeks when FPL has not yet
 * accumulated any transfer counts (all fields 0) — the client then keeps its
 * curated static prompts. Only web_names that are UNIQUE across the element
 * list are returned, so each one resolves unambiguously via the backend player
 * resolver (a bare "Palmer" with two Palmers would be ambiguous, so it's
 * dropped).
 *
 * FPL API reference:
 *   https://fantasy.premierleague.com/api/bootstrap-static/
 */
import { NextResponse } from 'next/server';

const FPL_BASE = 'https://fantasy.premierleague.com/api';
const TOP_N = 5;

interface BootstrapElement {
  web_name: string;
  transfers_in_event: number;
  transfers_out_event: number;
  transfers_in: number;
  transfers_out: number;
}

/** Empty (inactive) payload — the client falls back to its static prompts. */
const INACTIVE = { active: false, in: [] as string[], out: [] as string[] };

export async function GET() {
  let bootstrap: { elements: BootstrapElement[] };
  try {
    const res = await fetch(`${FPL_BASE}/bootstrap-static/`, { next: { revalidate: 600 } });
    if (!res.ok) return NextResponse.json(INACTIVE);
    bootstrap = await res.json();
  } catch {
    return NextResponse.json(INACTIVE);
  }

  const elements = bootstrap.elements ?? [];

  // web_names claimed by more than one element are ambiguous → never suggest
  // them (they wouldn't resolve to a single player in the chat).
  const nameCounts = new Map<string, number>();
  for (const e of elements) nameCounts.set(e.web_name, (nameCounts.get(e.web_name) ?? 0) + 1);
  const isUnique = (e: BootstrapElement) => nameCounts.get(e.web_name) === 1;

  // Prefer this-gameweek movement (the classic "top transfers" signal); fall
  // back to season totals if the event counters are all zero (freshly rolled GW).
  const eventSignal = elements.some((e) => e.transfers_in_event > 0 || e.transfers_out_event > 0);
  const inField = eventSignal ? 'transfers_in_event' : 'transfers_in';
  const outField = eventSignal ? 'transfers_out_event' : 'transfers_out';

  const topBy = (field: keyof BootstrapElement) =>
    elements
      .filter((e) => isUnique(e) && (e[field] as number) > 0)
      .sort((a, b) => (b[field] as number) - (a[field] as number))
      .slice(0, TOP_N)
      .map((e) => e.web_name);

  const inList = topBy(inField);
  const outList = topBy(outField);

  // Need at least two buys (for a comparison) and one sell (for a transfer).
  const active = inList.length >= 2 && outList.length >= 1;
  if (!active) return NextResponse.json(INACTIVE);

  return NextResponse.json({ active: true, in: inList, out: outList });
}
