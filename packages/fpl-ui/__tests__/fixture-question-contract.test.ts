/**
 * The questions a tapped team or calendar cell hands to the chat, and what the backend is expected to do with them.
 *
 * A tap sends free text. The orchestrator (an LLM) reads it against the tool descriptions in
 * packages/fpl-grounded-assistant/fpl_grounded_assistant/tool_schema_registry.py, whose worked examples are Spanish.
 * Nothing here calls a model: this pins the SHAPE of each question in both languages, so a rewording cannot drop the
 * parts the routing leans on (the team, the opponent and venue, the gameweek, and asking BOTH sides of a match)
 * without somebody noticing. Whether the English phrasing really routes is measured by the paid English battery (S7).
 *
 * Expected routing, per tap (the contract each phrase is written for):
 *
 *   team row, attack view   -> get_fixture_outlook(team_query = the team, axis = "attack")
 *   team row, defence view  -> get_fixture_outlook(team_query = the team, axis = "defence")
 *   cell with a match       -> get_fixture_outlook twice (axis "attack" and "defence", same team_query and
 *                              target_gw) plus get_team_snapshot(team_name = the team): one composed turn
 *   cell, double gameweek   -> the same, with both matches named
 *   cell, blank gameweek    -> a question about that team's gameweek (get_fixture_outlook with target_gw, or
 *                              get_team_schedule); unmeasured
 *
 * The deterministic router is NOT in this path: with the orchestrator on, free text goes to it first
 * (harness.ask_v2), and route() only serves as a fallback.
 */
import { fixtureCellQuestion, teamOutlookQuestion } from '@/lib/fixture-chat-links';
import type { FixtureOutlookGW } from '@/lib/types';
import type { Locale } from '@/lib/i18n/locale';

const cell = (opponent_short: string, is_home: boolean) => ({ opponent_short, is_home, band: 3 });
const gw = (over: Partial<FixtureOutlookGW>): FixtureOutlookGW => ({
  gameweek: 7, band: 3, klass: 'neutral', is_dgw: false, is_bgw: false, fixtures: [cell('EVE', true)], ...over,
});
const SINGLE = gw({});
const DOUBLE = gw({ is_dgw: true, fixtures: [cell('EVE', true), cell('NFO', false)] });
const BLANK = gw({ band: null, is_bgw: true, fixtures: [], gameweek: 8 });

/** What each language writes for the same four ideas. */
const WORDS: Record<Locale, { attack: RegExp; clean: RegExp; bothSides: RegExp; home: string; away: string; gw: string; double: string }> = {
  es: { attack: /ofensivo/, clean: /portería a cero/, bothSides: /ofensivamente y defensivamente/, home: 'en casa', away: 'a domicilio', gw: 'J', double: 'doble jornada' },
  en: { attack: /attacking/, clean: /clean sheets/, bothSides: /attacking and defensively/, home: 'at home', away: 'away', gw: 'GW', double: 'double gameweek' },
};

describe.each(['es', 'en'] as Locale[])('tap questions (%s)', (locale) => {
  const w = WORDS[locale];

  test('a team row names the team and the axis, and nothing else', () => {
    const attack = teamOutlookQuestion('Arsenal', 'attack', locale);
    const defence = teamOutlookQuestion('Arsenal', 'defence', locale);
    expect(attack).toContain('Arsenal');
    expect(attack).toMatch(w.attack);
    expect(attack).not.toMatch(w.clean);
    expect(defence).toContain('Arsenal');
    expect(defence).toMatch(w.clean);
    expect(defence).not.toMatch(w.attack);
    for (const q of [attack, defence]) expect(q).not.toMatch(/\bGW\d|\bJ\d/);
  });

  test('a cell with a match names team, opponent, venue and gameweek, and asks both sides', () => {
    const q = fixtureCellQuestion('Arsenal', SINGLE, locale);
    expect(q).toContain(`Arsenal vs EVE (${w.home})`);
    expect(q).toContain(`, ${w.gw}7:`);
    expect(q).toMatch(w.bothSides);
    expect(q.endsWith('Arsenal?')).toBe(true);
    expect(q).not.toContain(w.double);
  });

  test('a double gameweek names both matches and says so', () => {
    const q = fixtureCellQuestion('Arsenal', DOUBLE, locale);
    expect(q).toContain(`Arsenal vs EVE (${w.home})`);
    expect(q).toContain(`Arsenal vs NFO (${w.away})`);
    expect(q).toContain(`${w.gw}7 (${w.double})`);
    expect(q).toMatch(w.bothSides);
  });

  test('a blank gameweek asks what the team has in it', () => {
    const q = fixtureCellQuestion('Arsenal', BLANK, locale);
    expect(q).toContain('Arsenal');
    expect(q).toContain(`${w.gw}8`);
    expect(q).not.toMatch(/ vs /);
  });
});
