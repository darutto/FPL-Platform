/**
 * fixture-outlook-provenance — what the /fixtures board is allowed to claim
 * about its own data.
 *
 * The 2026-27 bundle shipped with `attack` and `defence` collapsed onto a
 * single signal, so the Ataque / Portería a cero switcher re-rendered
 * identical rows. It stayed that way six weeks. The footer did admit, in
 * prose, that the defence axis "se ajustará … en cuanto haya resultados" —
 * and nobody read it, which is exactly why a footer is not enough.
 *
 * Two rules carried over from the i74 zonal stamp, and they matter here for
 * the same reason:
 *   1. What the stamp SAYS comes from the bundle's own `generation` block,
 *      never from a constant in this file. A label derived from the same
 *      variable that chose the file is a tautology, not a check.
 *   2. What the stamp COMPARES AGAINST comes from live reality — the FPL
 *      bootstrap's finished-gameweek count, fetched by the board — so
 *      "this bundle is behind the season" is something we can actually find
 *      out rather than assume.
 */
import type { FixtureOutlookGeneration } from './types';

/**
 * Below this many played gameweeks the separation rests on a thin sample.
 *
 * Not a round number picked for feel. compute_rolling_strength blends a team's
 * own results against FPL's captured preseason rating with weight
 * w / (w + 3.0), where w is the decayed count of that team's matches AT ONE
 * VENUE — so roughly half the played gameweeks. Measured own-data share:
 *
 *   3 played -> 22%   5 -> 34%   10 -> 47%   19 -> 52%   38 -> 54%
 *
 * Under ~5 the defence axis is still mostly repeating FPL's preseason opinion,
 * which is why the stamp says so instead of calling the separation settled.
 */
export const THIN_GAMEWEEKS = 5;

export type FixtureOutlookProvenanceStatus =
  | 'current'
  | 'thin'
  | 'season_start'
  | 'axes_collapsed'
  | 'stale_gameweeks'
  | 'unknown';

export interface FixtureOutlookProvenance {
  status: FixtureOutlookProvenanceStatus;
  /** Always-present factual caption: which season, how much of it, when built. */
  label: string;
  /** Gold notice, or null when the data needs no caveat. */
  warning: string | null;
}

const MONTHS_ES = [
  'ene', 'feb', 'mar', 'abr', 'may', 'jun',
  'jul', 'ago', 'sep', 'oct', 'nov', 'dic',
];

/** '2026-09-08T22:14:03Z' -> '8 sep 2026'. Null/unparseable -> null. */
export function formatGeneratedAt(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return null;
  return `${at.getUTCDate()} ${MONTHS_ES[at.getUTCMonth()]} ${at.getUTCFullYear()}`;
}

/**
 * Build the board's stamp.
 *
 * @param generation  the bundle's own provenance block (null on a bundle
 *                    predating it — which is itself worth saying out loud).
 * @param liveFinishedGameweek  gameweeks finished according to the live FPL
 *                    bootstrap, or null when that lookup failed. The only
 *                    input here that does not come from the bundle.
 */
export function fixtureOutlookProvenance(
  generation: FixtureOutlookGeneration | null | undefined,
  liveFinishedGameweek: number | null,
): FixtureOutlookProvenance {
  if (!generation) {
    return {
      status: 'unknown',
      label: 'Calendario real de la Premier League desde la API oficial de FPL.',
      warning:
        '⚠ Estos datos no declaran cuándo ni cómo se generaron, así que no ' +
        'podemos decirte a qué jornada llegan.',
    };
  }

  const played = generation.gameweeks_played;
  const season = generation.season_label ?? generation.season;
  const builtOn = formatGeneratedAt(generation.generated_at);

  const parts = [`Temporada ${season}`];
  parts.push(
    played > 0
      ? `dificultad calculada con los resultados hasta la jornada ${played}`
      : 'sin jornadas jugadas todavía',
  );
  if (builtOn) parts.push(`actualizado el ${builtOn}`);
  const label = `${parts.join(' · ')}.`;

  // Order matters: the axes being identical is the thing the user can see on
  // screen, so it outranks every other caveat.
  if (!generation.axes_separated) {
    return played === 0
      ? {
          status: 'season_start',
          label,
          warning:
            '⚠ Arranque de temporada: aún no hay resultados, así que Ataque y ' +
            'Portería a cero muestran la misma dificultad (el FDR de FPL). Los ' +
            'dos ejes se separan en cuanto se juegan jornadas.',
        }
      : {
          status: 'axes_collapsed',
          label,
          warning:
            `⚠ Ambos ejes muestran los mismos datos pese a haber ${played} ` +
            'jornadas jugadas: este calendario está sin regenerar. Cambiar entre ' +
            'Ataque y Portería a cero no cambiará nada.',
        };
  }

  if (liveFinishedGameweek !== null && liveFinishedGameweek > played) {
    return {
      status: 'stale_gameweeks',
      label,
      warning:
        `⚠ La liga va por la jornada ${liveFinishedGameweek} y este calendario ` +
        `se calculó con ${played}. Los últimos resultados aún no pesan en la ` +
        'dificultad de portería a cero.',
    };
  }

  if (played < THIN_GAMEWEEKS) {
    return {
      status: 'thin',
      label,
      warning:
        `⚠ Muestra corta: ${played} de 38 jornadas. Los dos ejes ya se separan, ` +
        'pero a estas alturas la dificultad de portería a cero todavía refleja ' +
        'sobre todo la valoración de pretemporada de FPL, no la forma real. Se ' +
        'afina con cada jornada que se juega.',
    };
  }

  return { status: 'current', label, warning: null };
}
