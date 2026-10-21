'use client';

/**
 * CommandPanel — quick-commands screen (U2, Stitch Hi-Fi "Commands").
 *
 * Two stacked sections:
 *   - Vistas rápidas (@resources): complete queries with no argument —
 *     clicking sends immediately and jumps to the chat screen.
 *   - Acciones (/commands): click inserts "/comando " into the input; the
 *     existing SlashMenu/parseSlashCommand machinery takes over from there
 *     (these need an argument before sending, so no auto-send).
 *
 * Slash entries come from the lib/slash-commands registry (single source);
 * this panel only adds the friendly label/description/icon presentation.
 */
import { SLASH_COMMANDS } from '@/lib/slash-commands';
import { ACCENT_HEX, type Accent } from '@/lib/theme';
import {
  IconCaptain,
  IconCompare,
  IconTransfer,
  IconFixtures,
  IconDiff,
  IconChip,
  IconRanking,
  IconInjury,
  IconForm,
  IconXG,
  IconPoints,
  IconMinutes,
  IconPopular,
} from './CommandIcons';

type IconComponent = (props: { color: string }) => React.ReactNode;

interface PanelCommand {
  /** Text inserted into the chat input (trailing space added for / commands) */
  insert: string;
  label: string;
  desc: string;
  Icon: IconComponent;
  accent: Accent;
  /** Argument hint (e.g. "p.ej. Haaland") shown as the input placeholder
   *  after insertion — / commands need an argument before sending. */
  placeholder?: string;
  /** Complete query, no argument needed — send immediately on click. */
  autoSend?: boolean;
}

// @ vistas rápidas — Spanish aliases supported by the backend resource router.
const AT_COMMANDS: PanelCommand[] = [
  { insert: '@lesionados', label: 'Lesionados', desc: 'Lista actualizada', Icon: IconInjury, accent: 'coralSoft', autoSend: true },
  { insert: '@forma', label: 'En racha', desc: 'Mejor forma reciente', Icon: IconForm, accent: 'gold', autoSend: true },
  { insert: '@xg', label: 'Peligro de gol', desc: 'Líderes xG + xA por 90', Icon: IconXG, accent: 'coral', autoSend: true },
  { insert: '@puntos', label: 'Más puntos', desc: 'Acumulados temporada', Icon: IconPoints, accent: 'turquoise', autoSend: true },
  { insert: '@minutos', label: 'Los infaltables', desc: 'Más minutos jugados', Icon: IconMinutes, accent: 'cyan', autoSend: true },
  { insert: '@populares', label: 'Más comprados', desc: 'Mayor ownership', Icon: IconPopular, accent: 'purple', autoSend: true },
];

// Presentation for each registry command (friendly question as the label).
const SLASH_PRESENTATION: Record<string, { label: string; desc: string; Icon: IconComponent; accent: Accent }> = {
  '/capitan': { label: '¿A quién le doy la cinta?', desc: 'Recomendación de capitán', Icon: IconCaptain, accent: 'turquoise' },
  '/comparar': { label: 'Comparar 2 jugadores', desc: 'Análisis side-by-side', Icon: IconCompare, accent: 'cyan' },
  '/transferencia': { label: 'Sugerir fichaje', desc: '¿Vale la pena el cambio?', Icon: IconTransfer, accent: 'gold' },
  '/calendarios': { label: 'Fixture de jugador', desc: 'Dificultad próximos partidos', Icon: IconFixtures, accent: 'turquoise' },
  '/diferenciales': { label: 'Buscar joyas ocultas', desc: 'Baja propiedad, alto potencial', Icon: IconDiff, accent: 'coralSoft' },
  '/chips': { label: '¿Uso un chip?', desc: 'Triple Cap, WC, BB o FH', Icon: IconChip, accent: 'purple' },
  '/clasificacion': { label: 'Top capitanes de la semana', desc: 'Ranking de la jornada', Icon: IconRanking, accent: 'gold' },
};

const SLASH_PANEL_COMMANDS: PanelCommand[] = SLASH_COMMANDS.map((sc) => {
  const p = SLASH_PRESENTATION[sc.command];
  return {
    insert: `${sc.command} `,
    label: p?.label ?? sc.label,
    desc: p?.desc ?? sc.placeholder,
    Icon: p?.Icon ?? IconCaptain,
    accent: p?.accent ?? 'turquoise',
    placeholder: sc.placeholder,
  };
});

interface Props {
  /** Called with the text to drop into the chat input, plus an optional
   *  argument-hint placeholder for bare slash commands. */
  onInsert: (text: string, placeholder?: string) => void;
  /** Called for autoSend commands — sends immediately, no editing step. */
  onSend: (text: string) => void;
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

function CommandRow({ cmd, onInsert, onSend }: { cmd: PanelCommand; onInsert: (text: string, placeholder?: string) => void; onSend: (text: string) => void }) {
  return (
    <button
      onClick={() => (cmd.autoSend ? onSend(cmd.insert) : onInsert(cmd.insert, cmd.placeholder))}
      className="group w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left border border-transparent hover:border-white/15 hover:bg-white/5 transition-colors"
    >
      <span className="flex items-center justify-center w-7 h-7 rounded-md bg-white/5 border border-white/10 flex-shrink-0">
        <cmd.Icon color={ACCENT_HEX[cmd.accent]} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-xs font-bold text-bf-text/90 group-hover:text-white truncate leading-tight">
          {cmd.label}
        </span>
        <span className="block text-[10px] text-bf-gray truncate leading-tight mt-0.5">
          {cmd.desc}
        </span>
      </span>
      <span className="text-sm text-transparent group-hover:text-bf-gray transition-colors flex-shrink-0">
        ›
      </span>
    </button>
  );
}

export default function CommandPanel({ onInsert, onSend }: Props) {
  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="px-4 py-3 border-b border-white/10 flex-shrink-0 bg-black/25">
        <span className="text-[10px] font-bold uppercase tracking-widest text-bf-text/50">
          Comandos rápidos
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-2.5">
        <SectionHeading>Vistas rápidas</SectionHeading>
        <div className="flex flex-col gap-0.5 mb-3">
          {AT_COMMANDS.map((cmd) => (
            <CommandRow key={cmd.insert} cmd={cmd} onInsert={onInsert} onSend={onSend} />
          ))}
        </div>

        <SectionHeading>Acciones</SectionHeading>
        <div className="flex flex-col gap-0.5">
          {SLASH_PANEL_COMMANDS.map((cmd) => (
            <CommandRow key={cmd.insert} cmd={cmd} onInsert={onInsert} onSend={onSend} />
          ))}
        </div>
      </div>
    </div>
  );
}
