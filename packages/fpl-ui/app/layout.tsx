import type { Metadata } from 'next';
import { Barlow, Archivo_Black } from 'next/font/google';
import { ClerkProvider } from '@clerk/nextjs';
import { LocaleProvider } from '@/lib/i18n/LocaleProvider';
import { translate } from '@/lib/i18n/dictionary';
import { getRequestLocale } from '@/lib/i18n/server';
import './globals.css';

// Brand typography (Stitch FPL Chat Hi-Fi): Barlow for UI text,
// Archivo Black for hero numerals. Both served via next/font — no CLS.
const barlow = Barlow({
  subsets: ['latin'],
  weight: ['300', '400', '500', '600', '700', '800', '900'],
  display: 'swap',
  variable: '--font-barlow',
});

const archivoBlack = Archivo_Black({
  subsets: ['latin'],
  weight: '400',
  display: 'swap',
  variable: '--font-archivo-black',
});

export async function generateMetadata(): Promise<Metadata> {
  const { locale } = await getRequestLocale();
  return { title: translate(locale, 'app.title'), description: translate(locale, 'app.description') };
}

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { locale, canSwitch } = await getRequestLocale();
  return (
    <ClerkProvider afterSignOutUrl="/login">
      <html lang={locale} className={`${barlow.variable} ${archivoBlack.variable}`}>
        {/* suppressHydrationWarning: browser extensions (Grammarly, etc.) inject
            data-* attributes on <body> before hydration — harmless false positive. */}
        <body className="bg-bf-bg text-bf-text antialiased font-sans" suppressHydrationWarning>
          <LocaleProvider initialLocale={locale} canSwitch={canSwitch}>{children}</LocaleProvider>
        </body>
      </html>
    </ClerkProvider>
  );
}
