/** @jest-environment jsdom */
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import SquadPitch from '../components/squad/SquadPitch';

const squad = {
  gw: 8,
  summary: { gw_points: 61, total_points: 432, bank: 14 },
  players: [
    { id: 1, web_name: 'Pickford', team_short: 'EVE', position: 'GK', price: 55, sel: '18.0', form: '4.5', gw_points: 6, pick_position: 1, is_starter: true, is_captain: false },
    { id: 2, web_name: 'Gabriel', team_short: 'ARS', position: 'DEF', price: 60, sel: '22.0', form: '6.2', gw_points: 8, pick_position: 2, is_starter: true, is_captain: false },
    { id: 3, web_name: 'Cole Palmer', team_short: 'CHE', position: 'MID', price: 105, sel: '45.3', form: '8.4', gw_points: 12, pick_position: 6, is_starter: true, is_captain: true },
    { id: 4, web_name: 'Haaland', team_short: 'MCI', position: 'FWD', price: 150, sel: '62.1', form: '7.0', gw_points: 10, pick_position: 10, is_starter: true, is_captain: false },
    { id: 5, web_name: 'Calvert-Lewin', team_short: 'LEE', position: 'FWD', price: 55, sel: '2.1', form: '3.0', gw_points: 2, pick_position: 15, is_starter: false, is_captain: false },
  ],
};

const originalFetch = global.fetch;
let fetchMock: jest.Mock;

beforeEach(() => {
  fetchMock = jest.fn().mockResolvedValue({ ok: true, json: async () => squad });
  global.fetch = fetchMock;
});

afterEach(() => {
  global.fetch = originalFetch;
});

test('loads the connected squad, selects a starter, and deselects it without asking AI', async () => {
  const onAskPlayer = jest.fn();
  const onGw = jest.fn();
  render(<SquadPitch teamId={123} onAskPlayer={onAskPlayer} onGw={onGw} />);

  const captain = await screen.findByRole('button', { name: 'Cole Palmer, CHE, capitán' });
  expect(fetchMock).toHaveBeenCalledWith('/api/fpl-squad/123');
  expect(onGw).toHaveBeenCalledWith(8);
  expect(captain).toHaveAttribute('aria-pressed', 'false');
  expect(screen.queryByRole('region')).not.toBeInTheDocument();

  fireEvent.click(captain);
  const detail = screen.getByRole('region', { name: 'Detalle de Cole Palmer' });
  expect(within(detail).getByText('45.3%')).toBeInTheDocument();
  expect(within(detail).getByText('8.4')).toBeInTheDocument();
  expect(captain).toHaveAttribute('aria-pressed', 'true');

  fireEvent.click(captain);
  expect(screen.queryByRole('region')).not.toBeInTheDocument();
  expect(captain).toHaveAttribute('aria-pressed', 'false');
  expect(onAskPlayer).not.toHaveBeenCalled();
});

test('bench selection replaces the starter detail and Ask AI uses only the selected player', async () => {
  const onAskPlayer = jest.fn();
  render(<SquadPitch teamId={123} onAskPlayer={onAskPlayer} />);
  const starter = await screen.findByRole('button', { name: 'Haaland, MCI' });
  fireEvent.click(starter);
  const bench = screen.getByRole('button', { name: 'Calvert-Lewin, LEE' });
  fireEvent.click(bench);

  expect(screen.queryByRole('region', { name: 'Detalle de Haaland' })).not.toBeInTheDocument();
  expect(starter).toHaveAttribute('aria-pressed', 'false');
  expect(bench).toHaveAttribute('aria-pressed', 'true');
  const detail = screen.getByRole('region', { name: 'Detalle de Calvert-Lewin' });
  expect(onAskPlayer).not.toHaveBeenCalled();
  fireEvent.click(within(detail).getByRole('button', { name: /Ask AI/ }));
  expect(onAskPlayer).toHaveBeenCalledTimes(1);
  expect(onAskPlayer).toHaveBeenCalledWith('Cuéntame sobre Calvert-Lewin — ¿lo alineo esta semana?');
});

test('a resize preserves the selected player and does not refetch or duplicate the formation', async () => {
  render(<SquadPitch teamId={123} onAskPlayer={jest.fn()} />);
  const captain = await screen.findByRole('button', { name: 'Cole Palmer, CHE, capitán' });
  fireEvent.click(captain);
  const detail = screen.getByRole('region', { name: 'Detalle de Cole Palmer' });

  fireEvent(window, new Event('resize'));
  expect(screen.getByRole('region', { name: 'Detalle de Cole Palmer' })).toBe(detail);
  expect(screen.getAllByRole('button', { name: 'Cole Palmer, CHE, capitán' })).toHaveLength(1);
  expect(captain).toHaveAttribute('aria-pressed', 'true');
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test('changing the connected team clears the previous player selection', async () => {
  const onAskPlayer = jest.fn();
  const { rerender } = render(<SquadPitch teamId={123} onAskPlayer={onAskPlayer} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Gabriel, ARS' }));
  expect(screen.getByRole('region', { name: 'Detalle de Gabriel' })).toBeInTheDocument();

  rerender(<SquadPitch teamId={456} onAskPlayer={onAskPlayer} />);
  const defender = await screen.findByRole('button', { name: 'Gabriel, ARS' });
  expect(fetchMock).toHaveBeenLastCalledWith('/api/fpl-squad/456');
  expect(defender).toHaveAttribute('aria-pressed', 'false');
  expect(screen.queryByRole('region')).not.toBeInTheDocument();
});

test('regression: the squad pitch keeps its own landscape drawing (unchanged by the position-changes pitch)', async () => {
  const { container } = render(<SquadPitch teamId={123} onAskPlayer={jest.fn()} />);
  await screen.findByRole('button', { name: 'Haaland, MCI' });
  const box = container.querySelector('[data-squad-pitch]') as HTMLElement;
  expect(box.className).toMatch(/aspect-\[5\/3\]/);
  const marks = (sel: string) => {
    const svg = container.querySelector(sel) as SVGSVGElement;
    return [svg.getAttribute('viewBox'), svg.getAttribute('preserveAspectRatio'),
      ...Array.from(svg.children).map((el) => `${el.tagName}:${['x', 'y', 'width', 'height', 'x1', 'y1', 'x2', 'y2', 'cx', 'cy', 'r']
        .map((k) => el.getAttribute(k)).filter((v) => v !== null).join(',')}`)];
  };
  expect(marks('.squad-pitch-standard')).toEqual(['0 0 400 240', 'xMidYMid meet',
    'rect:8,8,384,224', 'line:8,120,392,120', 'circle:200,120,34', 'rect:130,8,140,36', 'rect:130,196,140,36',
    'rect:162,8,76,15', 'rect:162,217,76,15']);
  expect(marks('.squad-pitch-sidebar')).toEqual(['0 0 400 340', 'xMidYMid meet',
    'rect:8,8,384,324', 'line:8,170,392,170', 'circle:200,170,34', 'rect:130,8,140,45', 'rect:130,287,140,45',
    'rect:162,8,76,18', 'rect:162,314,76,18']);
});
