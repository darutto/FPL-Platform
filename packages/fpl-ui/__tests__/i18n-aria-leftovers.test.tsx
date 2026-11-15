/**
 * @jest-environment jsdom
 *
 * Accessible names that were still Spanish after the screens were translated: the table region in a chat answer and
 * the section switcher. Spanish stays exactly as it was.
 */
import { render } from '@testing-library/react';
import '@testing-library/jest-dom';

import MarkdownLite from '../components/MarkdownLite';
import SectionSwitcher from '../components/chat/SectionSwitcher';
import { LocaleProvider } from '../lib/i18n/LocaleProvider';
import type { Locale } from '../lib/i18n/locale';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn() }),
  usePathname: () => '/chat',
}));

const TABLE = '| A | B |\n| - | - |\n| 1 | 2 |';
const inLocale = (locale: Locale, ui: React.ReactElement) =>
  render(<LocaleProvider initialLocale={locale} canSwitch={false}>{ui}</LocaleProvider>);

describe.each([
  ['es', 'Tabla', 'Sección', 'Mundial'],
  ['en', 'Table', 'Section', 'World Cup'],
] as const)('accessible names (%s)', (locale, table, section, worldCup) => {
  test('a table in an answer is a region named in the language', () => {
    const { getByRole } = inLocale(locale, <MarkdownLite text={TABLE} />);
    expect(getByRole('region', { name: table })).toBeInTheDocument();
  });

  test('the section switcher names itself and its World Cup tab in the language', () => {
    const { getByRole } = inLocale(locale, <SectionSwitcher />);
    expect(getByRole('tablist', { name: section })).toBeInTheDocument();
    expect(getByRole('tab', { name: worldCup })).toBeInTheDocument();
  });
});
