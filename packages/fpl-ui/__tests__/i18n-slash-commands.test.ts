/**
 * The command registry in both languages. Spanish is the registry itself, untouched; English
 * keeps every intent_hint and only swaps names, labels and argument hints. A drift guard reads
 * the backend's own alias tables so a command we show in English can never be one it rejects.
 */
import { existsSync, readFileSync } from 'fs';
import { join } from 'path';
import { SLASH_COMMANDS, matchSlashCommands, parseSlashCommand, slashCommandsFor } from '@/lib/slash-commands';

const BACKEND = join(__dirname, '..', '..', 'fpl-grounded-assistant', 'fpl_grounded_assistant');
const backendFile = (name: string) => {
  const path = join(BACKEND, name);
  return existsSync(path) ? readFileSync(path, 'utf8') : null;
};

describe('slashCommandsFor', () => {
  test('Spanish is the registry itself, byte for byte', () => {
    expect(slashCommandsFor('es')).toBe(SLASH_COMMANDS);
    expect(SLASH_COMMANDS.map((c) => c.command)).toEqual([
      '/capitan', '/comparar', '/transferencia', '/calendarios', '/diferenciales', '/chips', '/clasificacion',
    ]);
  });

  test('English: the canonical names from the glossary, same intents, same order', () => {
    const en = slashCommandsFor('en');
    expect(en.map((c) => c.command)).toEqual([
      '/captain', '/compare', '/transfer', '/fixtures', '/differentials', '/chips', '/rankings',
    ]);
    expect(en.map((c) => c.intent_hint)).toEqual(SLASH_COMMANDS.map((c) => c.intent_hint));
    for (const c of en) {
      expect(c.label.trim()).not.toBe('');
      expect(c.placeholder.trim()).not.toBe('');
    }
  });

  test('the backend accepts every English name we show', () => {
    const registry = backendFile('prompt_registry.py');
    if (registry === null) return; // the backend package is not part of this checkout
    for (const { command } of slashCommandsFor('en')) {
      const name = command.slice(1);
      expect(registry).toMatch(new RegExp(`"${name}"\\s*:`));
    }
  });

  test('the backend resolves every English @view the panel inserts', () => {
    const aliases = backendFile('intent_aliases.py');
    if (aliases === null) return;
    for (const name of ['injuries', 'form', 'xg', 'points', 'minutes', 'popular']) {
      expect(aliases).toContain(`"${name}"`);
    }
  });
});

describe('matchSlashCommands', () => {
  test('Spanish matching is what it always was', () => {
    expect(matchSlashCommands('/c').map((c) => c.command)).toEqual(['/capitan', '/comparar', '/calendarios', '/chips', '/clasificacion']);
    expect(matchSlashCommands('hola')).toEqual([]);
  });

  test('English offers the English names first', () => {
    expect(matchSlashCommands('/c', 'en').map((c) => c.command)).toEqual(['/captain', '/compare', '/chips']);
    expect(matchSlashCommands('/ra', 'en').map((c) => c.command)).toEqual(['/rankings']);
  });

  test('English still finds a Spanish command when no English name matches the prefix', () => {
    expect(matchSlashCommands('/capi', 'en').map((c) => c.command)).toEqual(['/capitan']);
    expect(matchSlashCommands('/transf', 'en').map((c) => c.command)).toEqual(['/transfer']);
    expect(matchSlashCommands('/transfe', 'es').map((c) => c.command)).toEqual(['/transferencia']);
  });
});

describe('parseSlashCommand', () => {
  test('recognises both spellings of a command', () => {
    expect(parseSlashCommand('/captain Haaland')).toEqual({ intent_hint: 'captain_score', question: 'Haaland' });
    expect(parseSlashCommand('/capitan Haaland')).toEqual({ intent_hint: 'captain_score', question: 'Haaland' });
    expect(parseSlashCommand('/rankings')).toEqual({ intent_hint: 'rank_candidates', question: '' });
    expect(parseSlashCommand('who should I captain')).toBeNull();
  });
});
