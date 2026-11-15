/**
 * @jest-environment jsdom
 *
 * The verdict above a TABLE card: 0-3 structured conclusions that talk about the table and
 * never reprint its rows; the model's prose (only when the model wrote it) follows under a
 * hairline; a deterministic dump of the rows is not shown; with neither, no verdict band.
 * Synthetic data only (invented names and values).
 */
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import MessageList, { isDeterministicTableText, looksLikeRenderedTable, type Message } from '../components/chat/MessageList';
import TableConclusions, { conclusionEvidence, conclusionLabel, metricLabel } from '../components/intents/TableConclusions';
import { LocaleProvider } from '../lib/i18n/LocaleProvider';
import { translate, type DictKey, type TVars } from '../lib/i18n/dictionary';
import type { AskResponse, TableConclusion } from '../lib/types';
import {
  comparisonOkResponse,
  differentialOkResponse,
  fixtureRunOkResponse,
  orchestratorRankCardResponse,
  rankingOkResponse,
} from './fixtures/sample-responses';

const tEs = (key: DictKey, vars?: TVars) => translate('es', key, vars);
const tEn = (key: DictKey, vars?: TVars) => translate('en', key, vars);

const GAP_ONE: TableConclusion = {
  key: 'gap',
  params: { leaders: ['Uno'], metric: 'expected_goals' },
  evidence: { next_rank: 2, next_value: 6.1, lead_values: [7.29] },
};
const GAP_TWO: TableConclusion = {
  key: 'gap',
  params: { leaders: ['Uno', 'Dos'], metric: 'total_points' },
  evidence: { next_rank: 3, next_value: 60, lead_values: [81, 78] },
};
const CONC_POS: TableConclusion = { key: 'concentration', params: { kind: 'position', value: 'FWD', count: 4, total: 5 }, evidence: null };
const CONC_TEAM: TableConclusion = { key: 'concentration', params: { kind: 'team', value: 'AAA', count: 3, total: 5 }, evidence: null };
const OPPORTUNITY: TableConclusion = { key: 'opportunity', params: { name: 'Tres', kind: 'ownership' }, evidence: { value: 4.2 } };
const READING: TableConclusion = { key: 'reading', params: { kind: 'total_metric' }, evidence: null };

const bad = (value: unknown) => value as TableConclusion;

describe('wording — Spanish', () => {
  test('gap: one leader, two leaders, evidence = closest leader minus the next row', () => {
    expect(conclusionLabel(GAP_ONE, tEs)).toBe('Uno se despega');
    expect(conclusionEvidence(GAP_ONE, tEs)).toBe('xG · 2.º a 1.19');
    expect(conclusionLabel(GAP_TWO, tEs)).toBe('Uno y Dos se despegan');
    expect(conclusionEvidence(GAP_TWO, tEs)).toBe('puntos · 3.º a 18');
  });

  test('concentration: position and team', () => {
    expect(conclusionLabel(CONC_POS, tEs)).toBe('4 de 5 son delanteros');
    expect(conclusionLabel({ ...CONC_POS, params: { ...CONC_POS.params, value: 'MID' } } as TableConclusion, tEs)).toBe('4 de 5 son centrocampistas');
    expect(conclusionLabel({ ...CONC_POS, params: { ...CONC_POS.params, value: 'DEF' } } as TableConclusion, tEs)).toBe('4 de 5 son defensas');
    expect(conclusionLabel({ ...CONC_POS, params: { ...CONC_POS.params, value: 'GKP' } } as TableConclusion, tEs)).toBe('4 de 5 son porteros');
    expect(conclusionLabel(CONC_TEAM, tEs)).toBe('3 de 5 son del AAA');
    expect(conclusionEvidence(CONC_POS, tEs)).toBeNull();
  });

  test('opportunity: one decimal with a dot; reading', () => {
    expect(conclusionLabel(OPPORTUNITY, tEs)).toBe('Tres, en pocos equipos');
    expect(conclusionEvidence(OPPORTUNITY, tEs)).toBe('4.2 % de propiedad');
    expect(conclusionEvidence({ ...OPPORTUNITY, evidence: { value: 7 } } as TableConclusion, tEs)).toBe('7.0 % de propiedad');
    expect(conclusionLabel(READING, tEs)).toBe('Es un total: pesa quien más juega');
    expect(conclusionEvidence(READING, tEs)).toBeNull();
  });
});

describe('wording — English', () => {
  test('every key', () => {
    expect(conclusionLabel(GAP_ONE, tEn)).toBe('Uno pulls clear');
    expect(conclusionEvidence(GAP_ONE, tEn)).toBe('xG · #2 is 1.19 back');
    expect(conclusionLabel(GAP_TWO, tEn)).toBe('Uno and Dos pull clear');
    expect(conclusionEvidence(GAP_TWO, tEn)).toBe('points · #3 is 18 back');
    expect(conclusionLabel(CONC_POS, tEn)).toBe('4 of 5 are forwards');
    expect(conclusionLabel(CONC_TEAM, tEn)).toBe('3 of 5 play for AAA');
    expect(conclusionLabel(OPPORTUNITY, tEn)).toBe('Tres, in few teams');
    expect(conclusionEvidence(OPPORTUNITY, tEn)).toBe('4.2% owned');
    expect(conclusionLabel(READING, tEn)).toBe("It's a total: favours whoever plays most");
  });
});

describe('metric word', () => {
  test('known ids, per-90 variants, unknown id', () => {
    expect(metricLabel('expected_goal_involvements', tEs)).toBe('xGI');
    expect(metricLabel('expected_goals_per_90', tEs)).toBe('xG/90');
    expect(metricLabel('clean_sheets_per_90', tEs)).toBe('porterías a cero/90');
    expect(metricLabel('form', tEn)).toBe('form');
    expect(metricLabel('made_up_metric', tEs)).toBeNull();
    expect(metricLabel(undefined, tEs)).toBeNull();
  });

  test('unknown metric id drops the metric word, not the line or its evidence', () => {
    const c = { ...GAP_ONE, params: { leaders: ['Uno'], metric: 'made_up_metric' } } as TableConclusion;
    expect(conclusionLabel(c, tEs)).toBe('Uno se despega');
    expect(conclusionEvidence(c, tEs)).toBe('2.º a 1.19');
    expect(conclusionEvidence(c, tEn)).toBe('#2 is 1.19 back');
  });
});

describe('unknown key or malformed params → dropped, never shown raw', () => {
  test.each([
    ['unknown key', { key: 'nope', params: {}, evidence: null }],
    ['no params', { key: 'gap', evidence: null }],
    ['gap without leaders', { key: 'gap', params: { leaders: [], metric: 'form' }, evidence: null }],
    ['gap with three leaders', { key: 'gap', params: { leaders: ['A', 'B', 'C'], metric: 'form' }, evidence: null }],
    ['gap with a non-string leader', { key: 'gap', params: { leaders: [7], metric: 'form' }, evidence: null }],
    ['concentration with an unknown position', { key: 'concentration', params: { kind: 'position', value: 'XYZ', count: 3, total: 5 }, evidence: null }],
    ['concentration with an unknown kind', { key: 'concentration', params: { kind: 'league', value: 'AAA', count: 3, total: 5 }, evidence: null }],
    ['concentration with text counts', { key: 'concentration', params: { kind: 'team', value: 'AAA', count: '3', total: 5 }, evidence: null }],
    ['concentration with count above total', { key: 'concentration', params: { kind: 'team', value: 'AAA', count: 6, total: 5 }, evidence: null }],
    ['opportunity of an unknown kind', { key: 'opportunity', params: { name: 'Tres', kind: 'price' }, evidence: { value: 4.2 } }],
    ['opportunity without a name', { key: 'opportunity', params: { kind: 'ownership' }, evidence: { value: 4.2 } }],
    ['reading of an unknown kind', { key: 'reading', params: { kind: 'other' }, evidence: null }],
    ['null', null],
  ])('%s', (_name, value) => {
    expect(conclusionLabel(bad(value), tEs)).toBeNull();
  });

  test('malformed evidence drops the evidence, keeps the label', () => {
    const noGap = bad({ ...GAP_ONE, evidence: { next_rank: 2, next_value: 9, lead_values: [7.29] } });
    expect(conclusionLabel(noGap, tEs)).toBe('Uno se despega');
    expect(conclusionEvidence(noGap, tEs)).toBeNull();
    expect(conclusionEvidence(bad({ ...GAP_ONE, evidence: { next_rank: 2, next_value: 'x', lead_values: [7.29] } }), tEs)).toBeNull();
    expect(conclusionEvidence(bad({ ...GAP_ONE, evidence: { next_rank: 2, next_value: 1, lead_values: [] } }), tEs)).toBeNull();
    expect(conclusionEvidence(bad({ ...GAP_ONE, evidence: null }), tEs)).toBeNull();
    expect(conclusionEvidence(bad({ ...OPPORTUNITY, evidence: { value: 'low' } }), tEs)).toBeNull();
  });

  test('component: only wordable lines render, at most three; none → nothing', () => {
    const { container, unmount } = render(
      <TableConclusions conclusions={[bad({ key: 'nope', params: {}, evidence: null }), GAP_ONE, CONC_POS, OPPORTUNITY, READING]} />,
    );
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent('Uno se despega');
    expect(items[0]).toHaveTextContent('xG · 2.º a 1.19');
    expect(items[2]).toHaveTextContent('Tres, en pocos equipos');
    expect(container).not.toHaveTextContent('nope');
    unmount();

    const { container: c2 } = render(<TableConclusions conclusions={[bad({ key: 'nope', params: {}, evidence: null })]} />);
    expect(c2).toBeEmptyDOMElement();
    const { container: c3 } = render(<TableConclusions conclusions={null} />);
    expect(c3).toBeEmptyDOMElement();
  });

  test('component in English', () => {
    render(
      <LocaleProvider initialLocale="en" canSwitch>
        <TableConclusions conclusions={[GAP_TWO, OPPORTUNITY]} />
      </LocaleProvider>,
    );
    const items = screen.getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('Uno and Dos pull clear');
    expect(items[1]).toHaveTextContent('4.2% owned');
  });
});

// ---------------------------------------------------------------------------
// The verdict band in the chat surface
// ---------------------------------------------------------------------------

const DUMP = 'Top 3 por xG:\n1. Uno (AAA) 7.29\n2. Dos (BBB) 6.10\n3. Tres (CCC) 5.80';

/** An `@resource` turn: never reaches the orchestrator, so synthesis_turn is null and llm_used false. */
const resourceResponse: AskResponse = {
  ...rankingOkResponse,
  intent: null,
  captain_ranking: null,
  final_text: 'Top Expected Goal Involvements',
  llm_used: false,
  synthesis_turn: null,
  resource_rows: {
    resource: 'top_xg',
    title: 'Top Expected Goal Involvements',
    columns: ['Jugador', 'Equipo', 'Pos', 'Valor'],
    rows: [
      { web_name: 'Uno', team_short: 'AAA', position: 'FWD', value: 7.29 },
      { web_name: 'Dos', team_short: 'BBB', position: 'FWD', value: 6.1 },
    ],
  },
};

function turn(response: AskResponse): Message {
  return {
    id: 'a-1',
    role: 'assistant',
    text: response.final_text,
    outcome: response.outcome,
    llmUsed: response.llm_used,
    degraded: response.degraded,
    response,
  };
}

const renderTurn = (response: AskResponse) => render(<MessageList messages={[turn(response)]} loading={false} />);
const verdictBand = () => screen.queryByRole('region', { name: 'Veredicto' });
const card = () => screen.getByRole('region', { name: 'Datos de la recomendación' });

beforeAll(() => {
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: jest.fn() });
});

describe('table conclusions in the chat surface', () => {
  test('orchestrator turn: conclusions first, then the model prose under them', () => {
    const prose = 'Texto sintético del modelo sobre la tabla.';
    renderTurn({
      ...orchestratorRankCardResponse,
      final_text: prose,
      llm_used: true,
      synthesis_turn: true,
      table_conclusions: [GAP_ONE, CONC_POS],
    });
    const verdict = verdictBand()!;
    const list = within(verdict).getByTestId('table-conclusions');
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    const text = within(verdict).getByText(prose);
    expect(list.compareDocumentPosition(text) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(text.closest('.chat-prose')).toHaveClass('border-t');
  });

  test('orchestrator turn without conclusions: prose still shown, as before', () => {
    const prose = 'Texto sintético del modelo sobre la tabla.';
    renderTurn({ ...orchestratorRankCardResponse, final_text: prose, llm_used: true, synthesis_turn: true });
    const verdict = verdictBand()!;
    expect(within(verdict).getByText(prose)).toBeInTheDocument();
    expect(within(verdict).queryByTestId('table-conclusions')).not.toBeInTheDocument();
    expect(within(verdict).getByText(prose).closest('.chat-prose')).not.toHaveClass('border-t');
  });

  test('resource turn: conclusions only, the resource title is not printed in the band', () => {
    renderTurn({ ...resourceResponse, table_conclusions: [GAP_ONE, READING] });
    const verdict = verdictBand()!;
    expect(within(verdict).getAllByRole('listitem')).toHaveLength(2);
    expect(verdict).toHaveTextContent('Uno se despega');
    expect(verdict).not.toHaveTextContent('Top Expected Goal Involvements');
    expect(within(card()).getByText('Top Expected Goal Involvements')).toBeInTheDocument();
  });

  test.each([
    ['no field', undefined],
    ['null', null],
    ['empty list', []],
    ['only unknown keys', [bad({ key: 'nope', params: {}, evidence: null })]],
  ])('resource turn with no renderable conclusions (%s): no band, the card goes alone', (_name, conclusions) => {
    renderTurn({ ...resourceResponse, table_conclusions: conclusions as TableConclusion[] | null | undefined });
    expect(verdictBand()).not.toBeInTheDocument();
    expect(within(card()).getByText('Uno')).toBeInTheDocument();
  });

  test.each([
    ['/clasificacion → ranking', rankingOkResponse],
    ['/diferenciales → differential', differentialOkResponse],
    ['/calendarios → fixture_run', fixtureRunOkResponse],
  ])('slash table turn hides the deterministic dump: %s', (_name, base) => {
    renderTurn({ ...base, final_text: DUMP, llm_used: false, synthesis_turn: null });
    expect(verdictBand()).not.toBeInTheDocument();
    expect(screen.queryByText(/Top 3 por xG/)).not.toBeInTheDocument();
    expect(card()).toBeInTheDocument();
  });

  test('slash table turn with conclusions: the band holds the conclusions, not the dump', () => {
    renderTurn({ ...rankingOkResponse, final_text: DUMP, llm_used: false, synthesis_turn: undefined, table_conclusions: [CONC_TEAM] });
    const verdict = verdictBand()!;
    expect(verdict).toHaveTextContent('3 de 5 son del AAA');
    expect(verdict).not.toHaveTextContent('Top 3 por xG');
  });

  test('/comparar is not a table: its text is still shown', () => {
    renderTurn({ ...comparisonOkResponse, llm_used: false, synthesis_turn: null });
    expect(within(verdictBand()!).getByText(comparisonOkResponse.final_text)).toBeInTheDocument();
  });

  test('a table view whose text the model wrote keeps its prose', () => {
    const prose = 'Texto sintético del modelo sobre el ranking.';
    renderTurn({ ...rankingOkResponse, final_text: prose, llm_used: true, synthesis_turn: true });
    expect(within(verdictBand()!).getByText(prose)).toBeInTheDocument();
  });

  test('a non-ok turn is untouched: plain bubble with its text', () => {
    const text = 'Texto sintético de aclaración.';
    renderTurn({ ...rankingOkResponse, outcome: 'needs_clarification', captain_ranking: null, final_text: text });
    expect(verdictBand()).not.toBeInTheDocument();
    expect(screen.getByText(text)).toBeInTheDocument();
  });
});

describe('isDeterministicTableText', () => {
  test('table view + no synthesis verdict + llm_used false', () => {
    expect(isDeterministicTableText(resourceResponse)).toBe(true);
    expect(isDeterministicTableText({ ...rankingOkResponse, synthesis_turn: undefined })).toBe(true);
    expect(isDeterministicTableText({ ...rankingOkResponse, llm_used: true })).toBe(false);
    expect(isDeterministicTableText({ ...rankingOkResponse, synthesis_turn: true })).toBe(false);
    expect(isDeterministicTableText(comparisonOkResponse)).toBe(false);
    expect(isDeterministicTableText({ ...rankingOkResponse, outcome: 'not_found' })).toBe(false);
    expect(isDeterministicTableText(undefined)).toBe(false);
  });
});

describe('looksLikeRenderedTable', () => {
  test('a markdown table whose rule row has alignment colons', () => {
    expect(looksLikeRenderedTable('| Jugador | Valor |\n|:---|---:|\n| Uno | 7.29 |')).toBe(true);
    expect(looksLikeRenderedTable('| Jugador | Valor |\n| :---: | :--- |\n| Uno | 7.29 |')).toBe(true);
  });

  test('plain rule rows still match; prose does not', () => {
    expect(looksLikeRenderedTable('| Jugador | Valor |\n|---|---|\n| Uno | 7.29 |')).toBe(true);
    expect(looksLikeRenderedTable('Uno se despega: nadie más llega a ese nivel.')).toBe(false);
    expect(looksLikeRenderedTable('Dos opciones: Uno | Dos | Tres. La hora 12:30 no cambia nada.')).toBe(false);
  });
});
