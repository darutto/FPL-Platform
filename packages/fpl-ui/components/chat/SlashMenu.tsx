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
      className="absolute bottom-full mb-1 left-0 right-0 bg-gray-800 rounded-xl border border-gray-700 overflow-hidden z-10"
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
          className={`w-full text-left px-4 py-2 text-sm flex gap-3 transition-colors ${
            idx === activeIndex
              ? 'bg-gray-700 text-gray-100'
              : 'hover:bg-gray-700/60 text-gray-200'
          }`}
        >
          <span className="text-indigo-400 font-mono w-28 flex-shrink-0">{sc.command}</span>
          <span className="text-gray-400">{sc.label}</span>
        </button>
      ))}
    </div>
  );
}
