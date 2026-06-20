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
import { SLASH_COMMANDS, matchCommands, type SlashCommandLike } from '@/lib/slash-commands';
import SlashMenu, { optionId } from './SlashMenu';

const SLASH_MENU_ID = 'slash-command-listbox';

/** External text insertion (command panel / pitch "Ask AI"). The nonce lets
 *  the same text be re-inserted on consecutive clicks. */
export interface InsertRequest {
  text: string;
  nonce: number;
  /** Command hint shown as the placeholder (e.g. "p.ej. Haaland") so the
   *  user knows to type an argument before sending. */
  placeholder?: string;
}

/** Premium web-search toggle (WC chat). When provided, a globe button sits to
 *  the left of the textarea. Opt-in per shell — FPL doesn't pass it yet. */
export interface WebSearchToggle {
  /** Whether web search is armed for the next send. */
  enabled: boolean;
  /** Flip the armed state. */
  onToggle: () => void;
  /** Whether the user's tier may use web search. When false, the globe is a
   *  disabled tap-to-upgrade affordance (no request is sent). Defaults true
   *  until Clerk supplies the real tier; the backend enforces the gate. */
  available?: boolean;
  /** Upgrade URL opened when an ineligible user taps the disabled globe. */
  upgradeUrl?: string;
}

interface Props {
  onSubmit: (value: string) => void;
  disabled?: boolean;
  /** When set/changed, replaces the input value and focuses the textarea. */
  insert?: InsertRequest | null;
  /** Slash-command registry for the menu. Defaults to the FPL registry. */
  commands?: SlashCommandLike[];
  /** Placeholder shown when no slash command is active. */
  defaultPlaceholder?: string;
  /** Optional premium web-search toggle (WC only). */
  webSearch?: WebSearchToggle;
}

const DEFAULT_PLACEHOLDER = 'Escribe tu pregunta o usa /capitan, /comparar…';
const WEB_SEARCH_PLACEHOLDER =
  'Pregunta lo que sea — buscaré en noticias y fuentes en vivo…';

export default function InputBar({
  onSubmit,
  disabled = false,
  insert = null,
  commands = SLASH_COMMANDS,
  defaultPlaceholder = DEFAULT_PLACEHOLDER,
  webSearch,
}: Props) {
  const [value, setValue] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const [cmdPlaceholder, setCmdPlaceholder] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // External insertion from the command panel / squad pitch.
  useEffect(() => {
    if (insert == null) return;
    setValue(insert.text);
    setActiveIndex(0);
    setCmdPlaceholder(insert.placeholder ?? null);
    textareaRef.current?.focus();
  }, [insert]);

  const menuCommands: SlashCommandLike[] = matchCommands(value, commands);
  const menuOpen = menuCommands.length > 0;
  const activeOptionId = menuOpen ? optionId(menuCommands[activeIndex].command) : undefined;

  const handleSelect = (sc: SlashCommandLike) => {
    setValue(sc.command + ' ');
    setCmdPlaceholder(sc.placeholder ?? null);
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

  const webOn = webSearch?.enabled ?? false;
  const webAvailable = webSearch?.available ?? true;
  const placeholder =
    cmdPlaceholder ?? (webOn ? WEB_SEARCH_PLACEHOLDER : defaultPlaceholder);

  const handleGlobe = () => {
    if (!webSearch || disabled) return;
    if (webAvailable) {
      webSearch.onToggle();
      textareaRef.current?.focus();
    } else if (typeof window !== 'undefined') {
      window.open(
        webSearch.upgradeUrl ?? 'https://www.patreon.com/fpl_asistente',
        '_blank',
        'noopener,noreferrer',
      );
    }
  };

  return (
    <div className="relative">
      <SlashMenu
        id={SLASH_MENU_ID}
        commands={menuCommands}
        activeIndex={activeIndex}
        onSelect={handleSelect}
      />

      {webOn && (
        <div className="mb-1.5 flex items-center gap-1.5 px-1 text-[11px] font-medium text-bf-cyan">
          <GlobeIcon className="opacity-90" />
          Búsqueda web activa · esta consulta usará tu cuota premium
        </div>
      )}

      <div
        className={`flex items-end gap-2 rounded-[14px] px-4 py-3 border transition-colors ${
          webOn
            ? 'bg-bf-cyan/5 border-bf-cyan/50'
            : 'bg-white/5 border-white/10 focus-within:border-bf-turquoise/40'
        }`}
      >
        {webSearch && (
          <button
            type="button"
            onClick={handleGlobe}
            disabled={disabled}
            aria-pressed={webOn}
            aria-label={
              webAvailable
                ? webOn
                  ? 'Desactivar búsqueda web'
                  : 'Activar búsqueda web'
                : 'Búsqueda web (función premium)'
            }
            title={
              webAvailable
                ? 'Buscar en la web (premium)'
                : 'Función premium — hazte mecenas para activarla'
            }
            className={`relative flex-shrink-0 self-center rounded-[10px] p-1.5 border transition-colors disabled:opacity-40 ${
              webOn
                ? 'border-bf-cyan/50 bg-bf-cyan/10 text-bf-cyan'
                : webAvailable
                  ? 'border-white/10 text-bf-gray hover:text-bf-cyan hover:border-bf-cyan/30'
                  : 'border-white/10 text-bf-gray/50'
            }`}
          >
            <GlobeIcon />
            {!webAvailable && (
              // Locked badge — premium feature, not available on this tier.
              // Visible without hover (mobile has no tooltip); tap → upgrade.
              <span className="absolute -top-1 -right-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-bf-coral text-bf-ink">
                <LockIcon />
              </span>
            )}
          </button>
        )}
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

function GlobeIcon({ className }: { className?: string }) {
  return (
    <svg
      width={16}
      height={16}
      viewBox="0 0 22 22"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <circle cx="11" cy="11" r="8" stroke="currentColor" strokeWidth="1.6" />
      <path
        d="M3 11h16M11 3c2.5 2.5 4 5.5 4 8s-1.5 5.5-4 8c-2.5-2.5-4-5.5-4-8s1.5-5.5 4-8z"
        stroke="currentColor"
        strokeWidth="1.4"
      />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg width={8} height={8} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="5" y="11" width="14" height="9" rx="2" fill="currentColor" />
      <path
        d="M8 11V8a4 4 0 0 1 8 0v3"
        stroke="currentColor"
        strokeWidth="2.4"
        fill="none"
      />
    </svg>
  );
}
