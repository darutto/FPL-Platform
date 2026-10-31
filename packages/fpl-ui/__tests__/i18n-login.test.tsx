/**
 * @jest-environment jsdom
 *
 * Walkthrough flow 1: /login and /post-login in both languages. The Clerk widget is Clerk's own copy (see the
 * walkthrough, section 3) and is stubbed here; what the app owns is the title, the subtitle and the wait line.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

jest.mock('@clerk/nextjs', () => ({
  SignIn: () => <div data-testid="clerk-sign-in" />,
  useAuth: () => ({ getToken: jest.fn(() => Promise.resolve('t')) }),
}));
jest.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams('') }));

import LoginPage from '../app/login/page';
import PostLoginPage from '../app/post-login/page';
import { LocaleProvider } from '@/lib/i18n/LocaleProvider';
import type { Locale } from '@/lib/i18n/locale';

beforeEach(() => {
  global.fetch = jest.fn(() => new Promise(() => {})) as unknown as typeof fetch; // post-login stays on its wait line
});

const inLocale = (locale: Locale, ui: React.ReactElement) =>
  render(<LocaleProvider initialLocale={locale} canSwitch={false}>{ui}</LocaleProvider>);

test('login reads in English', () => {
  inLocale('en', <LoginPage />);
  expect(screen.getByRole('heading', { name: 'FPL Assistant' })).toBeInTheDocument();
  expect(screen.getByText('Sign in with your Patreon account to access the chat.')).toBeInTheDocument();
  expect(screen.getByTestId('clerk-sign-in')).toBeInTheDocument();
});

test('login stays Spanish in Spanish', () => {
  inLocale('es', <LoginPage />);
  expect(screen.getByRole('heading', { name: 'FPL Asistente' })).toBeInTheDocument();
  expect(screen.getByText('Inicia sesión con tu cuenta de Patreon para acceder al chat.')).toBeInTheDocument();
});

test('post-login waits in the visitor language', () => {
  const en = inLocale('en', <PostLoginPage />);
  expect(screen.getByText('Checking your Patreon membership...')).toBeInTheDocument();
  en.unmount();
  inLocale('es', <PostLoginPage />);
  expect(screen.getByText('Verificando tu membresía de Patreon...')).toBeInTheDocument();
});
