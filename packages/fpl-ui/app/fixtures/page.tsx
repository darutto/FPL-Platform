'use client';

/**
 * /fixtures — standalone, PUBLIC fixture ticker (Track D / FI7).
 *
 * The browse-first surface of the two-surface model: scan the whole league's
 * fixture outlook with zero tokens, then deep-link into chat to go deeper on a
 * team or a single fixture. Outside the Clerk gate (middleware only protects
 * /chat and /wc). The board itself (controls, detailed/compact views, data
 * seam) lives in FixturesBoard, shared with the in-app Calendario pager tab.
 *
 * Off-season: FixturesBoard renders deterministic mock data; swap the seam for
 * a live get_fixture_outlook fetch once the FPL API rolls over.
 */
import { useRouter } from 'next/navigation';
import { FixturesBoard } from '@/components/intents/FixturesBoard';

export default function FixturesPage() {
  const router = useRouter();
  // Deep-link into chat: /chat reads ?q= on mount and prefills the composer.
  const onAsk = (question: string) =>
    router.push(`/chat?q=${encodeURIComponent(question)}`);

  return (
    <div className="min-h-[100dvh] bg-bf-ink text-white px-4 py-8">
      <div className="max-w-[960px] mx-auto space-y-5">
        <header className="space-y-1">
          <h1 className="text-2xl font-extrabold">
            Calendario<span className="text-bf-turquoise">.</span>
          </h1>
          <p className="text-sm text-bf-gray">
            Dificultad de dos ejes con detección de rachas. Toca un equipo o una
            jornada para profundizar en el chat.
          </p>
        </header>

        <FixturesBoard onAsk={onAsk} />

        <p className="text-[11px] leading-snug text-bf-gray/60">
          Datos de ejemplo (pretemporada): la API de FPL aún no publica la nueva
          campaña. En cuanto se active, esta página mostrará el calendario real
          sin cambios de código.
        </p>
      </div>
    </div>
  );
}
