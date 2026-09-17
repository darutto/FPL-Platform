/**
 * fixture-chat-links — the deep-link questions that turn a browsed fixture cell
 * or team row into a chat prompt (Track D / FI7).
 *
 * The /fixtures surface never gives advice itself (schedule reads only); it
 * hands the user a ready-made question so the owning engines answer in chat.
 * The team-row tap stays axis-aware (an attack-view tap asks about goals, a
 * defence-view tap about clean sheets: a multi-GW calendar read is one axis
 * at a time). The single-cell tap asks about BOTH sides of that one match
 * whatever view it came from (i93-b, 2026-09-15): one match is one profile,
 * and the chat answer composes the calendar read on both axes with that
 * team's real players (i93).
 */
import type { FixtureAxis, FixtureOutlookGW } from './types';

/** Whole-team outlook question (team code / row tap). */
export function teamOutlookQuestion(teamName: string, axis: FixtureAxis): string {
  return axis === 'attack'
    ? `¿Cómo pinta el calendario ofensivo del ${teamName} en las próximas jornadas?`
    : `¿Qué tan bueno es el calendario del ${teamName} para portería a cero próximamente?`;
}

/**
 * Single-fixture question (one GW cell tap). Mentions both matches on a DGW.
 * Axis-independent: the phrase asks for the attacking AND the defensive read
 * of that match, so the answer is the whole profile of the fixture.
 */
export function fixtureCellQuestion(teamName: string, gw: FixtureOutlookGW): string {
  if (gw.fixtures.length === 0) {
    return `¿Qué tiene el ${teamName} en la J${gw.gameweek}?`;
  }
  const matchup = gw.fixtures
    .map((f) => `${teamName} vs ${f.opponent_short} (${f.is_home ? 'en casa' : 'a domicilio'})`)
    .join(' y ');
  const jornada = gw.is_dgw ? `J${gw.gameweek} (doble jornada)` : `J${gw.gameweek}`;
  return `${matchup}, ${jornada}: ¿qué tal pinta ofensivamente y defensivamente para el ${teamName}?`;
}
