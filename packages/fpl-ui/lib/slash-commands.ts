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
import { translate, type DictKey } from './i18n/dictionary';
import type { Locale } from './i18n/locale';

/**
 * Minimal shape needed by SlashMenu/InputBar — domain-agnostic.
 * FPL's SlashCommand (with intent_hint) and WC's WcSlashCommand both
 * satisfy this structurally, so the input/menu components can be shared.
 */
export interface SlashCommandLike {
  /** The slash prefix, e.g. "/capitan" */
  command: string;
  /** Display label shown in the slash menu */
  label: string;
  /** Input placeholder shown after selecting the command */
  placeholder?: string;
}

export interface SlashCommand extends SlashCommandLike {
  /** intent_hint value sent to the backend */
  intent_hint: IntentHint;
  placeholder: string;
}

/**
 * Return commands whose prefix matches the current input.
 * Generic over any SlashCommandLike[] so WC's registry can reuse this.
 * Returns [] when input doesn't start with '/'.
 */
export function matchCommands<T extends SlashCommandLike>(input: string, commands: readonly T[]): T[] {
  if (!input.startsWith('/')) return [];
  const query = input.toLowerCase();
  return commands.filter((sc) => sc.command.startsWith(query));
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
  {
    command: '/clasificacion',
    label: 'Top capitanes de la semana',
    intent_hint: 'rank_candidates',
    placeholder: 'p.ej. Haaland, Salah, Palmer',
  },
  // NOTE: /calendario (singular, fixture_outlook ticker) was removed from the
  // quick-command list — it only ever worked through the legacy intent_hint
  // pre-processing shim (it has no entry in the backend's real prompt
  // registry, unlike the other seven commands here), and a dedicated
  // Calendario tab already covers this need in the swipe pager. Removing it
  // avoids maintaining a second, redundant path to the same feature.
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
 * The registry in the language being shown. Spanish is SLASH_COMMANDS itself, untouched;
 * English keeps each command's intent_hint and swaps in the canonical English name, label
 * and argument hint (lib/i18n/en.ts, per docs/i18n-glossary.md). The backend accepts both
 * spellings of every command.
 */
export function slashCommandsFor(locale: Locale): SlashCommand[] {
  if (locale === 'es') return SLASH_COMMANDS;
  return SLASH_COMMANDS.map((sc) => {
    const slug = sc.command.slice(1);
    return {
      ...sc,
      command: translate(locale, `slash.${slug}.command` as DictKey),
      label: translate(locale, `slash.${slug}.label` as DictKey),
      placeholder: translate(locale, `slash.${slug}.placeholder` as DictKey),
    };
  });
}

/**
 * Return commands whose prefix matches the current input.
 * Returns [] when input doesn't start with '/'.
 *
 * In English the English names are offered first; a Spanish prefix that matches no English
 * name ("/capi") still finds the Spanish command, so typing either language works.
 */
export function matchSlashCommands(input: string, locale: Locale = 'es'): SlashCommand[] {
  const own = matchCommands(input, slashCommandsFor(locale));
  return own.length > 0 || locale === 'es' ? own : matchCommands(input, SLASH_COMMANDS);
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
  // Both spellings of every command are recognised, whatever language is showing.
  for (const sc of [...SLASH_COMMANDS, ...slashCommandsFor('en')]) {
    if (lower.startsWith(sc.command)) {
      const question = input.slice(sc.command.length).trim();
      return { intent_hint: sc.intent_hint, question };
    }
  }
  return null;
}
