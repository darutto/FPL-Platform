/**
 * @jest-environment jsdom
 *
 * i125(a) -- the captain prose and the ranking card name the same list.
 *
 * The bodies are REAL POST /ask responses (fixtures/i125a-captain-ask.json,
 * pinned by the backend's tests/test_i125a_captain_list.py): the backend now
 * opens the answer with the tool's top N, from the same presentation ids
 * RankingTable paints. Here both are rendered by their real components and
 * the names are read off the DOM: the numbered list in the bubble must be
 * the first rows of the card's first section, in the same order -- with a
 * squad connected that is "A) Candidatos de tu plantilla", without it
 * "B) Mejores candidatos globales". Tarkowski (DEF) is second in both.
 */
import { render } from '@testing-library/react';
import '@testing-library/jest-dom';

import MarkdownLite from '../components/MarkdownLite';
import RankingTable from '../components/intents/RankingTable';
import type { RankedCaptainEntry, RankingPresentation } from '../lib/types';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const bodies = require('./fixtures/i125a-captain-ask.json');

interface Body {
  final_text: string;
  captain_ranking: RankedCaptainEntry[];
  presentation: RankingPresentation;
  squad_source: 'connected' | 'not_connected' | 'unavailable' | null;
}

function textList(body: Body): string[] {
  const { container } = render(<MarkdownLite text={body.final_text} />);
  const ol = container.querySelector('ol');
  expect(ol).not.toBeNull();
  return Array.from(ol!.querySelectorAll('li')).map((li) => li.querySelector('strong')?.textContent ?? '');
}

function cardFirstSection(body: Body): { title: string; names: string[] } {
  const { container } = render(
    <RankingTable
      data={body.captain_ranking}
      squadSource={body.squad_source}
      presentation={body.presentation}
    />,
  );
  const section = container.querySelector('section');
  expect(section).not.toBeNull();
  const title = section!.querySelector('h3')?.textContent ?? '';
  const rows = Array.from(section!.children[1].children);
  const names = rows.map((row) => {
    const hit = body.captain_ranking.find((e) => row.textContent?.includes(e.web_name));
    return hit?.web_name ?? '';
  });
  return { title, names };
}

describe('i125(a) — prose list === card list (real /ask bodies)', () => {
  test.each([
    ['team', 'A) Candidatos de tu plantilla', ['Groß', 'Tarkowski', 'Haaland']],
    ['noteam', 'B) Mejores candidatos globales', ['Groß', 'Tarkowski', 'Barnes']],
  ])('%s: the bubble lists the first rows of the card section, in order', (arm, title, expected) => {
    const body = bodies[arm] as Body;
    const prose = textList(body);
    const card = cardFirstSection(body);
    expect(prose).toEqual(expected);
    expect(card.title).toBe(title);
    expect(card.names.slice(0, prose.length)).toEqual(prose);
  });
});
