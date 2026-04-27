'use client';

/**
 * StarterPrompts — clickable prompt chips shown on empty chat.
 *
 * No player names hardcoded — prompts are generic and gameweek-agnostic.
 * Configurable: update STARTER_PROMPTS per gameweek without code changes.
 * Clicking populates the question and sends immediately.
 *
 * For slash-command starters, the text includes the command prefix
 * so parseSlashCommand picks up the intent_hint automatically.
 */

const STARTER_PROMPTS = [
  '¿A quién debería dar el brazalete?',
  '/comparar Haaland vs Salah',
  '¿Debería usar el triple capitán?',
  '/diferenciales menos del 10%',
  '/transferencia Palmer por Saka',
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
          className="text-xs bg-gray-800 hover:bg-gray-700 border border-gray-700 hover:border-gray-600 text-gray-300 rounded-full px-3 py-1.5 transition-colors"
        >
          {prompt}
        </button>
      ))}
    </div>
  );
}
