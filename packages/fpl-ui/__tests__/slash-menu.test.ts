/**
 * SlashMenu behavior tests — V2 Phase 2g
 *
 * Pure function tests: no React, no DOM, no jsdom required.
 *
 * Coverage:
 *   1. Menu visibility — matchSlashCommands drives open/closed state
 *   2. Command filtering — prefix narrowing as the user types
 *   3. Command selection — value after selection parses correctly through
 *      the existing parseSlashCommand() path (no regression)
 *   4. Keyboard navigation — activeIndex clamping at boundaries
 *   5. Placeholder selection — correct placeholder text per command
 *   6. No-regression — plain text never triggers the menu
 */
import {
  matchSlashCommands,
  parseSlashCommand,
  SLASH_COMMANDS,
  type SlashCommand,
} from '../lib/slash-commands';

// ---------------------------------------------------------------------------
// Helpers: mirrors InputBar's activeIndex management in pure form
// ---------------------------------------------------------------------------

function clampIndex(current: number, delta: number, max: number): number {
  return Math.min(Math.max(current + delta, 0), max);
}

/** After handleSelect, the inserted value is `command + ' '`. */
function insertedValue(sc: SlashCommand): string {
  return sc.command + ' ';
}

// ---------------------------------------------------------------------------
// Menu visibility — driven by matchSlashCommands
// ---------------------------------------------------------------------------

describe('slash menu visibility', () => {
  test('"/" opens menu with all commands', () => {
    expect(matchSlashCommands('/')).toHaveLength(SLASH_COMMANDS.length);
  });

  test('empty string → no menu', () => {
    expect(matchSlashCommands('')).toHaveLength(0);
  });

  test('plain text without slash → no menu', () => {
    expect(matchSlashCommands('should I captain Haaland')).toHaveLength(0);
  });

  test('space before slash → no menu (does not start with /)', () => {
    expect(matchSlashCommands(' /capitan')).toHaveLength(0);
  });

  test('complete command with argument → menu closes (no prefix match)', () => {
    // "/capitan Haaland" — the registered command is "/capitan", the input
    // is longer than any registered command prefix, so no match.
    expect(matchSlashCommands('/capitan Haaland')).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Command filtering — prefix narrowing
// ---------------------------------------------------------------------------

describe('slash menu filtering', () => {
  test('"/cap" → only /capitan', () => {
    const matches = matchSlashCommands('/cap');
    expect(matches).toHaveLength(1);
    expect(matches[0].command).toBe('/capitan');
  });

  test('"/com" → only /comparar', () => {
    const matches = matchSlashCommands('/com');
    expect(matches).toHaveLength(1);
    expect(matches[0].command).toBe('/comparar');
  });

  test('"/c" → /capitan, /comparar, /calendarios, /chips (4 commands starting with /c)', () => {
    const matches = matchSlashCommands('/c');
    const commands = matches.map((m) => m.command);
    expect(commands).toContain('/capitan');
    expect(commands).toContain('/comparar');
    expect(commands).toContain('/calendarios');
    expect(commands).toContain('/chips');
    expect(commands).not.toContain('/transferencia');
    expect(commands).not.toContain('/diferenciales');
  });

  test('"/t" → only /transferencia', () => {
    const matches = matchSlashCommands('/t');
    expect(matches).toHaveLength(1);
    expect(matches[0].command).toBe('/transferencia');
  });

  test('"/d" → only /diferenciales', () => {
    const matches = matchSlashCommands('/d');
    expect(matches).toHaveLength(1);
    expect(matches[0].command).toBe('/diferenciales');
  });

  test('"/xyz" → no matches', () => {
    expect(matchSlashCommands('/xyz')).toHaveLength(0);
  });

  test('filter is case-insensitive', () => {
    expect(matchSlashCommands('/CAP')).toHaveLength(1);
    expect(matchSlashCommands('/CAP')[0].command).toBe('/capitan');
  });
});

// ---------------------------------------------------------------------------
// Command selection — post-select value routes through parseSlashCommand
// ---------------------------------------------------------------------------

describe('command selection — parseSlashCommand regression', () => {
  for (const sc of SLASH_COMMANDS) {
    test(`selecting ${sc.command} → inserted value parses with intent_hint="${sc.intent_hint}"`, () => {
      // After handleSelect, value = sc.command + ' '
      // After the user types a question: sc.command + ' ' + 'some question'
      const withQuestion = insertedValue(sc) + 'some question';
      const parsed = parseSlashCommand(withQuestion);
      expect(parsed).not.toBeNull();
      expect(parsed!.intent_hint).toBe(sc.intent_hint);
      expect(parsed!.question).toBe('some question');
    });
  }

  test('inserted value with no trailing question still parses (question is empty string)', () => {
    const sc = SLASH_COMMANDS[0];
    const parsed = parseSlashCommand(insertedValue(sc));
    expect(parsed).not.toBeNull();
    expect(parsed!.question).toBe('');
  });

  test('menu is closed after selection (inserted value has no further prefix match)', () => {
    // insertedValue = "/capitan " — the trailing space means it's no longer
    // a prefix-only match for any command ("/capitan " !== "/capitan")
    const value = insertedValue(SLASH_COMMANDS[0]);
    expect(matchSlashCommands(value)).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Keyboard navigation — activeIndex clamping
// ---------------------------------------------------------------------------

describe('keyboard navigation — activeIndex clamping', () => {
  const max = SLASH_COMMANDS.length - 1; // 5 for 6 commands

  test('ArrowDown from 0 → 1', () => {
    expect(clampIndex(0, +1, max)).toBe(1);
  });

  test('ArrowDown from max → stays at max (no overflow)', () => {
    expect(clampIndex(max, +1, max)).toBe(max);
  });

  test('ArrowUp from 1 → 0', () => {
    expect(clampIndex(1, -1, max)).toBe(0);
  });

  test('ArrowUp from 0 → stays at 0 (no underflow)', () => {
    expect(clampIndex(0, -1, max)).toBe(0);
  });

  test('ArrowDown then ArrowUp returns to start', () => {
    let idx = 0;
    idx = clampIndex(idx, +1, max);
    idx = clampIndex(idx, +1, max);
    idx = clampIndex(idx, -1, max);
    idx = clampIndex(idx, -1, max);
    expect(idx).toBe(0);
  });

  test('filtered menu: clamping respects reduced length', () => {
    const filtered = matchSlashCommands('/cap'); // length 1, max = 0
    const filteredMax = filtered.length - 1;     // 0
    expect(clampIndex(0, +1, filteredMax)).toBe(0); // can't go below single item
  });
});

// ---------------------------------------------------------------------------
// Placeholder — command-specific hint text
// ---------------------------------------------------------------------------

describe('command placeholder text', () => {
  test('every command has a non-empty placeholder', () => {
    for (const sc of SLASH_COMMANDS) {
      expect(sc.placeholder).toBeTruthy();
    }
  });

  test('/capitan placeholder contains "Haaland" (player example)', () => {
    const sc = SLASH_COMMANDS.find((s) => s.command === '/capitan')!;
    expect(sc.placeholder.toLowerCase()).toContain('haaland');
  });

  test('/comparar placeholder contains "vs" (comparison example)', () => {
    const sc = SLASH_COMMANDS.find((s) => s.command === '/comparar')!;
    expect(sc.placeholder.toLowerCase()).toContain('vs');
  });

  test('/transferencia placeholder contains "por" (swap example)', () => {
    const sc = SLASH_COMMANDS.find((s) => s.command === '/transferencia')!;
    expect(sc.placeholder.toLowerCase()).toContain('por');
  });

  test('all placeholders are distinct (no copy-paste duplicates)', () => {
    const placeholders = SLASH_COMMANDS.map((sc) => sc.placeholder);
    expect(new Set(placeholders).size).toBe(SLASH_COMMANDS.length);
  });
});

// ---------------------------------------------------------------------------
// No-regression — plain text and non-slash input
// ---------------------------------------------------------------------------

describe('plain text — no slash menu regression', () => {
  test('typing a question without / never triggers menu', () => {
    const inputs = [
      'should I captain Haaland',
      '¿Capitanear a Haaland?',
      'comparar Salah Saka',
      '',
      '  ',
    ];
    for (const input of inputs) {
      expect(matchSlashCommands(input)).toHaveLength(0);
    }
  });

  test('parseSlashCommand returns null for plain text (no regression)', () => {
    expect(parseSlashCommand('should I captain Haaland')).toBeNull();
    expect(parseSlashCommand('¿Capitanear a Haaland?')).toBeNull();
  });

  test('parseSlashCommand still works after slash selection (unchanged routing)', () => {
    const result = parseSlashCommand('/capitan Haaland');
    expect(result).not.toBeNull();
    expect(result!.intent_hint).toBe('captain_score');
    expect(result!.question).toBe('Haaland');
  });
});
