/**
 * /fixtures-preview — PUBLIC off-season preview of the Track D fixture ticker.
 *
 * The FPL API hasn't rolled over to the new season, so the live /calendario
 * path returns "temporada finalizada". This page renders FixtureOutlookCard
 * with representative mock data so the card + runs + verdicts can be reviewed.
 * Not gated by Clerk (middleware only protects /chat and /wc). Throwaway /
 * FI7 seed — safe to delete.
 */
import FixtureOutlookCard from '@/components/intents/FixtureOutlookCard';
import type {
  FixtureOutlookMeta,
  FixtureOutlookGW,
  FixtureOutlookRun,
  TeamOutlook,
  OutlookClass,
  FixtureAxis,
} from '@/lib/types';

// --- compact builders -------------------------------------------------------

type Cell = { opp: string; home?: boolean };

function klassOf(band: number | null): OutlookClass {
  if (band === null) return 'blank';
  if (band <= 2) return 'good';
  if (band >= 4) return 'bad';
  return 'neutral';
}

function GW(
  gameweek: number,
  band: number | null,
  cells: Cell[],
  opt?: { dgw?: boolean; bgw?: boolean },
): FixtureOutlookGW {
  return {
    gameweek,
    band,
    klass: klassOf(band),
    is_dgw: !!opt?.dgw,
    is_bgw: !!opt?.bgw,
    fixtures: cells.map((c) => ({
      opponent_short: c.opp,
      is_home: c.home ?? true,
      band: band ?? 3,
    })),
  };
}

function run(
  type: 'good' | 'bad',
  start_gw: number,
  end_gw: number,
  intensity: 'strong' | 'mild',
): FixtureOutlookRun {
  return { type, start_gw, end_gw, length: end_gw - start_gw + 1, intensity };
}

function team(
  team_short: string,
  team_name: string,
  axis: FixtureAxis,
  verdict: string,
  series: FixtureOutlookGW[],
  runs: FixtureOutlookRun[],
): TeamOutlook {
  const bands = series.map((g) => g.band).filter((b): b is number => b !== null);
  const avg = bands.length ? Math.round((bands.reduce((a, b) => a + b, 0) / bands.length) * 100) / 100 : null;
  return { team_short, team_name, axis, avg_band: avg, verdict, series, runs };
}

// --- mock outlooks ----------------------------------------------------------

const ATTACK: FixtureOutlookMeta = {
  axis: 'attack',
  horizon: 8,
  current_gameweek: 1,
  teams: [
    team('ARS', 'Arsenal', 'attack',
      'Buen tramo ofensivo: 5 jornadas de calendario muy asequible (J1–J5).',
      [
        GW(1, 1, [{ opp: 'SUN' }]),
        GW(2, 2, [{ opp: 'BRE', home: false }]),
        GW(3, 1, [{ opp: 'LEE' }]),
        GW(4, 2, [{ opp: 'WOL', home: false }]),
        GW(5, 2, [{ opp: 'BUR' }]),
        GW(6, 4, [{ opp: 'LIV', home: false }]),
        GW(7, 4, [{ opp: 'CHE' }]),
        GW(8, 5, [{ opp: 'MCI', home: false }]),
      ],
      [run('good', 1, 5, 'strong'), run('bad', 6, 8, 'mild')],
    ),
    team('NEW', 'Newcastle', 'attack',
      'Buen tramo ofensivo: 4 jornadas de calendario asequible (J4–J7).',
      [
        GW(1, 3, [{ opp: 'TOT' }]),
        GW(2, null, [], { bgw: true }),
        GW(3, 3, [{ opp: 'AVL', home: false }]),
        GW(4, 2, [{ opp: 'BUR' }]),
        GW(5, 1, [{ opp: 'SUN', home: false }]),
        GW(6, 2, [{ opp: 'LEE' }, { opp: 'WOL', home: false }], { dgw: true }),
        GW(7, 2, [{ opp: 'BHA' }]),
        GW(8, 3, [{ opp: 'CRY' }]),
      ],
      [run('good', 4, 7, 'mild')],
    ),
    team('LIV', 'Liverpool', 'attack',
      'Tramo ofensivo exigente: 3 jornadas duras (J1–J3).',
      [
        GW(1, 4, [{ opp: 'MCI' }]),
        GW(2, 5, [{ opp: 'ARS', home: false }]),
        GW(3, 4, [{ opp: 'CHE' }]),
        GW(4, 3, [{ opp: 'NEW', home: false }]),
        GW(5, 3, [{ opp: 'TOT' }]),
        GW(6, 2, [{ opp: 'BUR', home: false }]),
        GW(7, 1, [{ opp: 'SUN' }]),
        GW(8, 2, [{ opp: 'LEE', home: false }]),
      ],
      [run('bad', 1, 3, 'mild'), run('good', 6, 8, 'mild')],
    ),
  ],
};

const DEFENCE: FixtureOutlookMeta = {
  axis: 'defence',
  horizon: 8,
  current_gameweek: 1,
  teams: [
    team('ARS', 'Arsenal', 'defence',
      'Buen tramo para portería a cero: calendario muy favorable (J1–J5).',
      [
        GW(1, 1, [{ opp: 'SUN' }]),
        GW(2, 2, [{ opp: 'BRE', home: false }]),
        GW(3, 2, [{ opp: 'LEE' }]),
        GW(4, 1, [{ opp: 'WOL', home: false }]),
        GW(5, 2, [{ opp: 'BUR' }]),
        GW(6, 5, [{ opp: 'LIV', home: false }]),
        GW(7, 4, [{ opp: 'CHE' }]),
        GW(8, 4, [{ opp: 'MCI', home: false }]),
      ],
      [run('good', 1, 5, 'strong'), run('bad', 6, 8, 'mild')],
    ),
    team('CAI', 'Chelsea (Caicedo — mediocampista defensivo)', 'defence',
      'Calendario defensivo favorable (J2–J4).',
      [
        GW(1, 4, [{ opp: 'CRY', home: false }]),
        GW(2, 2, [{ opp: 'FUL' }]),
        GW(3, 1, [{ opp: 'LEE', home: false }]),
        GW(4, 2, [{ opp: 'BUR' }]),
        GW(5, 3, [{ opp: 'BHA', home: false }]),
        GW(6, 4, [{ opp: 'ARS' }]),
        GW(7, 3, [{ opp: 'TOT', home: false }]),
        GW(8, 3, [{ opp: 'EVE' }]),
      ],
      [run('good', 2, 4, 'mild')],
    ),
  ],
};

// --- page -------------------------------------------------------------------

export default function FixturesPreviewPage() {
  return (
    <div className="min-h-[100dvh] bg-bf-ink text-white px-4 py-8">
      <div className="max-w-[720px] mx-auto space-y-6">
        <header className="space-y-1">
          <h1 className="text-2xl font-extrabold">Fixture ticker — preview</h1>
          <p className="text-sm text-bf-gray">
            Datos de ejemplo (pretemporada: la API de FPL aún no publica la nueva
            campaña). Muestra el card <code>FixtureOutlookCard</code> en ambos ejes.
          </p>
        </header>

        <section className="space-y-2">
          <h2 className="text-xs font-bold uppercase tracking-wider text-bf-gray/70">
            Eje ataque (para atacantes / capitanía)
          </h2>
          <FixtureOutlookCard data={ATTACK} />
        </section>

        <section className="space-y-2">
          <h2 className="text-xs font-bold uppercase tracking-wider text-bf-gray/70">
            Eje defensa (porterías a cero / mediocampistas defensivos)
          </h2>
          <FixtureOutlookCard data={DEFENCE} />
        </section>
      </div>
    </div>
  );
}
