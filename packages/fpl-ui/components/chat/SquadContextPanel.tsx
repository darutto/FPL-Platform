'use client';

/**
 * SquadContextPanel — lets the user attach real squad context to asks.
 *
 * Flow:
 *   1. User enters their FPL team ID.
 *   2. Panel fetches /api/fpl-entry/{teamId} (server-side proxy to FPL API).
 *   3. normalizeSquadContext() converts the raw data to SquadContext.
 *   4. onContextChange(ctx) propagates the context up to ChatShell.
 *   5. ChatShell passes squad_context on every subsequent ask.
 *
 * Persistence: team ID only is stored in localStorage so it pre-fills on
 * next visit. The context itself is re-fetched on mount/reconnect — the FPL
 * API data is live and should not be cached client-side.
 *
 * No auth. No server-side persistence. Public FPL API only.
 */
import { useState, useEffect, useCallback } from 'react';
import type { SquadContext } from '@/lib/types';
import {
  validateTeamId,
  normalizeSquadContext,
  squadContextSummary,
  FT_OPTIONS,
  type FplEntryRaw,
  type FplEntryResponse,
} from '@/lib/squad-context';

const LS_KEY = 'fpl_team_id';

interface Props {
  onContextChange: (ctx: SquadContext | null) => void;
}

type PanelState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'connected'; entry: FplEntryRaw; ctx: SquadContext }
  | { status: 'error'; message: string };

export default function SquadContextPanel({ onContextChange }: Props) {
  const [teamIdInput, setTeamIdInput] = useState('');
  const [panel, setPanel] = useState<PanelState>({ status: 'idle' });
  // Free transfers: not derivable from the FPL API. User selects explicitly.
  // null = not set; backend will omit hit_warning signal when unknown.
  const [freeTransfers, setFreeTransfers] = useState<number | null>(null);

  // Pre-fill team ID from localStorage on mount, but do not auto-fetch
  // (user must confirm; data should be fresh when explicitly requested).
  useEffect(() => {
    try {
      const stored = localStorage.getItem(LS_KEY);
      if (stored) setTeamIdInput(stored);
    } catch {
      // localStorage unavailable (SSR guard)
    }
  }, []);

  const handleConnect = useCallback(async () => {
    const teamId = validateTeamId(teamIdInput);
    if (teamId === null) {
      setPanel({ status: 'error', message: 'ID de equipo no válido — debe ser un número positivo.' });
      return;
    }

    setPanel({ status: 'loading' });

    let data: FplEntryResponse;
    try {
      const res = await fetch(`/api/fpl-entry/${teamId}`);
      if (res.status === 404) {
        setPanel({ status: 'error', message: 'No se encontró el equipo. Comprueba el ID.' });
        return;
      }
      if (!res.ok) {
        setPanel({ status: 'error', message: `Error al obtener datos (${res.status}). Inténtalo de nuevo.` });
        return;
      }
      data = await res.json() as FplEntryResponse;
    } catch {
      setPanel({ status: 'error', message: 'No se pudo conectar con la API de FPL. Inténtalo de nuevo.' });
      return;
    }

    const ctx = normalizeSquadContext(data.entry, data.history);
    setPanel({ status: 'connected', entry: data.entry, ctx });
    onContextChange(ctx);

    // Persist team ID (not context — context is re-fetched each time)
    try { localStorage.setItem(LS_KEY, String(teamId)); } catch { /* ignore */ }
  }, [teamIdInput, onContextChange]);

  const handleFtSelect = useCallback((ft: number | null) => {
    setFreeTransfers(ft);
    if (panel.status === 'connected') {
      onContextChange({ ...panel.ctx, free_transfers: ft });
    }
  }, [panel, onContextChange]);

  const handleDisconnect = useCallback(() => {
    setPanel({ status: 'idle' });
    setFreeTransfers(null);
    onContextChange(null);
    try { localStorage.removeItem(LS_KEY); } catch { /* ignore */ }
    setTeamIdInput('');
  }, [onContextChange]);

  return (
    <div className="flex items-center gap-2 text-xs">
      {panel.status === 'connected' ? (
        <>
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0" />
          <span className="text-gray-400 truncate max-w-[140px]">
            {squadContextSummary(panel.entry)}
          </span>

          {/* Free-transfer selector — user must set this; API cannot derive it. */}
          <span className="text-gray-600 flex-shrink-0">TL:</span>
          <div className="flex items-center gap-0.5 flex-shrink-0">
            {FT_OPTIONS.map((opt) => (
              <button
                key={opt ?? 'null'}
                onClick={() => handleFtSelect(opt)}
                className={`w-6 h-5 rounded text-[10px] transition-colors ${
                  freeTransfers === opt
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-800 text-gray-500 hover:text-gray-300'
                }`}
              >
                {opt ?? '—'}
              </button>
            ))}
          </div>

          <button
            onClick={handleDisconnect}
            className="text-gray-600 hover:text-gray-400 transition-colors flex-shrink-0"
          >
            Desconectar
          </button>
        </>
      ) : (
        <>
          <input
            type="text"
            inputMode="numeric"
            value={teamIdInput}
            onChange={(e) => {
              setTeamIdInput(e.target.value);
              if (panel.status === 'error') setPanel({ status: 'idle' });
            }}
            onKeyDown={(e) => { if (e.key === 'Enter') handleConnect(); }}
            placeholder="ID de equipo FPL"
            disabled={panel.status === 'loading'}
            className={`w-36 bg-gray-900 border rounded px-2 py-1 text-gray-300 placeholder-gray-600
              focus:outline-none focus:border-indigo-500 transition-colors disabled:opacity-50
              ${panel.status === 'error' ? 'border-red-600' : 'border-gray-700'}`}
          />
          <button
            onClick={handleConnect}
            disabled={panel.status === 'loading' || teamIdInput.trim() === ''}
            className="text-indigo-400 hover:text-indigo-300 transition-colors disabled:opacity-40 flex-shrink-0"
          >
            {panel.status === 'loading' ? 'Conectando…' : 'Conectar'}
          </button>
          {panel.status === 'error' && (
            <span className="text-red-400 truncate max-w-[160px]">{panel.message}</span>
          )}
        </>
      )}
    </div>
  );
}
