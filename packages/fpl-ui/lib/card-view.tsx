'use client';

/**
 * card-view — what a viewer has chosen on a card, shared with the off-screen copy that becomes the share image.
 *
 * `TeamAxisProvider` wraps one chat message, so the card on screen and its share copy read the same
 * attack/defence choice. Without it a card keeps its own. (Whether a card is the share copy is
 * `useSharedImage` in chat-ask: there it draws no controls, only what was chosen.)
 */
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import type { FixtureAxis } from './types';

type AxisState = [FixtureAxis, (axis: FixtureAxis) => void];

const TeamAxisContext = createContext<AxisState | null>(null);

export function TeamAxisProvider({ children }: { children: ReactNode }) {
  const [axis, setAxis] = useState<FixtureAxis>('attack');
  const value = useMemo<AxisState>(() => [axis, setAxis], [axis]);
  return <TeamAxisContext.Provider value={value}>{children}</TeamAxisContext.Provider>;
}

/** The axis starts on attack, as the /fixtures calendar does. */
export function useTeamAxis(): AxisState {
  const shared = useContext(TeamAxisContext);
  const own = useState<FixtureAxis>('attack');
  return shared ?? own;
}
