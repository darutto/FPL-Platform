/**
 * @jest-environment jsdom
 *
 * S6: the membership page and the /fixtures page header, in both languages.
 *
 *   - "Spanish" tests snapshot what is on screen. Those snapshots were recorded against the code as it was BEFORE
 *     the dictionary (origin/main), so a pass means the Spanish page did not change.
 *   - "English" tests: the five Patreon tiers keep their proper names and gain a short English descriptor
 *     ("Tribuna · Supporter"), perks and usage lines read in English, and nothing else is left in Spanish.
 *
 * The page is a server component that asks the request for its language; the test answers that question.
 */
import { render } from '@testing-library/react';
import '@testing-library/jest-dom';

import SubscribePage from '../app/subscribe/page';
import FixturesPage from '../app/fixtures/page';
import { LocaleProvider } from '../lib/i18n/LocaleProvider';
import type { Locale } from '../lib/i18n/locale';
import { onScreen, shape } from './support/screen-text';

let requestLocale: Locale = 'es';
jest.mock('../lib/i18n/server', () => ({
  getRequestLocale: async () => ({ locale: requestLocale, canSwitch: false }),
}));
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn() }),
  usePathname: () => '/fixtures',
}));
jest.mock('../lib/presentation-access', () => ({ usePresentationAccess: () => false }));

/** The five Patreon tiers' proper names, which stay as Patreon spells them in every language. */
const TIER_NAMES = ['Tribuna', 'Gafete de cancha', 'Socio Junior', 'Ejecutivo: carné de plata', 'Ejecutivo: Carné de oro'];
const SPANISH_WORDS =
  /(membres|mensajes|asistente|beneficios|inicia sesi|sincroniz|nivel|unirme|recomendado|\bmes\b|ya eres|elige|prueba|gratis|d[ií]a\b|podcast exclusivo|ruedas de prensa|uniforme|premios|b[uú]squeda|uso del|todos los|acceso|voto|elemento|partidos narrados|competencias|menci[oó]n|calendario|dificultad|rachas|toca un|jornada)/i;
const isProperName = (s: string) => TIER_NAMES.some((n) => s === n || s.startsWith(`${n} ·`));

async function subscribe(locale: Locale) {
  requestLocale = locale;
  return render(await SubscribePage());
}

describe('the membership page', () => {
  test('Spanish: the page is what it was before the dictionary', async () => {
    const { container } = await subscribe('es');
    expect(shape(container)).toMatchSnapshot();
  });

  test('English: names keep Patreon spelling and gain an English descriptor', async () => {
    const { container } = await subscribe('en');
    const strings = onScreen(container);
    for (const expected of [
      'Tribuna · Supporter',
      'Gafete de cancha · Pitch Pass',
      'Socio Junior · Junior Member',
      'Ejecutivo: carné de plata · Executive: Silver Card',
      'Ejecutivo: Carné de oro · Executive: Gold Card',
    ]) {
      expect(strings).toContain(expected);
    }
    // five cards, five different names
    expect(container.querySelectorAll('h2')).toHaveLength(5);
  });

  test('English: the page, the perks and the usage lines read in English', async () => {
    const { container } = await subscribe('en');
    const strings = onScreen(container);
    for (const expected of [
      'Choose your membership', 'Recommended', 'Assistant usage', 'Join',
      '15 messages a day', '60 messages a day · web search', '150 messages a day · web search',
      'Special mention on the podcast', 'All Tribuna benefits', 'All Gafete de cancha benefits', 'All Socio Junior benefits',
      'Matches narrated live on Discord', 'Personalised commemorative item every season',
    ]) {
      expect(strings.some((s) => s.includes(expected))).toBe(true);
    }
    expect(strings.some((s) => /^Try FPL Assistant free with 5 messages a day\./.test(s))).toBe(true);
    expect(strings.some((s) => s.includes('Already a member?'))).toBe(true);
    expect(strings.filter((s) => SPANISH_WORDS.test(s) && !isProperName(s))).toEqual([]);
    expect(shape(container)).toMatchSnapshot();
  });

  test('English: every tier still links to Patreon and the usage numbers did not change', async () => {
    const { container } = await subscribe('en');
    const links = Array.from(container.querySelectorAll('a[href^="https://www.patreon.com/"]'));
    expect(links).toHaveLength(5);
    expect(container.textContent).toMatch(/\$1\s*\/ month/);
    expect(container.textContent).toMatch(/\$50\s*\/ month/);
  });
});

describe('the /fixtures page header', () => {
  const header = (locale: Locale) => {
    global.fetch = jest.fn(async () => ({ ok: false, json: async () => ({}) })) as unknown as typeof fetch;
    const { container } = render(
      <LocaleProvider initialLocale={locale} canSwitch={false}>
        <FixturesPage />
      </LocaleProvider>,
    );
    return container.querySelector('header') as HTMLElement;
  };

  test('Spanish: the header is what it was', () => {
    expect(onScreen(header('es'))).toMatchSnapshot();
  });

  test('English: the header reads in English', () => {
    const strings = onScreen(header('en'));
    expect(strings).toContain('Fixtures');
    expect(strings.some((s) => /^Two-axis difficulty with run detection\. Tap a team or a gameweek to go deeper in the chat\.$/.test(s))).toBe(true);
    expect(strings.filter((s) => SPANISH_WORDS.test(s))).toEqual([]);
  });
});
