const PATREON_URL = 'https://www.patreon.com/benditofantasy';

export default function SubscribePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-bf-bg px-4 text-bf-text">
      <div className="w-full max-w-sm rounded-card bg-bf-card p-8 text-center shadow-card">
        <h1 className="font-display text-2xl text-bf-text">Acceso para suscriptores</h1>
        <p className="mt-2 text-sm text-bf-gray">
          FPL Asistente está disponible para suscriptores de Patreon. Únete para
          desbloquear el chat.
        </p>
        <a
          href={PATREON_URL}
          target="_blank"
          rel="noreferrer"
          className="mt-6 inline-block w-full rounded-card bg-bf-coral px-4 py-3 font-semibold text-bf-ink transition hover:bg-bf-coral-soft"
        >
          Hacerme suscriptor
        </a>
        <p className="mt-4 text-xs text-bf-gray">
          ¿Ya eres suscriptor?{' '}
          <a href="/login" className="text-bf-cyan underline">
            Inicia sesión de nuevo
          </a>
          .
        </p>
      </div>
    </main>
  );
}
