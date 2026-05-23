'use client';

/**
 * QuotaIndicator — compact footer widget showing daily/monthly quota usage.
 *
 * Polls GET /api/quota?user_id=<id>&tier=<tier> on mount and whenever
 * refreshTrigger changes (caller increments it after each sent message).
 *
 * Color logic:
 *   remaining / cap > 0.5  → green  (plenty of quota left)
 *   0.2–0.5                → amber  (approaching limit)
 *   < 0.2                  → red    (near / at limit)
 *
 * Click → opens an inline modal with tier comparison + Patreon upgrade CTA.
 */

import { useEffect, useState, useCallback } from 'react';
import type { QuotaStatus } from '@/lib/types';

interface Props {
  userId?: string;       // defaults to 'anonymous'
  tier?: string;         // defaults to 'free'
  refreshTrigger?: number; // increment to force re-fetch after a turn
}

// ---------------------------------------------------------------------------
// Color helpers
// ---------------------------------------------------------------------------

function pctColor(remaining: number, cap: number): string {
  if (cap <= 0) return 'text-red-400 border-red-500/40 bg-red-500/10';
  const pct = remaining / cap;
  if (pct > 0.5) return 'text-emerald-300 border-emerald-500/40 bg-emerald-500/10';
  if (pct > 0.2) return 'text-amber-300 border-amber-500/40 bg-amber-500/10';
  return 'text-red-400 border-red-500/40 bg-red-500/10';
}

function dotColor(remaining: number, cap: number): string {
  if (cap <= 0) return 'bg-red-400';
  const pct = remaining / cap;
  if (pct > 0.5) return 'bg-emerald-400';
  if (pct > 0.2) return 'bg-amber-400';
  return 'bg-red-400';
}

// ---------------------------------------------------------------------------
// Tier comparison table for modal
// ---------------------------------------------------------------------------

const TIER_TABLE = [
  { tier: 'Free',             daily: 5,   monthly: 30,   link: false },
  { tier: 'Patreon $5',       daily: 30,  monthly: 600,  link: true  },
  { tier: 'Patreon $15',      daily: 150, monthly: 3000, link: true  },
  { tier: 'Patreon $30',      daily: '∞', monthly: 10000, link: true },
] as const;

const PATREON_URL = 'https://www.patreon.com/fpl_asistente';

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function QuotaIndicator({
  userId = 'anonymous',
  tier = 'free',
  refreshTrigger = 0,
}: Props) {
  const [status, setStatus] = useState<QuotaStatus | null>(null);
  const [fetchError, setFetchError] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  const fetchQuota = useCallback(async () => {
    try {
      const params = new URLSearchParams({ user_id: userId, tier });
      const res = await fetch(`/api/quota?${params.toString()}`);
      if (!res.ok) {
        setFetchError(true);
        return;
      }
      const data: QuotaStatus = await res.json();
      setStatus(data);
      setFetchError(false);
    } catch {
      setFetchError(true);
    }
  }, [userId, tier]);

  useEffect(() => {
    fetchQuota();
  }, [fetchQuota, refreshTrigger]);

  // Don't render if still loading on first mount or if quota fetch fails silently
  if (!status && !fetchError) return null;
  if (fetchError) return null;
  if (!status) return null;

  const dailyRemaining = status.daily_message_cap - status.daily_message_count;
  const monthlyRemaining = status.monthly_message_cap - status.monthly_message_count;

  // Determine which is more constraining (lower %)
  const dailyPct = status.daily_message_cap > 0
    ? dailyRemaining / status.daily_message_cap
    : 0;
  const monthlyPct = status.monthly_message_cap > 0
    ? monthlyRemaining / status.monthly_message_cap
    : 0;
  const constrainingPct = Math.min(dailyPct, monthlyPct);
  const pillColor = constrainingPct > 0.5
    ? 'text-emerald-300 border-emerald-500/40 bg-emerald-500/10'
    : constrainingPct > 0.2
      ? 'text-amber-300 border-amber-500/40 bg-amber-500/10'
      : 'text-red-400 border-red-500/40 bg-red-500/10';

  return (
    <>
      {/* Compact pill widget */}
      <button
        onClick={() => setModalOpen(true)}
        title={`Cuota diaria: ${dailyRemaining}/${status.daily_message_cap} msgs · Mensual: ${monthlyRemaining}/${status.monthly_message_cap} msgs\nTokens diarios: ${status.daily_token_cap - status.daily_tokens_used}/${status.daily_token_cap} · Mensuales: ${status.monthly_token_cap - status.monthly_tokens_used}/${status.monthly_token_cap}`}
        className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors hover:opacity-80 ${pillColor}`}
      >
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotColor(dailyRemaining, status.daily_message_cap)}`} />
        <span>
          Día {dailyRemaining}/{status.daily_message_cap}
        </span>
        <span className="opacity-50">·</span>
        <span>
          Mes {monthlyRemaining}/{status.monthly_message_cap}
        </span>
      </button>

      {/* Tier upgrade modal */}
      {modalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => setModalOpen(false)}
        >
          <div
            className="relative w-full max-w-sm mx-4 rounded-2xl border border-gray-700 bg-gray-900 p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-white">Cuota de mensajes</h2>
              <button
                onClick={() => setModalOpen(false)}
                className="text-gray-500 hover:text-gray-300 text-lg leading-none"
                aria-label="Cerrar"
              >
                ✕
              </button>
            </div>

            {/* Current usage summary */}
            <div className="mb-4 rounded-xl border border-gray-700 bg-gray-800 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-gray-400">Hoy</span>
                <span className={`text-[11px] font-medium ${pctColor(dailyRemaining, status.daily_message_cap)}`}>
                  {dailyRemaining} msgs restantes
                </span>
              </div>
              {/* Daily bar */}
              <div className="h-1.5 w-full rounded-full bg-gray-700 overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${
                    dailyPct > 0.5 ? 'bg-emerald-400' : dailyPct > 0.2 ? 'bg-amber-400' : 'bg-red-400'
                  }`}
                  style={{ width: `${Math.max(0, Math.min(100, dailyPct * 100)).toFixed(1)}%` }}
                />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-gray-400">Este mes</span>
                <span className={`text-[11px] font-medium ${pctColor(monthlyRemaining, status.monthly_message_cap)}`}>
                  {monthlyRemaining} msgs restantes
                </span>
              </div>
              {/* Monthly bar */}
              <div className="h-1.5 w-full rounded-full bg-gray-700 overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${
                    monthlyPct > 0.5 ? 'bg-emerald-400' : monthlyPct > 0.2 ? 'bg-amber-400' : 'bg-red-400'
                  }`}
                  style={{ width: `${Math.max(0, Math.min(100, monthlyPct * 100)).toFixed(1)}%` }}
                />
              </div>
              <p className="text-[10px] text-gray-500 pt-1">
                Tier actual: <span className="font-medium text-gray-400">{status.tier}</span>
              </p>
            </div>

            {/* Tier comparison table */}
            <table className="w-full text-[11px] mb-4">
              <thead>
                <tr className="border-b border-gray-700">
                  <th className="text-left text-gray-400 font-medium pb-1.5">Plan</th>
                  <th className="text-right text-gray-400 font-medium pb-1.5">Día</th>
                  <th className="text-right text-gray-400 font-medium pb-1.5">Mes</th>
                </tr>
              </thead>
              <tbody>
                {TIER_TABLE.map((row) => (
                  <tr
                    key={row.tier}
                    className={`border-b border-gray-800 ${row.tier.toLowerCase().startsWith(status.tier) ? 'text-white font-medium' : 'text-gray-400'}`}
                  >
                    <td className="py-1.5">{row.tier}</td>
                    <td className="text-right py-1.5">{row.daily}</td>
                    <td className="text-right py-1.5">{row.monthly}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Upgrade CTA */}
            <a
              href={PATREON_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="block w-full rounded-xl bg-orange-500 hover:bg-orange-400 text-white text-center text-xs font-semibold py-2.5 transition-colors"
            >
              Mejorar en Patreon
            </a>
          </div>
        </div>
      )}
    </>
  );
}
