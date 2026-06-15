'use client';

import { SignIn } from '@clerk/nextjs';

export default function LoginPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-bf-bg px-4 text-bf-text">
      <div className="mb-6 text-center">
        <h1 className="font-display text-2xl text-bf-text">FPL Asistente</h1>
        <p className="mt-2 text-sm text-bf-gray">
          Inicia sesión con tu cuenta de Patreon para acceder al chat.
        </p>
      </div>
      <SignIn
        routing="hash"
        withSignUp
        forceRedirectUrl="/post-login"
        signUpForceRedirectUrl="/post-login"
        appearance={{
          variables: {
            colorPrimary: '#FF6A4D',
            colorBackground: '#211F29',
            colorForeground: '#f0f0f0',
            colorMuted: '#33303f',
            colorMutedForeground: '#cfcdd9',
            colorInput: '#1c1a26',
            colorInputForeground: '#f0f0f0',
          },
        }}
      />
    </main>
  );
}
