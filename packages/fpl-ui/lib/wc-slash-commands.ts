/**
 * World Cup slash command registry — Spanish-first (Iteration 2 UI).
 *
 * Unlike the FPL registry (lib/slash-commands.ts), the WC backend has no
 * deterministic intent router — the LLM orchestrator picks tools for every
 * turn. So WC slash commands don't carry an intent_hint; instead each one
 * expands to a natural-language Spanish question that biases the
 * orchestrator toward the right tool (get_squad, get_head_to_head, etc.).
 *
 * Each command:
 *   1. Strips the command prefix + leading space from the input.
 *   2. Builds a full Spanish question via buildQuestion(arg).
 *   3. Sends that question as plain text to POST /ask (no intent_hint).
 *
 * Adding commands: add an entry to WC_SLASH_COMMANDS. No allowlist to
 * maintain — any Spanish phrasing the orchestrator can route is valid.
 */
import { matchCommands, type SlashCommandLike } from './slash-commands';

export interface WcSlashCommand extends SlashCommandLike {
  placeholder: string;
  /** Builds the natural-language question sent to the WC backend.
   *  `arg` is the trimmed text after the command prefix (may be empty). */
  buildQuestion: (arg: string) => string;
}

/**
 * Spanish-first WC slash command registry.
 * Configurable: add or reorder entries without changing other code.
 */
export const WC_SLASH_COMMANDS: WcSlashCommand[] = [
  {
    command: '/jugador',
    label: 'Información de jugador',
    placeholder: 'p.ej. Mbappé',
    buildQuestion: (arg) => arg
      ? `Dame información sobre el jugador ${arg}.`
      : '¿Qué información tienes sobre un jugador?',
  },
  {
    command: '/comparar',
    label: 'Comparar jugadores',
    placeholder: 'p.ej. Mbappé vs Haaland',
    buildQuestion: (arg) => arg
      ? `Compara a ${arg}.`
      : 'Compara dos jugadores del Mundial.',
  },
  {
    command: '/partidos',
    label: 'Partidos y resultados',
    placeholder: 'p.ej. España',
    buildQuestion: (arg) => arg
      ? `¿Cuáles son los partidos de ${arg} en este Mundial?`
      : '¿Qué partidos hay hoy en el Mundial?',
  },
  {
    command: '/clasificacion',
    label: 'Clasificación de grupo',
    placeholder: 'p.ej. grupo A',
    buildQuestion: (arg) => arg
      ? `¿Cómo está la clasificación del ${arg}?`
      : '¿Cómo está la clasificación general por grupos?',
  },
  {
    command: '/goleadores',
    label: 'Máximos goleadores',
    placeholder: '(sin argumento)',
    buildQuestion: () => '¿Quiénes son los máximos goleadores del torneo?',
  },
  {
    command: '/asistencias',
    label: 'Máximos asistidores',
    placeholder: '(sin argumento)',
    buildQuestion: () => '¿Quiénes son los máximos asistidores del torneo?',
  },
  {
    command: '/fantasy',
    label: 'Puntos de fantasy',
    placeholder: 'p.ej. delanteros (opcional)',
    buildQuestion: (arg) => arg
      ? `¿Quiénes son los jugadores con más puntos de fantasy entre los ${arg}?`
      : '¿Qué jugadores han hecho más puntos de fantasy en el torneo?',
  },
  {
    command: '/plantilla',
    label: 'Plantilla de selección',
    placeholder: 'p.ej. Argentina',
    buildQuestion: (arg) => arg
      ? `Muéstrame la plantilla de ${arg}.`
      : 'Muéstrame la plantilla de una selección.',
  },
  {
    command: '/enfrentamientos',
    label: 'Enfrentamientos directos',
    placeholder: 'p.ej. México vs Argentina',
    buildQuestion: (arg) => arg
      ? `¿Cuál es el historial entre ${arg} en este Mundial?`
      : '¿Cuál es el historial entre dos selecciones en este Mundial?',
  },
  {
    command: '/historial',
    label: 'Historial Mundial 2022',
    placeholder: 'p.ej. Argentina',
    buildQuestion: (arg) => arg
      ? `¿Cómo le fue a ${arg} en el Mundial 2022?`
      : '¿Qué pasó en el Mundial de 2022?',
  },
];

/**
 * Return WC commands whose prefix matches the current input.
 * Returns [] when input doesn't start with '/'.
 */
export function matchWcSlashCommands(input: string): WcSlashCommand[] {
  return matchCommands(input, WC_SLASH_COMMANDS);
}

/**
 * Parse a WC slash-command-prefixed input string into a full Spanish
 * question for the orchestrator.
 *
 * "/clasificacion grupo A" → "¿Cómo está la clasificación del grupo A?"
 * "¿cómo va el grupo A?"   → null (no slash prefix — sent as-is)
 */
export function parseWcSlashCommand(input: string): { question: string } | null {
  const lower = input.toLowerCase();
  for (const sc of WC_SLASH_COMMANDS) {
    if (lower.startsWith(sc.command)) {
      const arg = input.slice(sc.command.length).trim();
      return { question: sc.buildQuestion(arg) };
    }
  }
  return null;
}
