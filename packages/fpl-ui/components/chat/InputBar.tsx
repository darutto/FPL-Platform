'use client';

/**
 * InputBar — text input with send button and slash-command menu.
 *
 * The SlashMenu opens when the user types / and filters as they type the
 * command prefix. Keyboard navigation:
 *   ArrowDown / ArrowUp — move active item
 *   Enter               — select active item (or submit when menu is closed)
 *   Escape              — close menu
 *
 * After selecting a command the placeholder updates to the command's hint
 * text (e.g. "p.ej. Haaland") until the user finishes typing and sends.
 *
 * Plain text submission is unchanged — no slash prefix = no menu, no hint.
 */
import { useState, useRef, useEffect, type KeyboardEvent } from 'react';
import { matchSlashCommands, type SlashCommand } from '@/lib/slash-commands';
import SlashMenu, { optionId } from './SlashMenu';

const SLASH_MENU_ID = 'slash-command-listbox';

/** External text insertion (command panel / pitch "Ask AI"). The nonce lets
 *  the same text be re-inserted on consecutive clicks. */
export interface InsertRequest {
  text: string;
  nonce: number;
}

interface Props {
  onSubmit: (value: string) => void;
  disabled?: boolean;
  /** When set/changed, replaces the input value and focuses the textarea. */
  insert?: InsertRequest | null;
}

const DEFAULT_PLACEHOLDER = 'Escribe tu pregunta o usa /capitan, /comparar…';

export default function InputBar({ onSubmit, disabled = false, insert = null }: Props) {
  const [value, setValue] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const [cmdPlaceholder, setCmdPlaceholder] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // External insertion from the command panel / squad pitch.
  useEffect(() => {
    if (insert == null) return;
    setValue(insert.text);
    setActiveIndex(0);
    setCmdPlaceholder(null);
    textareaRef.current?.focus();
  }, [insert]);

  const menuCommands: SlashCommand[] = matchSlashCommands(value);
  const menuOpen = menuCommands.length > 0;
  const activeOptionId = menuOpen ? optionId(menuCommands[activeIndex].command) : undefined;

  const handleSelect = (sc: SlashCommand) => {
    setValue(sc.command + ' ');
    setCmdPlaceholder(sc.placeholder);
    setActiveIndex(0);
    // Return focus to the textarea so the user can type the argument
    textareaRef.current?.focus();
  };

  const handleChange = (next: string) => {
    setValue(next);
    setActiveIndex(0);
    // Clear command placeholder once the user types past any slash-command prefix
    if (!next.startsWith('/')) {
      setCmdPlaceholder(null);
    }
  };

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed);
    setValue('');
    setCmdPlaceholder(null);
    setActiveIndex(0);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (menuOpen) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActiveIndex((i) => Math.min(i + 1, menuCommands.length - 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActiveIndex((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSelect(menuCommands[activeIndex]);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        // Close the menu by clearing just the slash prefix
        setValue('');
        setCmdPlaceholder(null);
        setActiveIndex(0);
        return;
      }
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const placeholder = cmdPlaceholder ?? DEFAULT_PLACEHOLDER;

  return (
    <div className="relative">
      <SlashMenu
        id={SLASH_MENU_ID}
        commands={menuCommands}
        activeIndex={activeIndex}
        onSelect={handleSelect}
      />

      <div className="flex items-end gap-2 bg-white/5 rounded-[14px] px-4 py-3 border border-white/10 focus-within:border-bf-turquoise/40 transition-colors">
        <textarea
          ref={textareaRef}
          className="flex-1 bg-transparent resize-none text-sm text-bf-text placeholder-bf-gray/60 outline-none max-h-32"
          rows={1}
          placeholder={placeholder}
          value={value}
          onChange={(e) => handleChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          aria-label="Pregunta al asistente FPL"
          aria-haspopup="listbox"
          aria-expanded={menuOpen}
          aria-controls={menuOpen ? SLASH_MENU_ID : undefined}
          aria-activedescendant={activeOptionId}
        />
        <button
          onClick={submit}
          disabled={disabled || !value.trim()}
          className="flex-shrink-0 bg-bf-coral hover:bg-bf-coral/90 disabled:bg-white/10 disabled:text-bf-gray text-white hc:text-bf-ink text-sm font-bold rounded-[10px] px-3.5 py-1.5 transition-colors"
          aria-label="Enviar"
        >
          Enviar
        </button>
      </div>
    </div>
  );
}
