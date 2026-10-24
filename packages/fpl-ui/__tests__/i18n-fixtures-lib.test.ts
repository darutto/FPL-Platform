/**
 * S4b, the pure half: every wording helper of the fixtures family, in both languages.
 *
 * Spanish is pinned to the exact text the app printed before the dictionary (the old literals are
 * copied here), so moving a string in cannot have changed it. English is pinned to the glossary
 * (docs/i18n-glossary.md): British spelling, GW for gameweek, Home/Away, Clean sheet.
 */
import { translate, type DictKey } from '@/lib/i18n/dictionary';
import {
  axisLabel,
  bandLabel,
  cellAriaLabel,
  cellTitle,
  fixtureVerdict,
  gwLabel,
  gwRange,
  venueLabel,
} from '@/lib/fixture-outlook-format';
import { fixtureCellQuestion, teamOutlookQuestion } from '@/lib/fixture-chat-links';
import { fixtureOutlookProvenance } from '@/lib/fixture-outlook-provenance';
import {
  buildTimeline,
  competitionLegend,
  competitionName,
  extraSentence,
  gutterSentence,
  compactGutter,
  lockedLine,
  lockedLink,
  parseCompetitions,
  venueWord,
} from '@/lib/fixture-competitions';
import { formatVenue } from '@/components/intents/FixtureRunTable';
import type { FixtureOutlookGW, FixtureOutlookGeneration, FixtureOutlookMeta } from '@/lib/types';
import real from '@/lib/data/fixture-outlook-2026-27.json';

const cell = (opponent_short: string, is_home: boolean, band = 3) => ({ opponent_short, is_home, band });
const gw = (over: Partial<FixtureOutlookGW>): FixtureOutlookGW => ({
  gameweek: 7, band: 3, klass: 'neutral', is_dgw: false, is_bgw: false, fixtures: [cell('EVE', true)], ...over,
});
const BLANK = gw({ gameweek: 8, band: null, is_bgw: true, fixtures: [] });
const DOUBLE = gw({ is_dgw: true, fixtures: [cell('EVE', true), cell('NFO', false)] });

describe('labels', () => {
  test('Spanish is what the app said before', () => {
    expect([1, 2, 3, 4, 5].map((b) => bandLabel(b as 1))).toEqual(['Fácil', 'Favorable', 'Medio', 'Difícil', 'Muy difícil']);
    expect([venueLabel(true), venueLabel(false)]).toEqual(['L', 'V']);
    expect([axisLabel('attack'), axisLabel('defence')]).toEqual(['Ataque', 'Portería a cero']);
    expect([gwLabel(12), gwRange(12, 14)]).toEqual(['J12', 'J12–J14']);
    expect([formatVenue(true), formatVenue(false)]).toEqual(['L', 'V']);
  });

  test('English follows the glossary', () => {
    expect([1, 2, 3, 4, 5].map((b) => bandLabel(b as 1, 'en'))).toEqual(['Easy', 'Favourable', 'Moderate', 'Hard', 'Very hard']);
    expect([venueLabel(true, 'en'), venueLabel(false, 'en')]).toEqual(['H', 'A']);
    expect([axisLabel('attack', 'en'), axisLabel('defence', 'en')]).toEqual(['Attack', 'Clean sheet']);
    expect([gwLabel(12, 'en'), gwRange(12, 14, 'en')]).toEqual(['GW12', 'GW12–GW14']);
    expect([formatVenue(true, 'en'), formatVenue(false, 'en')]).toEqual(['H', 'A']);
  });

  test('cell tooltips', () => {
    expect(cellTitle(DOUBLE)).toBe('J7 · EVE/NFO L/V · FDR 3 · doble jornada');
    expect(cellTitle(DOUBLE, 'en')).toBe('GW7 · EVE/NFO H/A · FDR 3 · double gameweek');
    expect(cellTitle(gw({}))).toBe('J7 · EVE L · FDR 3');
    expect(cellTitle(BLANK)).toBe('Sin partido (jornada en blanco)');
    expect(cellTitle(BLANK, 'en')).toBe('No fixture (blank gameweek)');
    expect(cellAriaLabel(BLANK)).toBe('J8 · sin partido (jornada en blanco)');
    expect(cellAriaLabel(BLANK, 'en')).toBe('GW8 · no fixture (blank gameweek)');
    expect(cellAriaLabel(DOUBLE, 'en')).toBe(cellTitle(DOUBLE, 'en'));
  });
});

describe('the questions a tapped team or cell hands to the chat', () => {
  test('Spanish is byte-identical to the old literals', () => {
    expect(teamOutlookQuestion('Arsenal', 'attack')).toBe('¿Cómo pinta el calendario ofensivo del Arsenal en las próximas jornadas?');
    expect(teamOutlookQuestion('Arsenal', 'defence')).toBe('¿Qué tan bueno es el calendario del Arsenal para portería a cero próximamente?');
    expect(fixtureCellQuestion('Arsenal', gw({}))).toBe(
      'Arsenal vs EVE (en casa), J7: ¿qué tal pinta ofensivamente y defensivamente para el Arsenal?',
    );
    expect(fixtureCellQuestion('Arsenal', DOUBLE)).toBe(
      'Arsenal vs EVE (en casa) y Arsenal vs NFO (a domicilio), J7 (doble jornada): ¿qué tal pinta ofensivamente y defensivamente para el Arsenal?',
    );
    expect(fixtureCellQuestion('Arsenal', BLANK)).toBe('¿Qué tiene el Arsenal en la J8?');
  });

  test('English reads as a question an English user would type', () => {
    expect(teamOutlookQuestion('Arsenal', 'attack', 'en')).toBe("How does Arsenal's attacking fixture run look over the next gameweeks?");
    expect(teamOutlookQuestion('Arsenal', 'defence', 'en')).toBe("How good is Arsenal's fixture run for clean sheets coming up?");
    expect(fixtureCellQuestion('Arsenal', gw({}), 'en')).toBe(
      'Arsenal vs EVE (at home), GW7: how do they look attacking and defensively for Arsenal?',
    );
    expect(fixtureCellQuestion('Arsenal', DOUBLE, 'en')).toBe(
      'Arsenal vs EVE (at home) and Arsenal vs NFO (away), GW7 (double gameweek): how do they look attacking and defensively for Arsenal?',
    );
    expect(fixtureCellQuestion('Arsenal', BLANK, 'en')).toBe('What does Arsenal have in GW8?');
  });
});

describe('the data stamp', () => {
  const generation = (over: Partial<FixtureOutlookGeneration>): FixtureOutlookGeneration => ({
    generated_at: '2026-09-10T02:14:02Z', season: '2026-2027', season_label: '2026-27', source: 'recipe',
    gameweeks_played: 3, axes_separated: true, axis_separation_by_horizon: { '38': 16 }, teams: 20,
    source_horizon: 38, covers_gameweeks: [1, 38], gameweek_columns: 38, ...over,
  });

  test('Spanish is byte-identical to the old text, status by status', () => {
    expect(fixtureOutlookProvenance(null, null)).toEqual({
      status: 'unknown',
      label: 'Calendario real de la Premier League desde la API oficial de FPL.',
      warning: '⚠ Estos datos no declaran cuándo ni cómo se generaron, así que no podemos decirte a qué jornada llegan.',
    });
    expect(fixtureOutlookProvenance(generation({}), null)).toEqual({
      status: 'thin',
      label: 'Temporada 2026-27 · dificultad calculada con los resultados hasta la jornada 3 · actualizado el 10 sep 2026.',
      warning:
        '⚠ Muestra corta: 3 de 38 jornadas. Los dos ejes ya se separan, pero a estas alturas la dificultad de portería a cero todavía refleja sobre todo la valoración de pretemporada de FPL, no la forma real. Se afina con cada jornada que se juega.',
    });
    expect(fixtureOutlookProvenance(generation({ gameweeks_played: 0, axes_separated: false }), null).warning).toBe(
      '⚠ Arranque de temporada: aún no hay resultados, así que Ataque y Portería a cero muestran la misma dificultad (el FDR de FPL). Los dos ejes se separan en cuanto se juegan jornadas.',
    );
    expect(fixtureOutlookProvenance(generation({ axes_separated: false }), null).warning).toBe(
      '⚠ Ambos ejes muestran los mismos datos pese a haber 3 jornadas jugadas: este calendario está sin regenerar. Cambiar entre Ataque y Portería a cero no cambiará nada.',
    );
    expect(fixtureOutlookProvenance(generation({}), 5).warning).toBe(
      '⚠ La liga va por la jornada 5 y este calendario se calculó con 3. Los últimos resultados aún no pesan en la dificultad de portería a cero.',
    );
    const none = fixtureOutlookProvenance(generation({ gameweeks_played: 0, generated_at: '' }), null);
    expect(none.label).toBe('Temporada 2026-27 · sin jornadas jugadas todavía.');
    expect(fixtureOutlookProvenance(generation({ gameweeks_played: 8 }), null)).toMatchObject({ status: 'current', warning: null });
  });

  test('English says the same things', () => {
    expect(fixtureOutlookProvenance(null, null, 'en')).toEqual({
      status: 'unknown',
      label: 'Real Premier League fixtures from the official FPL API.',
      warning: '⚠ This data does not say when or how it was generated, so we cannot tell you which gameweek it reaches.',
    });
    const thin = fixtureOutlookProvenance(generation({}), null, 'en');
    expect(thin.label).toBe('Season 2026-27 · difficulty calculated from results up to gameweek 3 · updated 10 Sep 2026.');
    expect(thin.warning).toContain('Small sample: 3 of 38 gameweeks.');
    expect(fixtureOutlookProvenance(generation({ gameweeks_played: 0, axes_separated: false }), null, 'en').warning).toContain(
      'Start of the season',
    );
    expect(fixtureOutlookProvenance(generation({ axes_separated: false }), null, 'en').warning).toContain(
      'Switching between Attack and Clean sheet will change nothing.',
    );
    expect(fixtureOutlookProvenance(generation({}), 5, 'en').warning).toBe(
      '⚠ The league is at gameweek 5 and this calendar was calculated with 3. The latest results do not yet count towards clean-sheet difficulty.',
    );
    expect(fixtureOutlookProvenance(generation({ gameweeks_played: 0, generated_at: '' }), null, 'en').label).toBe(
      'Season 2026-27 · no gameweeks played yet.',
    );
  });
});

describe('other competitions', () => {
  const view = parseCompetitions({
    available: true,
    tier: 'premium',
    teams: {
      ARS: {
        matches: [
          { kickoff_utc: '2026-10-21T19:00:00Z', gameweek: 8, competition: 'UCL', venue: 'A', opponent: 'FC Bayern München',
            opponent_code: 'BAY', rest_whole_days_before: 3 },
          { kickoff_utc: '2026-12-02T19:00:00Z', gameweek: 8, competition: 'UEFA-SC', venue: 'H', opponent: 'Real Madrid',
            opponent_code: 'RMA', rest_whole_days_before: 1 },
        ],
        pl_matches: [
          { kickoff_utc: '2026-10-18T15:30:00Z', gameweek: 7, venue: 'A', opponent: 'Nottingham Forest', rest_whole_days_before: 4 },
          { kickoff_utc: '2026-10-24T14:00:00Z', gameweek: 8, venue: 'H', opponent: 'Everton', rest_whole_days_before: 2,
            rotation: true, previous_competition: 'UCL' },
        ],
      },
    },
  })!.teams.get('ARS')!;
  const series = [gw({ gameweek: 7 }), gw({ gameweek: 8 })];

  test('names, venues and legend', () => {
    expect([competitionName('UEFA-SC'), competitionName('UEFA-SC', 'en')]).toEqual(['Supercopa de Europa', 'UEFA Super Cup']);
    expect([competitionName('UCL'), competitionName('UCL', 'en')]).toEqual(['Champions League', 'Champions League']);
    expect([venueWord('H'), venueWord('A')]).toEqual(['local', 'visitante']);
    expect([venueWord('H', 'en'), venueWord('A', 'en')]).toEqual(['home', 'away']);
    expect(competitionLegend().map((e) => e.label)).toEqual(['Champions', 'Europa League', 'Conference', 'Copas']);
    expect(competitionLegend('en').map((e) => e.label)).toEqual(['Champions', 'Europa League', 'Conference', 'Cups']);
    expect(competitionLegend('en')[1].short).toBe('Europa');
    expect(lockedLine()).toBe('Ve los partidos de Champions, Europa y copas, con los días de descanso.');
    expect(lockedLink()).toBe('Ver con Premium');
    expect(lockedLine('en')).toBe('See the Champions League, Europa League and cup fixtures, with the days of rest.');
    expect(lockedLink('en')).toBe('See with Premium');
  });

  test('sentences, in Spanish as before and in English', () => {
    const items = buildTimeline(series, view);
    const itemsEn = buildTimeline(series, view, 'en');
    const sentences = (list: typeof items) => list.flatMap((i) => [i.kind === 'extra' ? i.sentence : '', i.gap?.sentence ?? '', i.gap?.cell ?? '']);
    expect(sentences(items).filter(Boolean)).toEqual([
      'Champions League ante FC Bayern München (visitante)',
      '3 días de descanso',
      'Su equipo jugó UCL hace 2 días. Todavía no hay evidencia suficiente para cuantificar el riesgo de rotación.',
      '2 días tras UCL',
      'Supercopa de Europa ante Real Madrid (local)',
      '1 día de descanso',
    ]);
    expect(sentences(itemsEn).filter(Boolean)).toEqual([
      'Champions League vs FC Bayern München (away)',
      '3 days of rest',
      'The team played UCL 2 days ago. There is not yet enough evidence to size the rotation risk.',
      '2 days after UCL',
      'UEFA Super Cup vs Real Madrid (home)',
      '1 day of rest',
    ]);
    expect(extraSentence(view.extras[0])).toBe('Champions League ante FC Bayern München (visitante)');
    expect(extraSentence(view.extras[0], 'en')).toBe('Champions League vs FC Bayern München (away)');
    expect(gutterSentence('ARS', compactGutter(view, 8))).toMatch(/^ARS · Champions League ante FC Bayern München \(visitante\) · /);
    expect(gutterSentence('ARS', compactGutter(view, 8), 'en')).toMatch(/^ARS · Champions League vs FC Bayern München \(away\) · /);
  });
});

describe('team verdicts', () => {
  const verdictKeys = [
    'fx.verdict.attackGood', 'fx.verdict.attackGoodStrong', 'fx.verdict.attackBad', 'fx.verdict.attackBadStrong',
    'fx.verdict.defenceGood', 'fx.verdict.defenceGoodStrong', 'fx.verdict.defenceBad', 'fx.verdict.defenceBadStrong',
  ] as DictKey[];

  test.each(verdictKeys)('%s: the Spanish template is recognised and said in English', (key) => {
    const spanish = translate('es', key, { n: 3, span: 'J17–J19' });
    expect(fixtureVerdict(spanish)).toBe(spanish);
    expect(fixtureVerdict(spanish, 'en')).toBe(translate('en', key, { n: 3, span: 'GW17–GW19' }));
  });

  test('the two spanless verdicts', () => {
    expect(fixtureVerdict('Calendario sin rachas claras en el horizonte.', 'en')).toBe('No clear runs in the fixtures ahead.');
    expect(fixtureVerdict('Sin fixtures en el horizonte.', 'en')).toBe('No fixtures in the window.');
  });

  test('anything it does not recognise passes through untouched', () => {
    expect(fixtureVerdict('Una frase nueva del backend.', 'en')).toBe('Una frase nueva del backend.');
    expect(fixtureVerdict('Good attacking stretch: 3 gameweeks of favourable fixtures (GW1–GW3).', 'en')).toBe(
      'Good attacking stretch: 3 gameweeks of favourable fixtures (GW1–GW3).',
    );
  });

  test('every verdict in the shipped 2026-27 bundle comes out in English, and none is left in Spanish', () => {
    const bundle = real as unknown as Record<'attack' | 'defence', Record<string, FixtureOutlookMeta>>;
    const verdicts = new Set<string>();
    for (const axis of ['attack', 'defence'] as const) {
      for (const meta of Object.values(bundle[axis])) for (const team of meta.teams) verdicts.add(team.verdict);
    }
    expect(verdicts.size).toBeGreaterThan(5);
    for (const v of verdicts) {
      const english = fixtureVerdict(v, 'en');
      expect(english).not.toBe(v);
      expect(english).not.toMatch(/jornada|tramo|calendario|portería|asequible|exigente|J\d/i);
      expect(english).toMatch(/GW\d+|No clear runs|No fixtures/);
    }
  });
});
