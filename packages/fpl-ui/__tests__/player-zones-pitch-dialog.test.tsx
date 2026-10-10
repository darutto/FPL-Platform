/**
 * @jest-environment jsdom
 *
 * i152 — the mini-pitch is a button that opens an enlarged, player-only view.
 */
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

import PlayerCard from '../components/intents/PlayerCard';
import PlayerZonasSection from '../components/intents/PlayerZonasSection';
import { playerSnapshotOkResponse } from './fixtures/sample-responses';
import type { PlayerSnapshotMeta, PlayerZonalOutlookMeta } from '../lib/types';

const zonal: PlayerZonalOutlookMeta = {
  zones: [
    { zone: 'in-box / central', share: 0.5923 },
    { zone: 'edge-of-box / right', share: 0.2611 },
  ],
  gw_from: 6,
  gw_to: 8,
  fixtures: [
    { gameweek: 6, fixture_id: 53, opponent: 'Bournemouth', opponent_short: 'BOU', is_home: true, status: 'neutral', matches: [] },
    {
      gameweek: 8, fixture_id: 73, opponent: 'Spurs', opponent_short: 'TOT', is_home: true, status: 'favorable',
      matches: [{ zone: 'in-box / central', delta_vs_avg: 0.0547, player_share: 0.5923 }],
    },
  ],
  verdict_kind: 'favorable',
  verdict: 'Cruce favorable en J8 (Spurs).',
  data_provenance: null,
};

const card = (z: PlayerZonalOutlookMeta): PlayerSnapshotMeta => ({
  ...playerSnapshotOkResponse.player_snapshot!, web_name: 'Palmer', zonal: z,
});

const trigger = () => screen.getByTestId('player-zones-pitch-button');
const dialog = () => screen.queryByRole('dialog');

describe('mini-pitch button', () => {
  test('is an accessible button with the player in its label', () => {
    render(<PlayerCard data={card(zonal)} />);
    const b = screen.getByRole('button', { name: 'Ampliar zonas de Palmer' });
    expect(b).toBe(trigger());
    expect(b).toHaveAttribute('type', 'button');
    expect(b).toHaveAttribute('aria-haspopup', 'dialog');
    expect(b).toHaveAttribute('aria-expanded', 'false');
    expect(b.className).toContain('focus-visible:outline');   // visible focus ring
  });

  test('is reachable with the keyboard and opens with Enter', async () => {
    const user = userEvent.setup();
    render(<PlayerCard data={card(zonal)} />);
    await user.tab();
    expect(trigger()).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(dialog()).toBeInTheDocument();
  });

  test('no zones → no button, no pitch', () => {
    render(<PlayerCard data={card({ ...zonal, zones: [{ zone: 'somewhere', share: 0.5 }] })} />);
    expect(screen.queryByTestId('player-zones-pitch-button')).not.toBeInTheDocument();
  });

  test('responsive layout: stacked and full width on mobile, 220px beside the chips from 481px', () => {
    render(<PlayerCard data={card(zonal)} />);
    const wrap = screen.getByTestId('player-zonas-pitch-wrap');
    expect(wrap.className).toContain('w-full');
    expect(wrap.className).toContain('min-[481px]:w-[220px]');
    expect(wrap.parentElement!.className).toContain('flex-col');
    expect(wrap.parentElement!.className).toContain('min-[481px]:flex-row');
  });
});

describe('enlarged view', () => {
  test('opens as a modal dialog labelled with the player', async () => {
    const user = userEvent.setup();
    render(<PlayerCard data={card(zonal)} />);
    await user.click(trigger());
    const d = screen.getByRole('dialog', { name: 'Zonas de Palmer' });
    expect(d).toHaveAttribute('aria-modal', 'true');
    expect(trigger()).toHaveAttribute('aria-expanded', 'true');
  });

  test('shows only the player: same zones and percentages, no rival picker or rival zones', async () => {
    const user = userEvent.setup();
    render(<PlayerCard data={card(zonal)} />);
    await user.click(trigger());
    const d = screen.getByRole('dialog');
    expect(within(d).getByTestId('player-zones-dialog-list')).toHaveTextContent('Área centro · 59% de su xG sin penalti');
    expect(within(d).getByTestId('player-zones-dialog-list')).toHaveTextContent('Frontal der · 26% de su xG sin penalti');
    expect(within(d).getAllByRole('listitem')).toHaveLength(2);
    // nothing to pick and no rival names inside the dialog
    expect(within(d).queryByRole('combobox')).not.toBeInTheDocument();
    expect(within(d).queryByRole('tab')).not.toBeInTheDocument();
    expect(within(d).queryByRole('radio')).not.toBeInTheDocument();
    expect(d).not.toHaveTextContent('Bournemouth');
    expect(d).not.toHaveTextContent('Spurs');
    // the only button inside is the close X
    expect(within(d).getAllByRole('button')).toHaveLength(1);
  });

  test('draws the same zones with the same colours as the mini', async () => {
    const user = userEvent.setup();
    render(<PlayerCard data={card(zonal)} />);
    await user.click(trigger());
    for (const zone of ['in-box-central', 'edge-of-box-right']) {
      const mini = screen.getByTestId(`pitch-cell-${zone}`);
      const big = screen.getByTestId(`pitch-cell-large-${zone}`);
      for (const attr of ['x', 'y', 'width', 'height', 'fill', 'fill-opacity', 'data-match']) {
        expect(big.getAttribute(attr)).toBe(mini.getAttribute(attr));
      }
    }
    expect(screen.getByTestId('pitch-cell-large-in-box-central').getAttribute('fill')).toBe('#02EBAE');
    expect(screen.getByTestId('pitch-cell-large-edge-of-box-right').getAttribute('fill')).toBe('#6b6975');
    expect(screen.getAllByRole('img').map((e) => e.getAttribute('aria-label'))[0]).toBe(
      screen.getAllByRole('img').map((e) => e.getAttribute('aria-label'))[1],
    );
  });

  test('shows the legend only when a favorable cross exists', async () => {
    const user = userEvent.setup();
    const { unmount } = render(<PlayerCard data={card(zonal)} />);
    await user.click(trigger());
    expect(screen.getByTestId('player-zones-dialog-legend')).toHaveTextContent('Turquesa');
    unmount();
    render(<PlayerCard data={card({ ...zonal, fixtures: [zonal.fixtures[0]] })} />);
    await user.click(trigger());
    expect(screen.queryByTestId('player-zones-dialog-legend')).not.toBeInTheDocument();
  });

  test('closes with the X', async () => {
    const user = userEvent.setup();
    render(<PlayerCard data={card(zonal)} />);
    await user.click(trigger());
    await user.click(screen.getByRole('button', { name: 'Cerrar' }));
    expect(dialog()).not.toBeInTheDocument();
  });

  test('closes with Esc', async () => {
    const user = userEvent.setup();
    render(<PlayerCard data={card(zonal)} />);
    await user.click(trigger());
    await user.keyboard('{Escape}');
    expect(dialog()).not.toBeInTheDocument();
  });

  test('closes when tapping outside the panel, not when tapping inside it', async () => {
    const user = userEvent.setup();
    render(<PlayerCard data={card(zonal)} />);
    await user.click(trigger());
    await user.click(screen.getByTestId('player-zones-dialog'));          // inside
    expect(dialog()).toBeInTheDocument();
    await user.click(within(screen.getByTestId('player-zones-dialog')).getByTestId('player-zones-pitch-large'));
    expect(dialog()).toBeInTheDocument();
    await user.click(screen.getByTestId('player-zones-dialog-backdrop')); // outside
    expect(dialog()).not.toBeInTheDocument();
  });

  test('moves focus inside on open and returns it to the mini-pitch on close (every way)', async () => {
    const user = userEvent.setup();
    render(<PlayerCard data={card(zonal)} />);
    for (const close of [
      () => user.click(screen.getByRole('button', { name: 'Cerrar' })),
      () => user.keyboard('{Escape}'),
      () => user.click(screen.getByTestId('player-zones-dialog-backdrop')),
    ]) {
      await user.click(trigger());
      expect(screen.getByRole('button', { name: 'Cerrar' })).toHaveFocus();
      await close();
      expect(dialog()).not.toBeInTheDocument();
      expect(trigger()).toHaveFocus();
    }
  });

  test('traps focus: Tab and Shift+Tab stay inside the dialog', async () => {
    const user = userEvent.setup();
    render(<PlayerCard data={card(zonal)} />);
    await user.click(trigger());
    const x = screen.getByRole('button', { name: 'Cerrar' });
    expect(x).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true);
    await user.tab({ shift: true });
    expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true);
    // focus that escaped (e.g. clicked on the page) is pulled back in on Tab
    trigger().focus();
    await user.tab();
    expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true);
  });

  test('locks the page scroll while open and restores it after', async () => {
    const user = userEvent.setup();
    document.body.style.overflow = 'auto';
    render(<PlayerCard data={card(zonal)} />);
    await user.click(trigger());
    expect(document.body.style.overflow).toBe('hidden');
    await user.keyboard('{Escape}');
    expect(document.body.style.overflow).toBe('auto');
    document.body.style.overflow = '';
  });

  test('scroll lock is released if the card unmounts while open', async () => {
    const user = userEvent.setup();
    document.body.style.overflow = '';
    const { unmount } = render(<PlayerCard data={card(zonal)} />);
    await user.click(trigger());
    unmount();
    expect(document.body.style.overflow).toBe('');
  });

  test('desktop window and mobile full screen are CSS-only variants of the same dialog', async () => {
    const user = userEvent.setup();
    render(<PlayerCard data={card(zonal)} />);
    await user.click(trigger());
    const d = screen.getByTestId('player-zones-dialog');
    expect(d.className).toContain('max-w-[640px]');
    expect(d.className).toContain('max-[480px]:h-full');
    expect(d.className).toContain('max-[480px]:max-w-none');
    expect(screen.getByTestId('player-zones-dialog-backdrop').className).toContain('max-[480px]:p-0');
  });

  test('the section works standalone and the dialog never renders when closed', () => {
    render(<PlayerZonasSection zonal={zonal} playerName="Palmer" />);
    expect(dialog()).not.toBeInTheDocument();
    expect(screen.queryByTestId('player-zones-pitch-large')).not.toBeInTheDocument();
  });
});
