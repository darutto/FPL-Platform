'use client';

/**
 * StarterPrompts — clickable prompt chips shown on empty chat.
 *
 * The example prompts DO name real players for concreteness, so they must be
 * refreshed when the squad landscape changes (transfers, players leaving the
 * league) — keep every name here a current Premier League player. Clicking
 * populates the question and sends immediately.
 *
 * For slash-command starters, the text includes the command prefix
 * so parseSlashCommand picks up the intent_hint automatically.
 */

const STARTER_PROMPTS = [
  '¿A quién debería dar el brazalete?',
  '/comparar Haaland vs Bruno Fernandes',
  '¿Debería usar el triple capitán?',
  '/diferenciales menos del 10%',
  '/transferencia Cole Palmer por Saka',
  '/calendarios Haaland',
] as const;

interface Props {
  onSelect: (prompt: string) => void;
}

export default function StarterPrompts({ onSelect }: Props) {
  return (
    <div className="flex flex-wrap gap-2 justify-center max-w-lg">
      {STARTER_PROMPTS.map((prompt) => (
        <button
          key={prompt}
          onClick={() => onSelect(prompt)}
          className="text-xs font-bold bg-bf-turquoise/10 hover:bg-bf-turquoise/20 border border-bf-turquoise/40 text-bf-turquoise rounded-full px-3 py-1.5 transition-colors"
        >
          {prompt}
        </button>
      ))}
    </div>
  );
}
