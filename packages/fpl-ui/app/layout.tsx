import type { Metadata } from 'next';
import { Barlow, Archivo_Black } from 'next/font/google';
import { ClerkProvider } from '@clerk/nextjs';
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

export const metadata: Metadata = {
  title: 'FPL Asistente',
  description: 'Asistente de Fantasy Premier League',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ClerkProvider afterSignOutUrl="/login">
      <html lang="es" className={`${barlow.variable} ${archivoBlack.variable}`}>
        {/* suppressHydrationWarning: browser extensions (Grammarly, etc.) inject
            data-* attributes on <body> before hydration — harmless false positive. */}
        <body className="bg-bf-bg text-bf-text antialiased font-sans" suppressHydrationWarning>{children}</body>
      </html>
    </ClerkProvider>
  );
}
