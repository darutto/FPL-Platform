'use client';

/**
 * SlashMenu — dropdown for the slash-command registry.
 *
 * Purely presentational: receives filtered commands and an activeIndex from
 * InputBar, which owns textarea focus and keyboard state.
 *
 * Renders null when commands is empty.
 *
 * Keyboard navigation (ArrowUp/ArrowDown/Enter/Escape) is handled by InputBar
 * so the textarea never loses focus while the menu is open.
 */
import type { SlashCommand } from '@/lib/slash-commands';

interface Props {
  commands: SlashCommand[];
  activeIndex: number;
  onSelect: (command: SlashCommand) => void;
  id?: string;
}

/** Stable DOM id for a listbox option, derived from the command slug. */
export function optionId(command: string): string {
  return `slash-option-${command.slice(1)}`;
}

export default function SlashMenu({ commands, activeIndex, onSelect, id }: Props) {
  if (commands.length === 0) return null;

  return (
    <div
      id={id}
      role="listbox"
      aria-label="Comandos de barra"
      className="absolute bottom-full mb-1.5 left-0 right-0 bg-bf-surface rounded-card border border-bf-turquoise/25 overflow-hidden z-10 shadow-menu"
    >
      {commands.map((sc, idx) => (
        <button
          key={sc.command}
          id={optionId(sc.command)}
          role="option"
          aria-selected={idx === activeIndex}
          onMouseDown={(e) => {
            // Prevent textarea blur before the click registers
            e.preventDefault();
            onSelect(sc);
          }}
          className={`w-full text-left px-4 py-2 text-sm flex gap-3 transition-colors border-b border-white/5 last:border-b-0 ${
            idx === activeIndex
              ? 'bg-bf-turquoise/10 text-bf-text'
              : 'hover:bg-white/5 text-bf-text/80'
          }`}
        >
          <span className="text-bf-turquoise font-mono font-bold w-28 flex-shrink-0">{sc.command}</span>
          <span className="text-bf-gray">{sc.label}</span>
        </button>
      ))}
    </div>
  );
}
