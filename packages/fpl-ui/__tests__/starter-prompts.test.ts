/**
 * buildDynamicPrompts — weaves live top buys/sells into the chat starter chips.
 */
import { buildDynamicPrompts } from '../components/chat/StarterPrompts';

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
