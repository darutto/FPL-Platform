/**
 * buildDynamicPrompts — weaves live top buys/sells into the chat starter chips.
 */
import { buildDynamicPrompts, staticPrompts } from '../components/chat/StarterPrompts';
import { parseSlashCommand } from '../lib/slash-commands';

describe('buildDynamicPrompts', () => {
  test('anchors compare/transfer/calendar on the hottest buy + sell', () => {
    const prompts = buildDynamicPrompts(['Haaland', 'Watkins'], ['Saka', 'Palmer']);
    expect(prompts).toContain('/comparar Haaland vs Watkins');
    expect(prompts).toContain('/transferencia Saka por Haaland');
    expect(prompts).toContain('/calendarios Haaland');
  });

  test('keeps the three generic (name-free) prompts', () => {
    const prompts = buildDynamicPrompts(['Haaland', 'Watkins'], ['Saka']);
    expect(prompts).toContain('¿A quién debería dar el brazalete?');
    expect(prompts).toContain('¿Debería usar el triple capitán?');
    expect(prompts).toContain('/diferenciales menos del 10%');
    expect(prompts).toHaveLength(6);
  });

  test('never suggests selling the same player it says to buy', () => {
    // Hottest buy and hottest sell collide → pick the next distinct sell.
    const prompts = buildDynamicPrompts(['Haaland', 'Watkins'], ['Haaland', 'Gyökeres']);
    expect(prompts).toContain('/transferencia Gyökeres por Haaland');
    expect(prompts).not.toContain('/transferencia Haaland por Haaland');
  });
});

/**
 * Every starter chip that begins with "/" must be a command the app and the backend both know, in both languages:
 * a chip that parses to nothing would be sent as free text and fall to the orchestrator.
 */
describe('starter chips are real commands', () => {
  const EXPECTED_HINT: Record<string, string> = {
    '/comparar': 'compare_players', '/compare': 'compare_players',
    '/transferencia': 'transfer_advice', '/transfer': 'transfer_advice',
    '/calendarios': 'player_fixture_run', '/fixtures': 'player_fixture_run',
    '/diferenciales': 'differential_picks', '/differentials': 'differential_picks',
  };

  test.each(['es', 'en'] as const)('(%s) static and live chips parse to the intended command', (locale) => {
    const chips = [...staticPrompts(locale), ...buildDynamicPrompts(['Haaland', 'Watkins'], ['Saka'], locale)];
    const slash = chips.filter((c) => c.startsWith('/'));
    expect(slash.length).toBeGreaterThanOrEqual(6);
    for (const chip of slash) {
      const command = chip.split(' ')[0];
      expect(EXPECTED_HINT[command]).toBeDefined();
      expect(parseSlashCommand(chip)?.intent_hint).toBe(EXPECTED_HINT[command]);
    }
  });

  test('English chips use the English command names, Spanish chips the Spanish ones', () => {
    expect(staticPrompts('en').filter((c) => c.startsWith('/')).map((c) => c.split(' ')[0]))
      .toEqual(['/compare', '/differentials', '/transfer', '/fixtures']);
    expect(staticPrompts('es').filter((c) => c.startsWith('/')).map((c) => c.split(' ')[0]))
      .toEqual(['/comparar', '/diferenciales', '/transferencia', '/calendarios']);
  });
});
