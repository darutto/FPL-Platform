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
import { slashCommandsFor } from '@/lib/slash-commands';
import { useLocale, useT } from '@/lib/i18n/LocaleProvider';
import type { DictKey } from '@/lib/i18n/dictionary';
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

// @ quick views: the resource router accepts both spellings; the panel inserts the one in the language showing.
type AtId = 'injuries' | 'form' | 'xg' | 'points' | 'minutes' | 'popular';
const AT_COMMANDS: Array<{ id: AtId; Icon: IconComponent; accent: Accent }> = [
  { id: 'injuries', Icon: IconInjury, accent: 'coralSoft' },
  { id: 'form', Icon: IconForm, accent: 'gold' },
  { id: 'xg', Icon: IconXG, accent: 'coral' },
  { id: 'points', Icon: IconPoints, accent: 'turquoise' },
  { id: 'minutes', Icon: IconMinutes, accent: 'cyan' },
  { id: 'popular', Icon: IconPopular, accent: 'purple' },
];

// Presentation for each registry command (friendly question as the label), keyed by the Spanish slug.
const SLASH_PRESENTATION: Record<string, { Icon: IconComponent; accent: Accent }> = {
  capitan: { Icon: IconCaptain, accent: 'turquoise' },
  comparar: { Icon: IconCompare, accent: 'cyan' },
  transferencia: { Icon: IconTransfer, accent: 'gold' },
  calendarios: { Icon: IconFixtures, accent: 'turquoise' },
  diferenciales: { Icon: IconDiff, accent: 'coralSoft' },
  chips: { Icon: IconChip, accent: 'purple' },
  clasificacion: { Icon: IconRanking, accent: 'gold' },
};

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
  const { locale } = useLocale();
  const t = useT();
  const atCommands: PanelCommand[] = AT_COMMANDS.map(({ id, Icon, accent }) => ({
    insert: t(`panel.at.${id}.command` as DictKey),
    label: t(`panel.at.${id}.label` as DictKey),
    desc: t(`panel.at.${id}.desc` as DictKey),
    Icon,
    accent,
    autoSend: true,
  }));
  const slashCommands: PanelCommand[] = slashCommandsFor(locale).map((sc, index) => {
    // The registry's order is the Spanish one; the slug identifies the command in both languages.
    const slug = slashCommandsFor('es')[index].command.slice(1);
    const p = SLASH_PRESENTATION[slug];
    return {
      insert: `${sc.command} `,
      label: t(`panel.slash.${slug}.label` as DictKey),
      desc: t(`panel.slash.${slug}.desc` as DictKey),
      Icon: p?.Icon ?? IconCaptain,
      accent: p?.accent ?? 'turquoise',
      placeholder: sc.placeholder,
    };
  });
  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="px-4 py-3 border-b border-white/10 flex-shrink-0 bg-black/25">
        <span className="text-[10px] font-bold uppercase tracking-widest text-bf-text/50">
          {t('panel.title')}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-2.5">
        <SectionHeading>{t('panel.quickViews')}</SectionHeading>
        <div className="flex flex-col gap-0.5 mb-3">
          {atCommands.map((cmd) => (
            <CommandRow key={cmd.insert} cmd={cmd} onInsert={onInsert} onSend={onSend} />
          ))}
        </div>

        <SectionHeading>{t('panel.actions')}</SectionHeading>
        <div className="flex flex-col gap-0.5">
          {slashCommands.map((cmd) => (
            <CommandRow key={cmd.insert} cmd={cmd} onInsert={onInsert} onSend={onSend} />
          ))}
        </div>
      </div>
    </div>
  );
}
