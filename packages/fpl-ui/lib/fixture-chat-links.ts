/**
 * fixture-chat-links — the deep-link questions that turn a browsed fixture cell
 * or team row into a chat prompt (Track D / FI7).
 *
 * The /fixtures surface never gives advice itself (schedule reads only); it
 * hands the user a ready-made question so the owning engines answer in chat.
 * Kept axis-aware so an attack-view tap asks about goals and a defence-view tap
 * asks about clean sheets.
 */
import type { FixtureAxis, FixtureOutlookGW } from './types';

/** Whole-team outlook question (team code / row tap). */
export function teamOutlookQuestion(teamName: string, axis: FixtureAxis): string {
  return axis === 'attack'
    ? `¿Cómo pinta el calendario ofensivo del ${teamName} en las próximas jornadas?`
    : `¿Qué tan bueno es el calendario del ${teamName} para portería a cero próximamente?`;
}

/** Single-fixture question (one GW cell tap). Mentions both matches on a DGW. */
export function fixtureCellQuestion(
  teamName: string,
  gw: FixtureOutlookGW,
  axis: FixtureAxis,
): string {
  if (gw.fixtures.length === 0) {
    return `¿Qué tiene el ${teamName} en la J${gw.gameweek}?`;
  }
  const matchup = gw.fixtures
    .map((f) => `${teamName} vs ${f.opponent_short} (${f.is_home ? 'en casa' : 'a domicilio'})`)
    .join(' y ');
  const jornada = gw.is_dgw ? `J${gw.gameweek} (doble jornada)` : `J${gw.gameweek}`;
  return axis === 'attack'
    ? `${matchup}, ${jornada}: ¿qué tal pinta ofensivamente para el ${teamName}?`
    : `${matchup}, ${jornada}: ¿buen partido para que el ${teamName} deje la portería a cero?`;
}
