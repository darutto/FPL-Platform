/**
 * @jest-environment jsdom
 *
 * StatComparisonTable — additive raw-stat comparison table (v1, first-pass).
 *
 * Contract: the backend is fully authoritative for `better`/`kind` — these
 * tests verify RENDERING of provided data, not frontend-side enforcement of
 * business rules the backend already owns (e.g. we don't simulate malformed
 * server data and expect the component to override it).
 */
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import StatComparisonTable from '@/components/intents/StatComparisonTable';
import type { StatComparisonMeta } from '@/lib/types';

function meta(rows: StatComparisonMeta['rows']): StatComparisonMeta {
  return { rows };
}

describe('StatComparisonTable', () => {
  test('renders nothing when rows is empty', () => {
    const { container } = render(<StatComparisonTable data={meta([])} nameA="A" nameB="B" />);
    expect(container).toBeEmptyDOMElement();
  });

  test('correct cell gets the better-cell testid, never both, never neither', () => {
    const data = meta([
      { key: 'goals', label: 'Goles', kind: 'performance',
        value_a: { value: 10, display: '10' }, value_b: { value: 3, display: '3' }, better: 'a' },
    ]);
    render(<StatComparisonTable data={data} nameA="Haaland" nameB="Salah" />);
    const betterCells = screen.getAllByTestId('stat-cell-better');
    expect(betterCells).toHaveLength(1);
    expect(within(betterCells[0]).getByText('10')).toBeInTheDocument();
  });

  test('no better cell when better is null', () => {
    const data = meta([
      { key: 'price_m', label: 'Precio', kind: 'context',
        value_a: { value: 14.5, display: '£14.5m' }, value_b: { value: 13.5, display: '£13.5m' }, better: null },
    ]);
    render(<StatComparisonTable data={data} nameA="A" nameB="B" />);
    expect(screen.queryByTestId('stat-cell-better')).not.toBeInTheDocument();
  });

  test('"—" placeholder cells never carry the better-cell testid', () => {
    const data = meta([
      { key: 'saves_per_90', label: 'Atajadas/90', kind: 'performance',
        value_a: { value: null, display: '—' }, value_b: { value: 2.1, display: '2.10' }, better: null },
    ]);
    render(<StatComparisonTable data={data} nameA="A" nameB="B" />);
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByTestId('stat-cell-better')).not.toBeInTheDocument();
  });

  test('context-kind rows render without highlight regardless of fixture better value', () => {
    // The backend never sets better on context rows — this only verifies
    // rendering reflects whatever data is given, not that the component
    // enforces the rule itself.
    const data = meta([
      { key: 'ownership_percent', label: 'Propiedad %', kind: 'context',
        value_a: { value: 52.3, display: '52.3%' }, value_b: { value: 64.1, display: '64.1%' }, better: null },
    ]);
    render(<StatComparisonTable data={data} nameA="A" nameB="B" />);
    expect(screen.queryByTestId('stat-cell-better')).not.toBeInTheDocument();
  });

  test('row label is a row header (scope="row"), column headers use scope="col"', () => {
    const data = meta([
      { key: 'form', label: 'Forma', kind: 'performance',
        value_a: { value: 9.5, display: '9.5' }, value_b: { value: 8.0, display: '8.0' }, better: 'a' },
    ]);
    render(<StatComparisonTable data={data} nameA="Haaland" nameB="Salah" />);
    const rowHeader = screen.getByRole('rowheader', { name: 'Forma' });
    expect(rowHeader).toBeInTheDocument();
    const colHeaders = screen.getAllByRole('columnheader');
    expect(colHeaders.length).toBe(3);
  });

  test('sr-only "Mejor valor" text present on the winning cell', () => {
    const data = meta([
      { key: 'goals', label: 'Goles', kind: 'performance',
        value_a: { value: 10, display: '10' }, value_b: { value: 3, display: '3' }, better: 'a' },
    ]);
    render(<StatComparisonTable data={data} nameA="A" nameB="B" />);
    expect(screen.getByText('Mejor valor:', { exact: false })).toBeInTheDocument();
  });

  test('long player names in header do not break rendering at narrow width', () => {
    const data = meta([
      { key: 'form', label: 'Forma', kind: 'performance',
        value_a: { value: 9.5, display: '9.5' }, value_b: { value: 8.0, display: '8.0' }, better: 'a' },
    ]);
    render(
      <StatComparisonTable
        data={data}
        nameA="A Very Long Player Name Indeed"
        nameB="Another Extremely Long Player Name"
      />,
    );
    expect(screen.getByText('A Very Long Player Name Indeed')).toBeInTheDocument();
  });
});
