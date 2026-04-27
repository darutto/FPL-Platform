/**
 * Slash command registry — Spanish-first (V2 Phase 1).
 *
 * Each command maps to an intent_hint value from INTENT_HINT_ALLOWLIST.
 * When a slash command is selected, the UI:
 *   1. Strips the command prefix from the question text.
 *   2. Attaches intent_hint to the POST /ask request body.
 *
 * Backend invariant: intent_hint fires only when the deterministic router
 * misses. If the text question is already routable, the hint is ignored.
 * Invalid hint values are silently dropped — no error raised.
 *
 * Adding aliases or additional languages: add entries to SLASH_COMMANDS.
 * The intent_hint values must remain in INTENT_HINT_ALLOWLIST.
 *
 * SlashMenu dropdown: implemented in Phase 2g (components/chat/SlashMenu.tsx).
 */
import { INTENT_HINT_ALLOWLIST, type IntentHint } from './types';

export interface SlashCommand {
  /** The slash prefix, e.g. "/capitan" */
  command: string;
  /** Display label shown in the slash menu */
  label: string;
  /** intent_hint value sent to the backend */
  intent_hint: IntentHint;
  /** Input placeholder shown after selecting the command */
  placeholder: string;
}

/**
 * Spanish-first slash command registry.
 * Configurable: add or reorder entries without changing other code.
 */
export const SLASH_COMMANDS: SlashCommand[] = [
  {
    command: '/capitan',
    label: 'Capitán',
    intent_hint: 'captain_score',
    placeholder: 'p.ej. Haaland',
  },
  {
    command: '/comparar',
    label: 'Comparar jugadores',
    intent_hint: 'compare_players',
    placeholder: 'p.ej. Salah vs De Bruyne',
  },
  {
    command: '/transferencia',
    label: 'Consejo de transferencia',
    intent_hint: 'transfer_advice',
    placeholder: 'p.ej. Palmer por Gordon',
  },
  {
    command: '/calendarios',
    label: 'Calendario de partidos',
    intent_hint: 'player_fixture_run',
    placeholder: 'p.ej. Mbappé',
  },
  {
    command: '/diferenciales',
    label: 'Diferenciales',
    intent_hint: 'differential_picks',
    placeholder: 'p.ej. menos del 10%',
  },
  {
    command: '/chips',
    label: 'Uso de chips',
    intent_hint: 'chip_advice',
    placeholder: 'p.ej. triple capitán',
  },
];

// Validate at module load: all registered commands use allowlisted hints.
// This catches misconfiguration at startup rather than at runtime.
for (const sc of SLASH_COMMANDS) {
  if (!(INTENT_HINT_ALLOWLIST as readonly string[]).includes(sc.intent_hint)) {
    throw new Error(
      `Slash command "${sc.command}" uses unlisted intent_hint "${sc.intent_hint}". ` +
        `Allowed: ${INTENT_HINT_ALLOWLIST.join(', ')}`,
    );
  }
}

/**
 * Return commands whose prefix matches the current input.
 * Returns [] when input doesn't start with '/'.
 */
export function matchSlashCommands(input: string): SlashCommand[] {
  if (!input.startsWith('/')) return [];
  const query = input.toLowerCase();
  return SLASH_COMMANDS.filter((sc) => sc.command.startsWith(query));
}

/**
 * Parse a slash-command-prefixed input string.
 *
 * "/capitan Haaland" → { intent_hint: "captain_score", question: "Haaland" }
 * "should I captain Haaland" → null (no slash prefix)
 *
 * The question is passed as-is to the backend. The backend deterministic
 * router may succeed on its own — in that case intent_hint is ignored.
 */
export function parseSlashCommand(
  input: string,
): { intent_hint: IntentHint; question: string } | null {
  const lower = input.toLowerCase();
  for (const sc of SLASH_COMMANDS) {
    if (lower.startsWith(sc.command)) {
      const question = input.slice(sc.command.length).trim();
      return { intent_hint: sc.intent_hint, question };
    }
  }
  return null;
}
