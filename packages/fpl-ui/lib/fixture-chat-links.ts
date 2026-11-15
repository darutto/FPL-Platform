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
import { translate } from './i18n/dictionary';
import { DEFAULT_LOCALE, type Locale } from './i18n/locale';

/** Whole-team outlook question (team code / row tap). */
export function teamOutlookQuestion(teamName: string, axis: FixtureAxis, locale: Locale = DEFAULT_LOCALE): string {
  return translate(locale, axis === 'attack' ? 'fx.q.teamAttack' : 'fx.q.teamDefence', { team: teamName });
}

/**
 * Single-fixture question (one GW cell tap). Mentions both matches on a DGW.
 * Axis-independent: the phrase asks for the attacking AND the defensive read
 * of that match, so the answer is the whole profile of the fixture.
 */
export function fixtureCellQuestion(teamName: string, gw: FixtureOutlookGW, locale: Locale = DEFAULT_LOCALE): string {
  if (gw.fixtures.length === 0) {
    return translate(locale, 'fx.q.cellBlank', { team: teamName, gw: gw.gameweek });
  }
  const matchup = gw.fixtures
    .map(
      (f) =>
        `${teamName} vs ${f.opponent_short} (${translate(locale, f.is_home ? 'fx.q.venueHome' : 'fx.q.venueAway')})`,
    )
    .join(translate(locale, 'fx.q.matchupJoin'));
  const jornada = gw.is_dgw
    ? translate(locale, 'fx.q.gwDouble', { gw: gw.gameweek })
    : translate(locale, 'fx.gw', { n: gw.gameweek });
  return translate(locale, 'fx.q.cell', { matchup, gw: jornada, team: teamName });
}
