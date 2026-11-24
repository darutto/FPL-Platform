'use client';

/**
 * Automatic retry of a "computing" EO answer.
 *
 * The backend marks such a reply with `pending` ({tool, league_id?, league_name?, eta_s, poll_s, max_s}). This hook then
 * calls POST /eo/poll every `poll_s` seconds (no model, no quota turn) until the card is ready, hands it to
 * `onReady`, and gives up after `max_s` seconds, when the chat offers «Reintentar».
 *
 * One poll at a time per conversation: a newer marker replaces the older one, a new user message cancels it.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { eoPoll, FplApiError } from './api';
import type { EoPending, EoPollResponse } from './types';

export interface EoPollState {
  messageId: string;
  marker: EoPending;
  startedAt: number;
  timedOut: boolean;
}

interface Options {
  teamId: number | null;
  locale: string;
  onReady: (messageId: string, reply: EoPollResponse) => void;
}

export function useEoPoll({ teamId, locale, onReady }: Options) {
  const [state, setState] = useState<EoPollState | null>(null);
  const onReadyRef = useRef(onReady);
  const teamRef = useRef(teamId);
  const localeRef = useRef(locale);
  onReadyRef.current = onReady;
  teamRef.current = teamId;
  localeRef.current = locale;

  const start = useCallback((messageId: string, marker: EoPending) => {
    setState({ messageId, marker, startedAt: Date.now(), timedOut: false });
  }, []);
  const cancel = useCallback(() => setState(null), []);
  const retry = useCallback(() => {
    setState((s) => (s ? { ...s, startedAt: Date.now(), timedOut: false } : s));
  }, []);

  const messageId = state?.messageId;
  const startedAt = state?.startedAt;
  const timedOut = state?.timedOut;

  useEffect(() => {
    if (state == null || timedOut) return;
    const { marker } = state;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const wait = (seconds: number) => {
      timer = setTimeout(tick, Math.max(1, seconds) * 1000);
    };
    const fail = () => {
      setState((s) => (s && s.messageId === state.messageId ? { ...s, timedOut: true } : s));
    };
    const tick = async () => {
      if (cancelled) return;
      if (Date.now() - state.startedAt >= marker.max_s * 1000) {
        fail();
        return;
      }
      const team = teamRef.current;
      if (team == null) {
        fail(); // no team to poll for: say so («Reintentar»), never go quiet
        return;
      }
      try {
        const reply = await eoPoll({
          tool: marker.tool,
          team_id: team,
          ...(marker.league_id != null ? { league_id: marker.league_id } : {}),
          ...(marker.league_name ? { league_name: marker.league_name } : {}),
          locale: localeRef.current,
        });
        if (cancelled) return;
        if (reply.status === 'computing') {
          wait(reply.poll_s ?? marker.poll_s);
        } else if (reply.status === 'ready' || reply.status === 'needs_league') {
          onReadyRef.current(state.messageId, reply);
          setState(null);
        } else {
          setState(null); // unavailable / disabled: the model's text stands
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof FplApiError && err.status === 429) wait(marker.poll_s); // too often: just wait
        else fail(); // 401 (no session), 5xx, network: a failed poll is visible, never silent
      }
    };
    wait(marker.poll_s);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // The effect restarts only for a new marker, a retry or the timeout; `state` itself is read once per run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messageId, startedAt, timedOut]);

  return { state, start, cancel, retry };
}
