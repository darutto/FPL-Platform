/**
 * @jest-environment jsdom
 *
 * The quota pill and its upgrade modal, in both languages. Patreon tier names are proper
 * names and stay as they are; the surrounding words follow the locale (docs/i18n-glossary.md).
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import QuotaIndicator from '../components/chat/QuotaIndicator';
import { LocaleProvider } from '@/lib/i18n/LocaleProvider';
import type { Locale } from '@/lib/i18n/locale';

const status = {
  allowed: true, tier: 'free', daily_tokens_used: 100, daily_message_count: 3, monthly_tokens_used: 400, monthly_message_count: 20,
  daily_token_cap: 1000, monthly_token_cap: 9000, daily_message_cap: 5, monthly_message_cap: 50,
  reason: null, upgrade_prompt_es: null, upgrade_prompt_en: null,
};

function show(locale: Locale) {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => status }) as unknown as typeof fetch;
  return render(
    <LocaleProvider initialLocale={locale} canSwitch={false}>
      <QuotaIndicator />
    </LocaleProvider>,
  );
}

test('English: Day/Month in the pill, the tooltip, and the whole modal', async () => {
  const user = userEvent.setup();
  show('en');
  const pill = await screen.findByRole('button', { name: /Day 2\/5/ });
  expect(pill).toHaveTextContent('Month 30/50');
  expect(pill).toHaveAttribute('title', 'Daily quota: 2/5 msgs · Monthly: 30/50 msgs\nDaily tokens: 900/1000 · Monthly: 8600/9000');

  await user.click(pill);
  const modal = screen.getByText('Message quota').closest('div')!.parentElement as HTMLElement;
  expect(within(modal).getByText('Today')).toBeInTheDocument();
  expect(within(modal).getByText('This month')).toBeInTheDocument();
  expect(within(modal).getAllByText('2 msgs left').length).toBe(1);
  expect(within(modal).getByText('Current tier:')).toBeInTheDocument();
  expect(within(modal).getByRole('columnheader', { name: 'Day' })).toBeInTheDocument();
  expect(within(modal).getByRole('columnheader', { name: 'Month' })).toBeInTheDocument();
  expect(within(modal).getByRole('cell', { name: 'Free' })).toBeInTheDocument();
  expect(within(modal).getByRole('link', { name: 'Upgrade on Patreon' })).toBeInTheDocument();
  expect(within(modal).getByRole('button', { name: 'Close' })).toBeInTheDocument();
});

test('Spanish: every string it had', async () => {
  const user = userEvent.setup();
  show('es');
  const pill = await screen.findByRole('button', { name: /Día 2\/5/ });
  expect(pill).toHaveTextContent('Mes 30/50');
  expect(pill).toHaveAttribute('title', 'Cuota diaria: 2/5 msgs · Mensual: 30/50 msgs\nTokens diarios: 900/1000 · Mensuales: 8600/9000');

  await user.click(pill);
  expect(screen.getByText('Cuota de mensajes')).toBeInTheDocument();
  expect(screen.getByText('Hoy')).toBeInTheDocument();
  expect(screen.getByText('Este mes')).toBeInTheDocument();
  expect(screen.getByText('2 msgs restantes')).toBeInTheDocument();
  expect(screen.getByText('Tier actual:')).toBeInTheDocument();
  expect(screen.getByRole('cell', { name: 'Gratis' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Mejorar en Patreon' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Cerrar' })).toBeInTheDocument();
});
