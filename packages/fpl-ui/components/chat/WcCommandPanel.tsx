'use client';

/**
 * WcCommandPanel — quick-commands screen for the World Cup chat (Iteration 2).
 *
 * Single "Preguntas rápidas" section built from WC_SLASH_COMMANDS — click
 * inserts "/comando " into the chat input (same insert-not-send pattern as
 * CommandPanel). The existing SlashMenu/InputBar machinery (now generic over
 * SlashCommandLike) takes over from there.
 */
import { WC_SLASH_COMMANDS } from '@/lib/wc-slash-commands';
import { ACCENT_HEX, type Accent } from '@/lib/theme';
import {
  IconCaptain,
  IconCompare,
  IconFixtures,
  IconRanking,
  IconPoints,
  IconXG,
  IconMinutes,
  IconDiff,
} from './CommandIcons';

type IconComponent = (props: { color: string }) => React.ReactNode;

const PRESENTATION: Record<string, { Icon: IconComponent; accent: Accent }> = {
  '/jugador': { Icon: IconCaptain, accent: 'turquoise' },
  '/comparar': { Icon: IconCompare, accent: 'cyan' },
  '/partidos': { Icon: IconFixtures, accent: 'turquoise' },
  '/clasificacion': { Icon: IconRanking, accent: 'gold' },
  '/brackets': { Icon: IconDiff, accent: 'cyan' },
  '/goleadores': { Icon: IconPoints, accent: 'coral' },
  '/fantasy': { Icon: IconXG, accent: 'purple' },
  '/plantilla': { Icon: IconMinutes, accent: 'coralSoft' },
  '/enfrentamientos': { Icon: IconDiff, accent: 'gray' },
  '/historial': { Icon: IconMinutes, accent: 'coral' },
};

interface Props {
  /** Called with the text to drop into the chat input, plus an optional
   *  argument-hint placeholder for bare slash commands. */
  onInsert: (text: string, placeholder?: string) => void;
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 px-2 pb-1.5 pt-1">
      <span className="text-[10px] font-extrabold text-bf-text/60 uppercase tracking-widest">
        {children}
      </span>
      <div className="flex-1 h-px bg-white/10" />
    </div>
  );
}

export default function WcCommandPanel({ onInsert }: Props) {
  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="px-4 py-3 border-b border-white/10 flex-shrink-0 bg-black/25">
        <span className="text-[10px] font-bold uppercase tracking-widest text-bf-text/50">
          Comandos rápidos
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-2.5">
        <SectionHeading>Preguntas rápidas</SectionHeading>
        <div className="flex flex-col gap-0.5">
          {WC_SLASH_COMMANDS.map((cmd) => {
            const p = PRESENTATION[cmd.command] ?? { Icon: IconCaptain, accent: 'turquoise' as Accent };
            return (
              <button
                key={cmd.command}
                onClick={() => onInsert(`${cmd.command} `, cmd.placeholder)}
                className="group w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left border border-transparent hover:border-white/15 hover:bg-white/5 transition-colors"
              >
                <span className="flex items-center justify-center w-7 h-7 rounded-md bg-white/5 border border-white/10 flex-shrink-0">
                  <p.Icon color={ACCENT_HEX[p.accent]} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-xs font-bold text-bf-text/90 group-hover:text-white truncate leading-tight">
                    {cmd.label}
                  </span>
                  <span className="block text-[10px] text-bf-gray truncate leading-tight mt-0.5">
                    {cmd.command} — {cmd.placeholder}
                  </span>
                </span>
                <span className="text-sm text-transparent group-hover:text-bf-gray transition-colors flex-shrink-0">
                  ›
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
