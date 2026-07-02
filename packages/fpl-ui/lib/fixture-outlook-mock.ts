/**
 * fixture-outlook-mock — deterministic mock league outlook for the /fixtures
 * page (FI7) while the FPL API is off-season (no upcoming fixtures / no team
 * strengths until the new season loads).
 *
 * This is the DATA SEAM: the page reads buildLeagueOutlook() today; swap it for
 * a live fetch (get_fixture_outlook per axis) once the API rolls over. Output
 * shape is identical to the backend FixtureOutlookMeta so nothing downstream
 * changes.
 *
 * Bands and runs mirror the backend semantics: 1=easiest … 5=hardest;
 * good ≤2 / bad ≥4 / neutral 3; a run is ≥3 consecutive same-class GWs,
 * graded strong (≥5) or mild (3–4).
 */
import type {
  FixtureOutlookMeta,
  FixtureOutlookGW,
  FixtureOutlookRun,
  OutlookClass,
  TeamOutlook,
  FixtureAxis,
} from './types';

const TEAMS: Array<{ short: string; name: string }> = [
  { short: 'ARS', name: 'Arsenal' },
  { short: 'AVL', name: 'Aston Villa' },
  { short: 'BOU', name: 'Bournemouth' },
  { short: 'BRE', name: 'Brentford' },
  { short: 'BHA', name: 'Brighton' },
  { short: 'BUR', name: 'Burnley' },
  { short: 'CHE', name: 'Chelsea' },
  { short: 'CRY', name: 'Crystal Palace' },
  { short: 'EVE', name: 'Everton' },
  { short: 'FUL', name: 'Fulham' },
  { short: 'LEE', name: 'Leeds' },
  { short: 'LIV', name: 'Liverpool' },
  { short: 'MCI', name: 'Man City' },
  { short: 'MUN', name: 'Man Utd' },
  { short: 'NEW', name: 'Newcastle' },
  { short: 'NFO', name: "Nott'm Forest" },
  { short: 'SUN', name: 'Sunderland' },
  { short: 'TOT', name: 'Tottenham' },
  { short: 'WHU', name: 'West Ham' },
  { short: 'WOL', name: 'Wolves' },
];

// --- deterministic RNG ------------------------------------------------------

function seedFrom(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function mulberry32(a: number): () => number {
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// --- run detection (port of the backend engine) -----------------------------

function classOf(band: number | null): OutlookClass {
  if (band === null) return 'blank';
  if (band <= 2) return 'good';
  if (band >= 4) return 'bad';
  return 'neutral';
}

function detectRuns(series: FixtureOutlookGW[]): FixtureOutlookRun[] {
  const runs: FixtureOutlookRun[] = [];
  let startIdx: number | null = null;
  let runClass: OutlookClass | null = null;

  const flush = (endIdx: number) => {
    if (startIdx === null || runClass === null) return;
    const length = endIdx - startIdx + 1;
    if (length >= 3) {
      runs.push({
        type: runClass as 'good' | 'bad',
        start_gw: series[startIdx].gameweek,
        end_gw: series[endIdx].gameweek,
        length,
        intensity: length >= 5 ? 'strong' : 'mild',
      });
    }
  };

  series.forEach((gw, i) => {
    const k = gw.klass;
    if (k === 'good' || k === 'bad') {
      if (k === runClass) return;
      flush(i - 1);
      startIdx = i;
      runClass = k;
    } else {
      flush(i - 1);
      startIdx = null;
      runClass = null;
    }
  });
  flush(series.length - 1);
  return runs;
}

// --- verdict (Spanish, schedule-only) ---------------------------------------

function verdictFor(axis: FixtureAxis, runs: FixtureOutlookRun[]): string {
  if (runs.length === 0) return 'Calendario sin rachas marcadas en el horizonte.';
  const primary = [...runs].sort((a, b) => a.start_gw - b.start_gw)[0];
  const span = `J${primary.start_gw}–J${primary.end_gw}`;
  const strong = primary.intensity === 'strong';
  const good = primary.type === 'good';
  if (axis === 'attack') {
    return good
      ? `Buen tramo ofensivo: ${primary.length} jornadas de calendario ${strong ? 'muy asequible' : 'asequible'} (${span}).`
      : `Tramo ofensivo ${strong ? 'muy exigente' : 'exigente'}: ${primary.length} jornadas duras (${span}).`;
  }
  return good
    ? `Buen tramo para portería a cero: calendario ${strong ? 'muy favorable' : 'favorable'} (${span}).`
    : `Tramo ${strong ? 'muy complicado' : 'complicado'} para mantener la portería a cero (${span}).`;
}

// --- public builder ---------------------------------------------------------

const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n));

export function buildLeagueOutlook(axis: FixtureAxis, horizon: number): FixtureOutlookMeta {
  const teams: TeamOutlook[] = TEAMS.map(({ short, name }) => {
    const rng = mulberry32(seedFrom(`${short}:${axis}`));
    // Each team has a difficulty "centre"; bands drift around it (AR(1)-style)
    // so similar bands cluster into runs, like a real fixture run.
    const centre = 1.6 + rng() * 3.0; // 1.6 … 4.6
    let cur = centre;
    const teamIdx = TEAMS.findIndex((t) => t.short === short);
    const pickOpponent = () => {
      let o = TEAMS[Math.floor(rng() * TEAMS.length)].short;
      if (o === short) o = TEAMS[(teamIdx + 3) % TEAMS.length].short;
      return o;
    };
    const series: FixtureOutlookGW[] = [];
    for (let gw = 1; gw <= horizon; gw++) {
      cur = cur * 0.65 + (centre + (rng() - 0.5) * 2.6) * 0.35;
      const band = clamp(Math.round(cur), 1, 5);
      const home = rng() > 0.5;
      const fixtures = [{ opponent_short: pickOpponent(), is_home: home, band }];

      // Occasional double gameweek (~12%): a second fixture, band possibly
      // different. Combined difficulty takes the easier of the two — two
      // chances at goals/clean sheets is a schedule upside, not a wash.
      const isDgw = rng() < 0.12;
      let combinedBand = band;
      if (isDgw) {
        const band2 = clamp(band + Math.round((rng() - 0.5) * 2), 1, 5);
        fixtures.push({ opponent_short: pickOpponent(), is_home: rng() > 0.5, band: band2 });
        combinedBand = Math.min(band, band2);
      }

      series.push({
        gameweek: gw,
        band: combinedBand,
        klass: classOf(combinedBand),
        is_dgw: isDgw,
        is_bgw: false,
        fixtures,
      });
    }
    const runs = detectRuns(series);
    const bands = series.map((s) => s.band).filter((b): b is number => b !== null);
    const avg = bands.length ? Math.round((bands.reduce((a, b) => a + b, 0) / bands.length) * 100) / 100 : null;
    return { team_short: short, team_name: name, axis, avg_band: avg, verdict: verdictFor(axis, runs), series, runs };
  });

  // Easiest schedule first (lowest avg band), mirroring get_all_team_outlooks.
  teams.sort((a, b) => (a.avg_band ?? 99) - (b.avg_band ?? 99));

  return { axis, horizon, current_gameweek: 1, teams };
}
