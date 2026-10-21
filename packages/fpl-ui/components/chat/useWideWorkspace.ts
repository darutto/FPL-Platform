'use client';

import { useEffect, useState } from 'react';

const KEY = 'fpl-workspace-panels';
type Preferences = { squad?: boolean; commands?: boolean };

/** Keep user choices separate from breakpoint defaults, including on resize. */
export function useWideWorkspace(enabled: boolean) {
  const [wide, setWide] = useState(false);
  const [threeColumns, setThreeColumns] = useState(false);
  const [preferences, setPreferences] = useState<Preferences>({});
  useEffect(() => {
    if (!enabled || !window.matchMedia) return;
    const workspace = window.matchMedia('(min-width: 1280px)');
    const three = window.matchMedia('(min-width: 1440px)');
    const update = () => { setWide(workspace.matches); setThreeColumns(three.matches); };
    update();
    workspace.addEventListener('change', update);
    three.addEventListener('change', update);
    try {
      const saved = JSON.parse(localStorage.getItem(KEY) ?? '{}');
      setPreferences({
        squad: typeof saved?.squad === 'boolean' ? saved.squad : undefined,
        commands: typeof saved?.commands === 'boolean' ? saved.commands : undefined,
      });
    } catch { /* Storage is optional. Breakpoint defaults still work. */ }
    return () => {
      workspace.removeEventListener('change', update);
      three.removeEventListener('change', update);
    };
  }, [enabled]);
  const squad = preferences.squad ?? threeColumns;
  const commands = preferences.commands ?? true;
  const toggle = (panel: keyof Preferences) => {
    const next = { ...preferences, [panel]: !(panel === 'squad' ? squad : commands) };
    setPreferences(next);
    try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* optional */ }
  };
  return { wide: enabled && wide, squad, commands, toggle };
}
