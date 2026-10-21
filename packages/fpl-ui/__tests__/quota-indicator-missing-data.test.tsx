/** @jest-environment jsdom */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import QuotaIndicator from '../components/chat/QuotaIndicator';

const respond = (body: unknown) => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => body }) as unknown as typeof fetch;
};
const complete = {
  allowed: true, tier: 'free', daily_tokens_used: 0, daily_message_count: 3, monthly_tokens_used: 0, monthly_message_count: 20,
  daily_token_cap: 1000, monthly_token_cap: 9000, daily_message_cap: 5, monthly_message_cap: 50,
  reason: null, upgrade_prompt_es: null, upgrade_prompt_en: null,
};

test('shows the counters when the payload is complete', async () => {
  respond(complete);
  render(<QuotaIndicator />);
  expect(await screen.findByText(/Día 2\/5/)).toBeInTheDocument();
});

test('hides itself instead of printing NaN when the counters are missing', async () => {
  respond({ allowed: true, tier: 'free' });
  const { container } = render(<QuotaIndicator />);
  await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  await new Promise((r) => setTimeout(r, 0));
  expect(container).toBeEmptyDOMElement();
  expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
});
