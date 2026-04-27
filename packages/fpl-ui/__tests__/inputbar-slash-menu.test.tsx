/**
 * @jest-environment jsdom
 *
 * InputBar + SlashMenu interaction tests — V2 Phase 2g1
 *
 * Renders the real InputBar (which composes SlashMenu) and exercises the
 * actual DOM interaction path: typing, keyboard navigation, click selection,
 * and plain-text submission.
 *
 * Dependency justification:
 *   @testing-library/react  — standard React DOM rendering in jest
 *   @testing-library/user-event — realistic event simulation (keydown
 *     sequences, focus model, mousedown/click) vs. fireEvent
 *   jest-environment-jsdom  — DOM for this file only; existing tests stay
 *     on the node environment via the default jest.config.ts
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import InputBar from '../components/chat/InputBar';
import { SLASH_COMMANDS } from '../lib/slash-commands';
import { optionId } from '../components/chat/SlashMenu';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function setup(onSubmit = jest.fn()) {
  const user = userEvent.setup();
  render(<InputBar onSubmit={onSubmit} />);
  const textarea = screen.getByRole('textbox', { name: /pregunta/i });
  return { user, textarea, onSubmit };
}

function getMenu() {
  return screen.queryByRole('listbox', { name: /comandos/i });
}

function getMenuItems() {
  const menu = getMenu();
  if (!menu) return [];
  return within(menu).getAllByRole('option');
}

// ---------------------------------------------------------------------------
// Menu visibility
// ---------------------------------------------------------------------------

describe('InputBar + SlashMenu — menu visibility', () => {
  test('menu is not rendered on initial mount', () => {
    setup();
    expect(getMenu()).toBeNull();
  });

  test('typing "/" opens the menu with all commands', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    expect(getMenu()).not.toBeNull();
    expect(getMenuItems()).toHaveLength(SLASH_COMMANDS.length);
  });

  test('plain text does not open the menu', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, 'should I captain Haaland');
    expect(getMenu()).toBeNull();
  });

  test('clearing the input after "/" closes the menu', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    expect(getMenu()).not.toBeNull();
    await user.clear(textarea);
    expect(getMenu()).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Filtering
// ---------------------------------------------------------------------------

describe('InputBar + SlashMenu — filtering', () => {
  test('typing "/cap" shows only /capitan', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/cap');
    const items = getMenuItems();
    expect(items).toHaveLength(1);
    expect(items[0].textContent).toContain('/capitan');
  });

  test('typing "/t" shows only /transferencia', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/t');
    const items = getMenuItems();
    expect(items).toHaveLength(1);
    expect(items[0].textContent).toContain('/transferencia');
  });

  test('typing "/c" shows four commands (/capitan, /comparar, /calendarios, /chips)', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/c');
    expect(getMenuItems()).toHaveLength(4);
  });

  test('typing "/xyz" shows no commands', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/xyz');
    expect(getMenu()).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Keyboard navigation
// ---------------------------------------------------------------------------

describe('InputBar + SlashMenu — keyboard navigation', () => {
  test('first item is active on menu open (aria-selected=true)', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    const items = getMenuItems();
    expect(items[0]).toHaveAttribute('aria-selected', 'true');
    expect(items[1]).toHaveAttribute('aria-selected', 'false');
  });

  test('ArrowDown moves active item to second entry', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    await user.keyboard('{ArrowDown}');
    const items = getMenuItems();
    expect(items[0]).toHaveAttribute('aria-selected', 'false');
    expect(items[1]).toHaveAttribute('aria-selected', 'true');
  });

  test('ArrowDown from last item does not overflow', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    const count = SLASH_COMMANDS.length;
    for (let i = 0; i < count + 3; i++) {
      await user.keyboard('{ArrowDown}');
    }
    const items = getMenuItems();
    expect(items[count - 1]).toHaveAttribute('aria-selected', 'true');
  });

  test('ArrowUp from first item stays at first item', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    await user.keyboard('{ArrowUp}');
    const items = getMenuItems();
    expect(items[0]).toHaveAttribute('aria-selected', 'true');
  });

  test('ArrowDown then ArrowUp returns to first item', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    await user.keyboard('{ArrowDown}');
    await user.keyboard('{ArrowUp}');
    const items = getMenuItems();
    expect(items[0]).toHaveAttribute('aria-selected', 'true');
  });

  test('Enter when menu is open selects the active command', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    // Default active is the first command
    await user.keyboard('{Enter}');
    // Menu should now be closed (value became "command "), and textarea
    // should contain the command prefix
    expect(getMenu()).toBeNull();
    expect((textarea as HTMLTextAreaElement).value).toBe(
      SLASH_COMMANDS[0].command + ' ',
    );
  });

  test('Enter after ArrowDown selects the second command', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    await user.keyboard('{ArrowDown}');
    await user.keyboard('{Enter}');
    expect((textarea as HTMLTextAreaElement).value).toBe(
      SLASH_COMMANDS[1].command + ' ',
    );
  });

  test('Escape closes the menu and clears the slash input', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/cap');
    expect(getMenu()).not.toBeNull();
    await user.keyboard('{Escape}');
    expect(getMenu()).toBeNull();
    expect((textarea as HTMLTextAreaElement).value).toBe('');
  });
});

// ---------------------------------------------------------------------------
// Enter submits when menu is closed
// ---------------------------------------------------------------------------

describe('InputBar + SlashMenu — Enter submits when menu is closed', () => {
  test('Enter on plain text calls onSubmit with the text', async () => {
    const { user, textarea, onSubmit } = setup();
    await user.click(textarea);
    await user.type(textarea, 'should I captain Haaland');
    await user.keyboard('{Enter}');
    expect(onSubmit).toHaveBeenCalledWith('should I captain Haaland');
  });

  test('Enter on complete slash command (with argument) submits', async () => {
    const { user, textarea, onSubmit } = setup();
    await user.click(textarea);
    // "/capitan Haaland" — menu is closed because it has no more prefix matches
    await user.type(textarea, '/capitan Haaland');
    await user.keyboard('{Enter}');
    expect(onSubmit).toHaveBeenCalledWith('/capitan Haaland');
  });

  test('textarea is cleared after submission', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, 'plain question');
    await user.keyboard('{Enter}');
    expect((textarea as HTMLTextAreaElement).value).toBe('');
  });

  test('Shift+Enter does not submit', async () => {
    const { user, textarea, onSubmit } = setup();
    await user.click(textarea);
    await user.type(textarea, 'test question');
    await user.keyboard('{Shift>}{Enter}{/Shift}');
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Mouse selection
// ---------------------------------------------------------------------------

describe('InputBar + SlashMenu — mouse selection', () => {
  test('clicking a menu item inserts its command prefix', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    const items = getMenuItems();
    await user.click(items[1]); // click second command
    expect((textarea as HTMLTextAreaElement).value).toBe(
      SLASH_COMMANDS[1].command + ' ',
    );
  });

  test('menu closes after mouse selection', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    const items = getMenuItems();
    await user.click(items[0]);
    expect(getMenu()).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// ARIA attributes and focus retention
// ---------------------------------------------------------------------------

describe('InputBar + SlashMenu — ARIA attributes and focus retention', () => {
  test('aria-expanded is false before any input', () => {
    setup();
    const textarea = screen.getByRole('textbox', { name: /pregunta/i });
    expect(textarea).toHaveAttribute('aria-expanded', 'false');
  });

  test('aria-expanded becomes true when menu opens', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    expect(textarea).toHaveAttribute('aria-expanded', 'true');
  });

  test('aria-expanded returns to false when menu closes', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    await user.keyboard('{Escape}');
    expect(textarea).toHaveAttribute('aria-expanded', 'false');
  });

  test('aria-controls is absent when menu is closed', () => {
    setup();
    const textarea = screen.getByRole('textbox', { name: /pregunta/i });
    expect(textarea).not.toHaveAttribute('aria-controls');
  });

  test('aria-controls targets the listbox id when menu is open', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    const menu = getMenu()!;
    expect(textarea).toHaveAttribute('aria-controls', menu.id);
    expect(menu.id).toBeTruthy();
  });

  test('aria-activedescendant is absent when menu is closed', () => {
    setup();
    const textarea = screen.getByRole('textbox', { name: /pregunta/i });
    expect(textarea).not.toHaveAttribute('aria-activedescendant');
  });

  test('aria-activedescendant references the first option when menu opens', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    const expectedId = optionId(SLASH_COMMANDS[0].command);
    expect(textarea).toHaveAttribute('aria-activedescendant', expectedId);
    expect(document.getElementById(expectedId)).not.toBeNull();
  });

  test('aria-activedescendant updates as ArrowDown moves selection', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    await user.keyboard('{ArrowDown}');
    const expectedId = optionId(SLASH_COMMANDS[1].command);
    expect(textarea).toHaveAttribute('aria-activedescendant', expectedId);
  });

  test('aria-activedescendant returns to first option after ArrowDown then ArrowUp', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    await user.keyboard('{ArrowDown}');
    await user.keyboard('{ArrowUp}');
    const expectedId = optionId(SLASH_COMMANDS[0].command);
    expect(textarea).toHaveAttribute('aria-activedescendant', expectedId);
  });

  test('textarea remains focused after mouse selection of a menu item', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    const items = getMenuItems();
    await user.click(items[0]);
    expect(document.activeElement).toBe(textarea);
  });
});

// ---------------------------------------------------------------------------
// Placeholder after selection
// ---------------------------------------------------------------------------

describe('InputBar + SlashMenu — placeholder after selection', () => {
  test('selecting /capitan shows its placeholder in the textarea', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    await user.keyboard('{Enter}'); // selects /capitan (first command)
    const sc = SLASH_COMMANDS.find((c) => c.command === '/capitan')!;
    expect(textarea).toHaveAttribute('placeholder', sc.placeholder);
  });

  test('clearing input after selection resets to default placeholder', async () => {
    const { user, textarea } = setup();
    await user.click(textarea);
    await user.type(textarea, '/');
    await user.keyboard('{Enter}'); // select first command
    await user.clear(textarea);
    await user.type(textarea, 'plain text');
    expect(textarea).not.toHaveAttribute('placeholder', SLASH_COMMANDS[0].placeholder);
  });
});
