/**
 * @jest-environment jsdom
 *
 * GenericCard + CardTable + InjuryListTable rendering tests (Track B).
 *
 * Covers:
 *   - GenericCard: title/pills, subtitle, hero (with/without tone), table
 *     body, footer — and that optional pieces are omitted gracefully.
 *   - CardTable: column headers, cell alignment/kind rendering (text/mono/
 *     badge), badge tone inference.
 *   - InjuryListTable: injury_list's generic_card adapter renders through
 *     InjuriesTable's row treatment (status badge, chance %, news).
 */
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import GenericCard from '../components/intents/GenericCard';
import CardTable, { inferBadgeTone } from '../components/intents/CardTable';
import InjuryListTable, { genericCardToInjuryRows } from '../components/intents/InjuryListTable';
import type { GenericCardMeta } from '../lib/types';
import {
  genericCardOkResponse,
  genericCardMinimalResponse,
  genericCardNoHeroToneResponse,
  injuryListGenericResponse,
} from './fixtures/sample-responses';

const fullMeta = genericCardOkResponse.generic_card!;
const minimalMeta = genericCardMinimalResponse.generic_card!;
const noHeroToneMeta = genericCardNoHeroToneResponse.generic_card!;
const injuryMeta = injuryListGenericResponse.generic_card!;

// ---------------------------------------------------------------------------
// GenericCard
// ---------------------------------------------------------------------------

describe('GenericCard', () => {
  test('renders title and pills', () => {
    render(<GenericCard data={fullMeta} />);
    expect(screen.getByText('Cambios de precio')).toBeInTheDocument();
    expect(screen.getByText('8 suben')).toBeInTheDocument();
    expect(screen.getByText('4 bajan')).toBeInTheDocument();
  });

  test('renders subtitle when present', () => {
    render(<GenericCard data={fullMeta} />);
    expect(screen.getByText('Actualizado hoy a las 02:00')).toBeInTheDocument();
  });

  test('renders hero value + label, toned', () => {
    render(<GenericCard data={fullMeta} />);
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('Jugadores subieron de precio')).toBeInTheDocument();
  });

  test('hero with tone=null still renders (falls back to neutral styling)', () => {
    render(<GenericCard data={noHeroToneMeta} />);
    const value = screen.getByText('5');
    expect(value).toBeInTheDocument();
    expect(value.className).toContain('text-white');
  });

  test('renders table rows from columns/rows', () => {
    render(<GenericCard data={fullMeta} />);
    expect(screen.getByText('Jugador')).toBeInTheDocument();
    expect(screen.getByText('Haaland')).toBeInTheDocument();
    expect(screen.getByText('Salah')).toBeInTheDocument();
    expect(screen.getByText('Rashford')).toBeInTheDocument();
    expect(screen.getAllByText('+0.1').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('-0.1')).toBeInTheDocument();
  });

  test('renders footer when present', () => {
    render(<GenericCard data={fullMeta} />);
    expect(
      screen.getByText('Los precios pueden cambiar hasta la medianoche.'),
    ).toBeInTheDocument();
  });

  test('minimal card: title only — no subtitle, hero, table, or footer', () => {
    render(<GenericCard data={minimalMeta} />);
    expect(screen.getByText('Sin datos adicionales')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    // no pills rendered when the list is empty
    expect(screen.queryByText('suben')).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// CardTable
// ---------------------------------------------------------------------------

describe('CardTable', () => {
  test('renders nothing when columns or rows are empty', () => {
    const { container: emptyRows } = render(
      <CardTable columns={fullMeta.columns} rows={[]} />,
    );
    expect(emptyRows.firstChild).toBeNull();

    const { container: emptyCols } = render(<CardTable columns={[]} rows={fullMeta.rows} />);
    expect(emptyCols.firstChild).toBeNull();
  });

  test('renders a badge-kind cell as a tinted pill', () => {
    const columns: GenericCardMeta['columns'] = [
      { header: 'Jugador', align: 'left', kind: 'text' },
      { header: 'Estado', align: 'left', kind: 'badge' },
    ];
    render(<CardTable columns={columns} rows={[['Saka', 'Duda']]} />);
    expect(screen.getByText('Duda')).toBeInTheDocument();
  });

  test('inferBadgeTone reads status vocabulary (EN + ES)', () => {
    expect(inferBadgeTone('Injured')).toBe('bad');
    expect(inferBadgeTone('Lesionado')).toBe('bad');
    expect(inferBadgeTone('Doubtful (75%)')).toBe('warn');
    expect(inferBadgeTone('Available')).toBe('good');
    expect(inferBadgeTone('Disponible')).toBe('good');
    expect(inferBadgeTone('Unknown status')).toBe('warn');
  });
});

// ---------------------------------------------------------------------------
// InjuryListTable — injury_list generic_card adapter
// ---------------------------------------------------------------------------

describe('InjuryListTable (injury_list routing)', () => {
  test('renders card title from generic_card', () => {
    render(<InjuryListTable data={injuryMeta} />);
    expect(screen.getByText('Lesiones')).toBeInTheDocument();
  });

  test('renders each row via InjuriesTable-style treatment: name, status, news', () => {
    render(<InjuryListTable data={injuryMeta} />);
    expect(screen.getByText('Saka')).toBeInTheDocument();
    expect(screen.getByText('Duda')).toBeInTheDocument();
    expect(screen.getByText('Molestia en el tobillo')).toBeInTheDocument();
    expect(screen.getByText('Isak')).toBeInTheDocument();
    expect(screen.getByText('Lesionado')).toBeInTheDocument();
  });

  test('empty-rows adapter shows the "no injuries" fallback line', () => {
    render(<InjuryListTable data={{ ...injuryMeta, rows: [] }} />);
    expect(screen.getByText('Sin lesiones reportadas')).toBeInTheDocument();
  });

  test('genericCardToInjuryRows maps columns by header keyword, EN+ES', () => {
    const rows = genericCardToInjuryRows(injuryMeta);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      web_name: 'Saka',
      team_short: 'ARS',
      position: 'MID',
      status_label: 'Duda',
      chance_of_playing: 75,
      news: 'Molestia en el tobillo',
    });
    expect(rows[1]).toMatchObject({
      web_name: 'Isak',
      chance_of_playing: 0,
      status_label: 'Lesionado',
    });
  });

  test('genericCardToInjuryRows degrades gracefully when columns are unrecognized', () => {
    const weirdMeta: GenericCardMeta = {
      accent: 'coral',
      title: 'Lesiones',
      subtitle: null,
      hero: null,
      pills: [],
      columns: [{ header: 'Col A', align: 'left', kind: 'text' }],
      rows: [['Some Player']],
      footer: null,
    };
    const rows = genericCardToInjuryRows(weirdMeta);
    expect(rows).toHaveLength(1);
    // no column matched a known field, so the adapter falls back to the
    // first cell as the player name rather than leaving it blank.
    expect(rows[0].web_name).toBe('Some Player');
    expect(rows[0].chance_of_playing).toBeNull();
  });
});
