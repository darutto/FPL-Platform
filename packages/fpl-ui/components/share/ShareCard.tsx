'use client';

import type { AskResponse } from '@/lib/types';
import IntentRenderer from '@/components/chat/IntentRenderer';

interface Props {
  question: string;
  response: AskResponse;
  appUrl: string;
  cta: string;
}

export default function ShareCard({ question, response, appUrl, cta }: Props) {
  return (
    <div className="w-[760px] rounded-2xl border border-white/10 bg-gradient-to-br from-bf-surface/95 via-[#1A1A24] to-[#11111A] p-5 text-bf-text shadow-card">
      <div className="flex items-center gap-3 border-b border-white/10 pb-3">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/logo-icon.png" alt="Bendito Fantasy" className="h-8 w-8 rounded" />
        <div className="leading-none">
          <p className="text-[13px] font-extrabold text-white">Club Bendito Fantasy</p>
          <p className="mt-1 text-[11px] text-bf-gray">Respuesta compartida desde el chat</p>
        </div>
      </div>

      <div className="mt-4 rounded-xl border border-bf-cyan/30 bg-bf-cyan/10 px-4 py-3">
        <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-bf-cyan">Pregunta</p>
        <p className="mt-1 text-[14px] font-medium text-white">{question}</p>
      </div>

      <div className="mt-4">
        <IntentRenderer response={response} />
      </div>

      <div className="mt-4 rounded-xl border border-bf-turquoise/30 bg-bf-turquoise/10 px-4 py-3">
        <p className="text-sm font-bold text-bf-turquoise">{cta}</p>
        <p className="mt-1 text-xs text-bf-text/90">{appUrl}</p>
      </div>
    </div>
  );
}
