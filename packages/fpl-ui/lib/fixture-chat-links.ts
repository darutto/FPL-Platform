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

/** Single-fixture question (one GW cell tap). */
export function fixtureCellQuestion(
  teamName: string,
  gw: FixtureOutlookGW,
  axis: FixtureAxis,
): string {
  const f = gw.fixtures[0];
  if (!f) {
    return `¿Qué tiene el ${teamName} en la J${gw.gameweek}?`;
  }
  const venue = f.is_home ? 'en casa' : 'a domicilio';
  const matchup = `${teamName} vs ${f.opponent_short} (J${gw.gameweek}, ${venue})`;
  return axis === 'attack'
    ? `${matchup}: ¿qué tal pinta ofensivamente para el ${teamName}?`
    : `${matchup}: ¿buen partido para que el ${teamName} deje la portería a cero?`;
}
